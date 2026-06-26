"""
Conector Mercado Livre — coleta anúncios de carros clássicos via API oficial.

Site: https://www.mercadolivre.com.br
Motor: REST API oficial (Mercado Livre Developers)
Estratégia: client_credentials OAuth → Search API (MLB1744 = Carros e Caminhonetes)
            com filtro VEHICLE_YEAR por faixas de ano (evita limite de 1000 resultados/query)

Compliance:
- API oficial: uso autorizado conforme Termos de Uso do Mercado Livre Developers.
- Rate limit: 0,25 s entre requisições (bem abaixo do limite da API com App Token).
- Credenciais: ML_CLIENT_ID e ML_CLIENT_SECRET via variáveis de ambiente.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Optional

import requests

from src.pipeline.normalizer import inferir_marca_modelo_ano, normalizar_texto
from src.pipeline.persistence import ANO_CORTE_CLASSICO
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "mercadolivre"
_API_BASE = "https://api.mercadolibre.com"
_SITE_ID = "MLB"
_CATEGORIA_CARROS = "MLB1744"  # Carros e Caminhonetes

_TIMEOUT = 15
_RATE_LIMIT = 0.25   # segundos entre requisições de paginação
_MAX_RETRIES = 2
_BACKOFF = 2.0
_LIMIT = 50          # itens por página (máximo da API)
_MAX_OFFSET = 950    # API limita a 1000 resultados por query (offset máx. = 950)

# Faixas de ano: décadas curtas para que cada query tenha bem menos de 1000 resultados.
_FAIXAS_ANO: list[tuple[int, int]] = [
    (1900, 1960),
    (1961, 1970),
    (1971, 1975),
    (1976, 1980),
    (1981, 1985),
    (1986, 1990),
    (1991, 1995),
    (1996, ANO_CORTE_CLASSICO),
]


def coletar_completo() -> tuple[list[Anuncio], dict]:
    """
    Coleta todos os anúncios de carros clássicos (ano <= ANO_CORTE_CLASSICO)
    dividindo a busca em faixas de ano para contornar o limite de 1000 resultados/query.
    """
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()
    sessao = _criar_sessao_autenticada()

    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    total_req = 0
    erros = 0

    for ano_ini, ano_fim in _FAIXAS_ANO:
        novos, req, err = _coletar_faixa(sessao, ano_ini, ano_fim, data_coleta, seen)
        anuncios.extend(novos)
        total_req += req
        erros += err
        logger.info(
            "[mercadolivre] faixa %d-%d: +%d anúncio(s) (total: %d)",
            ano_ini, ano_fim, len(novos), len(anuncios),
        )
        time.sleep(_RATE_LIMIT)

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "erros_detalhe": 0,
        "requisicoes": total_req,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[mercadolivre] coleta completa: %s", metricas)
    return anuncios, metricas


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """
    Busca anúncios no Mercado Livre por marca e modelo via API.

    Args:
        marca:   Nome da marca (ex.: "VOLKSWAGEN"). Usado para pós-filtragem.
        modelo:  Nome do modelo (ex.: "FUSCA"). Usado como termo de busca.
        paginas: Número máximo de páginas (50 itens cada) a buscar.

    Returns:
        Lista de Anuncio normalizados com ano <= ANO_CORTE_CLASSICO.
    """
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()
    sessao = _criar_sessao_autenticada()

    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for pagina in range(paginas):
        offset = pagina * _LIMIT
        params = {
            "category": _CATEGORIA_CARROS,
            "q": modelo.strip(),
            "VEHICLE_YEAR": f"1900-{ANO_CORTE_CLASSICO}",
            "limit": _LIMIT,
            "offset": offset,
        }
        dados = _requisitar(sessao, f"{_API_BASE}/sites/{_SITE_ID}/search", params)
        if not dados:
            break

        resultados = dados.get("results", [])
        if not resultados:
            break

        for item in resultados:
            a = _parsear_item(item, data_coleta)
            if a is None or a.url in seen:
                continue

            if marca_norm and a.marca:
                if normalizar_texto(a.marca) != marca_norm and marca_norm not in normalizar_texto(a.titulo):
                    continue

            if modelo_norm and a.modelo:
                a_modelo = normalizar_texto(a.modelo)
                if modelo_norm not in a_modelo and a_modelo not in modelo_norm and modelo_norm not in normalizar_texto(a.titulo):
                    continue

            seen.add(a.url)
            anuncios.append(a)

        total_disponivel = dados.get("paging", {}).get("total", 0)
        if offset + _LIMIT >= min(total_disponivel, _MAX_OFFSET + _LIMIT):
            break

        time.sleep(_RATE_LIMIT)

    logger.info(
        "[mercadolivre] busca '%s %s': %d anúncio(s) em %.1fs",
        marca, modelo, len(anuncios), time.monotonic() - inicio,
    )
    return anuncios


# ── Helpers internos ──────────────────────────────────────────────────────────

def _criar_sessao_autenticada() -> requests.Session:
    """Obtém App Token (client_credentials) e cria sessão autenticada."""
    client_id = os.environ.get("ML_CLIENT_ID", "")
    client_secret = os.environ.get("ML_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Variáveis de ambiente ML_CLIENT_ID e ML_CLIENT_SECRET não configuradas. "
            "Registre um app em developers.mercadolivre.com.br e adicione as credenciais."
        )
    token = _obter_token(client_id, client_secret)
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    return s


def _obter_token(client_id: str, client_secret: str) -> str:
    """Obtém App Token via client_credentials (sem login de usuário)."""
    resp = requests.post(
        f"{_API_BASE}/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _coletar_faixa(
    sessao: requests.Session,
    ano_ini: int,
    ano_fim: int,
    data_coleta: str,
    seen: set[str],
) -> tuple[list[Anuncio], int, int]:
    """
    Coleta anúncios de uma faixa de ano usando paginação por offset.
    Retorna (anuncios_novos, total_requisicoes, total_erros).
    """
    anuncios: list[Anuncio] = []
    total_req = 0
    erros = 0
    offset = 0

    while True:
        params = {
            "category": _CATEGORIA_CARROS,
            "VEHICLE_YEAR": f"{ano_ini}-{ano_fim}",
            "limit": _LIMIT,
            "offset": offset,
        }
        dados = _requisitar(sessao, f"{_API_BASE}/sites/{_SITE_ID}/search", params)
        total_req += 1

        if dados is None:
            erros += 1
            break

        resultados = dados.get("results", [])
        if not resultados:
            break

        for item in resultados:
            a = _parsear_item(item, data_coleta)
            if a is None or a.url in seen:
                continue
            seen.add(a.url)
            anuncios.append(a)

        total_disponivel = dados.get("paging", {}).get("total", 0)
        offset += _LIMIT

        if offset > min(total_disponivel, _MAX_OFFSET) or len(resultados) < _LIMIT:
            break

        time.sleep(_RATE_LIMIT)

    return anuncios, total_req, erros


def _parsear_item(item: dict, data_coleta: str) -> Optional[Anuncio]:
    """Converte um item da resposta da API em Anuncio. Retorna None se inválido."""
    preco = item.get("price")
    if not preco or preco <= 0:
        return None
    if item.get("currency_id") != "BRL":
        return None

    titulo = item.get("title", "").strip()
    if not titulo:
        return None

    url = item.get("permalink", "")
    if not url:
        return None

    attrs = {a["id"]: a.get("value_name", "") for a in item.get("attributes", [])}

    ano_str = attrs.get("VEHICLE_YEAR", "")
    ano = int(ano_str) if ano_str and ano_str.isdigit() else None
    if ano is None or not (1900 <= ano <= ANO_CORTE_CLASSICO):
        return None

    marca_api = attrs.get("BRAND", "")
    modelo_api = attrs.get("MODEL", "")

    # Preferir dados estruturados da API; inferir do título apenas como fallback.
    if marca_api and modelo_api:
        marca = normalizar_texto(marca_api)
        modelo = normalizar_texto(modelo_api)
    else:
        marca, modelo, _ = inferir_marca_modelo_ano(titulo)

    if not modelo:
        return None

    return Anuncio(
        titulo=titulo,
        preco=float(preco),
        marca=marca,
        modelo=modelo,
        ano=ano,
        versao=None,
        url=url,
        fonte=FONTE,
        data_coleta=data_coleta,
    )


def _requisitar(sessao: requests.Session, url: str, params: dict) -> Optional[dict]:
    """GET com retry. Retorna dict JSON ou None em caso de falha."""
    for tentativa in range(1, _MAX_RETRIES + 1):
        try:
            resp = sessao.get(url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning(
                "[mercadolivre] erro tentativa %d/%d — %s: %s",
                tentativa, _MAX_RETRIES, url, exc,
            )
            if tentativa < _MAX_RETRIES:
                time.sleep(_BACKOFF)
    return None
