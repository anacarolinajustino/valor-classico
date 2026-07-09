"""
Conector Franz Veículos Antigos.
Site: https://franzveiculosantigos.com.br
Motor: WordPress custom (portfólio) — NÃO tem página de listagem/loja
(o antigo `/loja/` woocommerce não existe mais, 404).

Estratégia: o sitemap do WordPress (`wp-sitemap-posts-post-1.xml`) lista
todas as páginas de veículo (uma por post, ex. `/puma-dkw-1967/`). A maior
parte já foi vendida (título/h1 contém "Vendido"/"Vendida") — esses são
ignorados individualmente, não descartam a fonte inteira.

Compliance: robots.txt permite tudo exceto /wp-admin/. Requer headers de
navegador completos (Accept + Accept-Language) — o Mod_Security do host
retorna 406 para requests com header mínimo.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.pipeline.normalizer import inferir_marca_modelo_ano, normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "franzveiculosantigos"
BASE_URL = "https://franzveiculosantigos.com.br"
SITEMAP_URL = f"{BASE_URL}/wp-sitemap-posts-post-1.xml"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.0
_VENDIDO_RE = re.compile(r"\bvendid[oa]\b", re.IGNORECASE)
_PRECO_RE = re.compile(r"R\$\s*[\d.,]+")


def coletar_completo(max_paginas: int = 150) -> tuple[list[Anuncio], dict]:
    """
    Coleta os veículos disponíveis do Franz. Sem parâmetro real de paginação:
    `max_paginas` limita quantas páginas de veículo do sitemap são visitadas
    (permite smoke test rápido sem varrer as ~130 páginas inteiras).
    """
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()

    urls = _listar_urls_veiculos(sessao)[:max_paginas]
    anuncios: list[Anuncio] = []
    vendidos = 0
    erros = 0

    for url in urls:
        html = _requisitar(sessao, url)
        if html is None:
            erros += 1
            continue
        anuncio, vendido = _parsear_detalhe(html, url, data_coleta)
        if vendido:
            vendidos += 1
        elif anuncio:
            anuncios.append(anuncio)
        time.sleep(RATE_LIMIT)

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "urls_sitemap": len(urls),
        "anuncios_validos": len(anuncios),
        "vendidos_ignorados": vendidos,
        "erros_detalhe": erros,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[franzveiculosantigos] coleta completa: %s", metricas)
    return anuncios, metricas


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """Busca por marca/modelo varrendo até paginas*24 páginas de veículo do sitemap."""
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)

    urls = _listar_urls_veiculos(sessao)[: paginas * 24]
    anuncios: list[Anuncio] = []

    for url in urls:
        html = _requisitar(sessao, url)
        if html is None:
            continue
        anuncio, vendido = _parsear_detalhe(html, url, data_coleta)
        if vendido or not anuncio:
            time.sleep(RATE_LIMIT)
            continue
        titulo_norm = normalizar_texto(anuncio.titulo)
        if modelo_norm and modelo_norm not in titulo_norm:
            time.sleep(RATE_LIMIT)
            continue
        if (marca_norm and anuncio.marca
                and normalizar_texto(anuncio.marca) != marca_norm
                and marca_norm not in titulo_norm):
            time.sleep(RATE_LIMIT)
            continue
        anuncios.append(anuncio)
        time.sleep(RATE_LIMIT)

    logger.info("[franzveiculosantigos] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def _listar_urls_veiculos(sessao: requests.Session) -> list[str]:
    xml = _requisitar(sessao, SITEMAP_URL)
    if not xml:
        return []
    return re.findall(r"<loc>(.*?)</loc>", xml)


def _parsear_detalhe(html: str, url: str, data_coleta: str) -> tuple[Optional[Anuncio], bool]:
    """Retorna (anuncio ou None, vendido: bool)."""
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    titulo_bruto = h1.get_text(strip=True) if h1 else ""
    if not titulo_bruto:
        title_tag = soup.find("title")
        titulo_bruto = title_tag.get_text(strip=True) if title_tag else ""
        titulo_bruto = re.sub(r"\s*[–-]\s*Franz Ve.culos Antigos\s*$", "", titulo_bruto)
    if not titulo_bruto:
        return None, False

    if _VENDIDO_RE.search(titulo_bruto):
        return None, True

    preco_match = _PRECO_RE.search(titulo_bruto) or _PRECO_RE.search(soup.get_text(" ", strip=True))
    preco = normalizar_preco(preco_match.group(0)) if preco_match else None
    if not preco or preco <= 0:
        return None, False

    marca, modelo, ano = inferir_marca_modelo_ano(titulo_bruto)
    if not modelo:
        return None, False

    return Anuncio(
        titulo=titulo_bruto, preco=preco, marca=marca, modelo=modelo,
        ano=ano, versao=None, url=url, fonte=FONTE, data_coleta=data_coleta,
    ), False


def _criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    return s


def _requisitar(sessao: requests.Session, url: str) -> Optional[str]:
    for i in range(1, MAX_RETRIES + 1):
        try:
            r = sessao.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return r.text
        except requests.RequestException as exc:
            logger.warning("[franzveiculosantigos] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
