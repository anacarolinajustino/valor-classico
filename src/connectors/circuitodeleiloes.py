"""
Conector Circuito de Leilões — coleta PREÇOS REALIZADOS de leilão.

Site institucional: https://www.circuitodeleiloes.com.br (sem catálogo).
Fonte real de dados: plataforma do leiloeiro oficial Picelli Leilões
(https://www.picellileiloes.com.br), que expõe os lotes via Supabase REST
em api.picellileiloes.com.br. A chave `sb_publishable_*` é pública por
design (anon role + RLS) — a mesma entregue a qualquer visitante do site.

Diferença metodológica em relação aos demais conectores (ver
sprint2-spike-circuitodeleiloes.md): aqui o preço é REALIZADO (lance
vencedor homologado), não preço pedido. Somente lotes com status
"vendido" entram; "condicional" (pendente de homologação) fica fora.

Compliance (verificado 2026-06-10):
- robots.txt Picelli: User-agent: * → Allow: / (Content-Signal search=yes)
- Rate limit: 1 requisição por consulta (filtros server-side)
- User-Agent realista definido abaixo.

Separação de responsabilidades:
- buscar()         → I/O (requests) contra a API REST
- parsear_lotes()  → função pura, usada nos testes
- parsear_titulo() → função pura, parse do padrão DETRAN "MARCA/MODELO - ANO/ANO"
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date
from typing import Optional

import requests

from src.pipeline.normalizer import normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
# Configurações do conector
# ────────────────────────────────────────────────
FONTE = "circuitodeleiloes"
API_BASE = "https://api.picellileiloes.com.br/rest/v1"
SITE_BASE = "https://www.picellileiloes.com.br"
# Chave anon pública (mesma servida no bundle JS do site a qualquer visitante).
# Pode rotacionar em deploys da Picelli — override via variável de ambiente.
API_KEY = os.environ.get(
    "CIRCUITODELEILOES_API_KEY",
    "sb_publishable_Ekokc-7yTyPVUHWzAqQkGw_M6l6jAnj",
)
CATEGORIA_VEICULOS_ANTIGOS = "de136bb4-6b19-456d-abce-64dc5173e91e"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF_SEGUNDOS = 2.0
LIMITE_LOTES = 200

# Marcas com nome composto — necessárias para split marca/modelo em títulos
# sem barra separadora (ex.: "MERCEDES BENZ 280 SE").
_MARCAS_COMPOSTAS = (
    "MERCEDES BENZ",
    "ALFA ROMEO",
    "LAND ROVER",
    "ASTON MARTIN",
    "ROLLS ROYCE",
)

# Abreviações DETRAN comuns nos títulos → marca canônica da consulta.
_ALIASES_MARCA = {
    "VOLKSWAGEN": ("VW",),
    "CHEVROLET": ("GM",),
    "MERCEDES BENZ": ("MB", "MBENZ"),
}

# Prefixos DETRAN de importação que não são marca.
_PREFIXOS_IMPORTACAO = {"IMP", "I"}


# ────────────────────────────────────────────────
# Interface pública
# ────────────────────────────────────────────────

def buscar(marca: str, modelo: str, paginas: int = 1) -> list[Anuncio]:
    """
    Busca preços realizados (lotes vendidos) por marca e modelo.

    Os filtros de categoria (Veículos Antigos e Especiais), status
    ("vendido") e lance > 0 são aplicados server-side; o matching de
    marca/modelo é client-side sobre o título do lote.

    Args:
        marca:   Nome da marca (ex.: "VOLKSWAGEN").
        modelo:  Nome do modelo (ex.: "FUSCA").
        paginas: Ignorado — mantido para compatibilidade de assinatura
                 com os demais conectores (a API retorna tudo em 1 request).

    Returns:
        Lista de Anuncio com preço realizado. Vazia em caso de falha.
    """
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()

    params = {
        "select": "id,slug,title,status,highest_bid_value,bid_count,updated_at",
        "category_id": f"eq.{CATEGORIA_VEICULOS_ANTIGOS}",
        "status": "eq.vendido",
        "highest_bid_value": "gt.0",
        "order": "updated_at.desc",
        "limit": str(LIMITE_LOTES),
    }
    lotes = _requisitar(f"{API_BASE}/public_lots", params)
    if lotes is None:
        logger.warning("[circuitodeleiloes] falha na coleta — sinal indisponível.")
        return []

    anuncios = parsear_lotes(lotes, marca, modelo, data_coleta)

    latencia = time.monotonic() - inicio
    logger.info(
        "[circuitodeleiloes] busca concluída: %d venda(s) de %d lote(s), %.1fs",
        len(anuncios), len(lotes), latencia,
    )
    return anuncios


# ────────────────────────────────────────────────
# Parsers puros — testáveis sem I/O
# ────────────────────────────────────────────────

def parsear_lotes(
    lotes: list[dict], marca: str, modelo: str, data_coleta: str = "2000-01-01"
) -> list[Anuncio]:
    """
    Converte lotes da view public_lots em Anuncio de preço realizado.

    Regras:
    - Somente status "vendido" com highest_bid_value > 0.
    - Título precisa conter marca (ou alias DETRAN: VW, GM, MB…) E modelo.
    - Deduplicação por id do lote.
    - marca/modelo canônicos vêm da consulta; ano vem do título.
    """
    marca_norm = _normalizar(marca)
    modelo_norm = _normalizar(modelo)
    termos_marca = [marca_norm, *(
        alias for canonica, aliases in _ALIASES_MARCA.items()
        if canonica == marca_norm for alias in aliases
    )]

    anuncios: list[Anuncio] = []
    vistos: set[str] = set()

    for lote in lotes:
        if lote.get("status") != "vendido":
            continue
        preco = lote.get("highest_bid_value")
        if not preco or preco <= 0:
            continue
        lote_id = str(lote.get("id", ""))
        if lote_id in vistos:
            continue

        titulo = (lote.get("title") or "").strip()
        titulo_norm = _normalizar(titulo)
        if modelo_norm and modelo_norm not in titulo_norm:
            continue
        if marca_norm and not any(t in titulo_norm for t in termos_marca):
            continue

        vistos.add(lote_id)
        _, _, ano = parsear_titulo(titulo)
        slug = lote.get("slug") or lote_id

        anuncios.append(Anuncio(
            titulo=titulo,
            preco=float(preco),
            marca=marca.upper(),
            modelo=modelo.upper(),
            ano=ano,
            versao=None,
            url=f"{SITE_BASE}/lote/{slug}",
            fonte=FONTE,
            data_coleta=data_coleta,
        ))

    return anuncios


def parsear_titulo(titulo: str) -> tuple[str, str, Optional[int]]:
    """
    Parse do título no padrão DETRAN: "MARCA/MODELO - ANOFAB/ANOMOD".

    Exemplos reais:
        "FORD/GALAXIE 500 - 1968/1968"          → ("FORD", "GALAXIE 500", 1968)
        "IMP/MERCEDES BENZ 190 E - 1983/1983"   → ("MERCEDES BENZ", "190 E", 1983)
        "GM/GM/OPALA COMODORO - 1980/1980"      → ("GM", "OPALA COMODORO", 1980)
        "AUDI S6 2.2 TB - 1995/1995"            → ("AUDI", "S6 2.2 TB", 1995)

    Regras:
    - Prefixos de importação DETRAN ("IMP", "I") são descartados.
    - Segmentos consecutivos duplicados são colapsados.
    - Conteúdo entre colchetes é removido antes do split (pode conter "/").
    - Sem barra: split por marca composta conhecida ou primeira palavra.
    """
    texto = titulo.strip()

    # Ano de fabricação: sufixo " - ANOFAB/ANOMOD" (fallback: primeiro ano avulso)
    ano: Optional[int] = None
    m = re.search(r"-?\s*\b((?:18|19|20)\d{2})\s*/\s*(?:18|19|20)\d{2}\s*$", texto)
    if m:
        ano = int(m.group(1))
        texto = texto[: m.start()].strip()
    else:
        m = re.search(r"\b((?:18|19|20)\d{2})\b", texto)
        if m:
            ano = int(m.group(1))

    # Colchetes podem conter "/" (ex.: "[MON/PROTOTIPO]") — remover antes do split
    texto = re.sub(r"\[[^\]]*\]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip(" -")

    segmentos = [s.strip() for s in texto.split("/") if s.strip()]
    while segmentos and segmentos[0].upper() in _PREFIXOS_IMPORTACAO:
        segmentos = segmentos[1:]
    # Colapsar duplicatas consecutivas (ex.: "GM/GM/OPALA")
    deduplicados: list[str] = []
    for seg in segmentos:
        if not deduplicados or deduplicados[-1].upper() != seg.upper():
            deduplicados.append(seg)

    if not deduplicados:
        return "", "", ano

    if len(deduplicados) >= 2:
        marca = deduplicados[0]
        modelo = " ".join(deduplicados[1:])
    else:
        unico = deduplicados[0]
        composta = next(
            (mc for mc in _MARCAS_COMPOSTAS if unico.upper().startswith(mc + " ") or unico.upper() == mc),
            None,
        )
        if composta:
            marca = unico[: len(composta)]
            modelo = unico[len(composta):]
        else:
            partes = unico.split(" ", 1)
            marca = partes[0]
            modelo = partes[1] if len(partes) > 1 else ""

    marca = re.sub(r"\s+", " ", marca).strip().upper()
    modelo = re.sub(r"\s+", " ", modelo).strip().upper()
    return marca, modelo, ano


# ────────────────────────────────────────────────
# Helpers internos
# ────────────────────────────────────────────────

def _normalizar(texto: str) -> str:
    """normalizar_texto + hífen→espaço (MERCEDES-BENZ casa com MERCEDES BENZ)."""
    resultado = normalizar_texto(texto).replace("-", " ")
    return re.sub(r"\s+", " ", resultado).strip()


def _requisitar(url: str, params: dict) -> Optional[list[dict]]:
    """GET com retry contra a API Supabase. Retorna lista de lotes ou None."""
    headers = {
        "apikey": API_KEY,
        "Authorization": f"Bearer {API_KEY}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url, params=params, headers=headers, timeout=TIMEOUT, verify=False
            )
            if resp.status_code in (401, 403):
                # Chave anon rotacionada em deploy da Picelli — erro claro no log
                logger.error(
                    "[circuitodeleiloes] autenticação recusada (HTTP %d) — "
                    "a chave pública pode ter rotacionado. Atualize "
                    "CIRCUITODELEILOES_API_KEY.", resp.status_code,
                )
                return None
            resp.raise_for_status()
            dados = resp.json()
            if isinstance(dados, list):
                return dados
            logger.warning("[circuitodeleiloes] resposta inesperada: %s", type(dados))
            return None
        except (requests.RequestException, ValueError) as exc:
            logger.warning(
                "[circuitodeleiloes] tentativa %d/%d falhou: %s",
                tentativa, MAX_RETRIES, exc,
            )
            if tentativa < MAX_RETRIES:
                time.sleep(BACKOFF_SEGUNDOS)
    return None
