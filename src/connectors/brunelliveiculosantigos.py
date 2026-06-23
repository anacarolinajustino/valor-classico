"""
Conector Brunelli Veículos Antigos.
Site: https://brunelliveiculosantigos.com.br
Motor: Custom (slug-based URLs)
Estratégia: requests + BeautifulSoup
Estrutura: listagem em /veiculos/, slugs /veiculos/{marca-modelo-ano-cor}/
           preço só na página de detalhe.
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

FONTE = "brunelliveiculosantigos"
BASE_URL = "https://brunelliveiculosantigos.com.br"
LISTING_PATH = "/veiculos"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.5
DETAIL_RATE_LIMIT = 0.8  # entre detalhe e detalhe


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for pg in range(1, paginas + 1):
        url = f"{BASE_URL}{LISTING_PATH}?page={pg}"
        html = _requisitar(sessao, url)
        if html is None:
            break

        for slug_url, titulo_slug in _extrair_slugs(html):
            titulo_norm = normalizar_texto(titulo_slug)
            if modelo_norm and modelo_norm not in titulo_norm:
                continue
            if marca_norm and marca_norm not in titulo_norm:
                continue
            if slug_url in seen:
                continue
            seen.add(slug_url)

            a = _buscar_detalhe(sessao, slug_url, titulo_slug, data_coleta)
            if a:
                anuncios.append(a)
            time.sleep(DETAIL_RATE_LIMIT)

        time.sleep(RATE_LIMIT)

    logger.info("[brunelliveiculosantigos] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0

    for pg in range(1, max_paginas + 1):
        url = f"{BASE_URL}{LISTING_PATH}?page={pg}"
        html = _requisitar(sessao, url)
        if html is None:
            erros += 1
            break

        slugs = _extrair_slugs(html)
        if not slugs:
            break

        paginas_ok += 1
        for slug_url, titulo_slug in slugs:
            if slug_url in seen:
                continue
            seen.add(slug_url)
            a = _buscar_detalhe(sessao, slug_url, titulo_slug, data_coleta)
            if a:
                anuncios.append(a)
            time.sleep(DETAIL_RATE_LIMIT)

        if not _tem_proxima(html):
            break
        time.sleep(RATE_LIMIT)

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_ok,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[brunelliveiculosantigos] coleta completa: %s", metricas)
    return anuncios, metricas


def _extrair_slugs(html: str) -> list[tuple[str, str]]:
    """Retorna lista de (url_absoluta, titulo_inferido_do_slug)."""
    soup = BeautifulSoup(html, "lxml")
    results: list[tuple[str, str]] = []
    pattern = re.compile(r"/veiculos/[a-z0-9\-]+/?$")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not pattern.search(href):
            continue
        url = href if href.startswith("http") else BASE_URL + href
        slug = href.rstrip("/").split("/")[-1]
        # Slug: marca-modelo-ano-cor → título legível
        titulo = slug.replace("-", " ").title()
        results.append((url, titulo))
    return results


def _buscar_detalhe(
    sessao: requests.Session,
    url: str,
    titulo_fallback: str,
    data_coleta: str,
) -> Optional[Anuncio]:
    html = _requisitar(sessao, url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")

    titulo_tag = soup.find(["h1", "h2"])
    titulo = titulo_tag.get_text(strip=True) if titulo_tag else titulo_fallback

    preco_tag = (
        soup.select_one(".preco")
        or soup.select_one(".price")
        or soup.select_one(".valor")
        or soup.find(string=re.compile(r"R\$\s*[\d.,]+"))
    )
    preco = None
    if preco_tag:
        txt = preco_tag if isinstance(preco_tag, str) else preco_tag.get_text(strip=True)
        preco = normalizar_preco(txt)
    if not preco or preco <= 0:
        return None

    marca, modelo, ano = inferir_marca_modelo_ano(titulo)
    if not modelo:
        return None

    return Anuncio(
        titulo=titulo, preco=preco, marca=marca, modelo=modelo,
        ano=ano, versao=None, url=url, fonte=FONTE,
        data_coleta=data_coleta,
    )


def _tem_proxima(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    return bool(soup.find("a", class_="next") or soup.find("a", rel="next"))


def _criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
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
            logger.warning("[brunelliveiculosantigos] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
