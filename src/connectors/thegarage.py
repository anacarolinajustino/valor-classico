"""
Conector The Garage.
Site: https://thegarage.com.br
Motor: WordPress custom (carros CPT)
Estratégia: requests + BeautifulSoup
  - Listagem: /carros/ → div.car-list > article (título no h2/h3/texto)
  - Preço: ausente na listagem; buscado na página de detalhe via <dd> com "R$"
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.pipeline.normalizer import inferir_marca_modelo_ano, normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "thegarage"
BASE_URL = "https://thegarage.com.br"
LISTING_PATH = "/carros/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.5
DETAIL_RATE_LIMIT = 0.8


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for pg in range(1, paginas + 1):
        url = f"{BASE_URL}{LISTING_PATH}page/{pg}/" if pg > 1 else f"{BASE_URL}{LISTING_PATH}"
        html = _requisitar(sessao, url)
        if html is None:
            break
        for a in _parsear_listagem(sessao, html, data_coleta):
            if a.url in seen:
                continue
            titulo_norm = normalizar_texto(a.titulo)
            if modelo_norm and modelo_norm not in titulo_norm:
                continue
            if marca_norm and a.marca and normalizar_texto(a.marca) != marca_norm and marca_norm not in titulo_norm:
                continue
            seen.add(a.url)
            anuncios.append(a)
        time.sleep(RATE_LIMIT)

    logger.info("[thegarage] busca: %d anúncio(s)", len(anuncios))
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
        url = f"{BASE_URL}{LISTING_PATH}page/{pg}/" if pg > 1 else f"{BASE_URL}{LISTING_PATH}"
        html = _requisitar(sessao, url)
        if html is None:
            erros += 1
            break

        items = _parsear_listagem(sessao, html, data_coleta)
        if not items:
            break

        paginas_ok += 1
        for a in items:
            if a.url not in seen:
                seen.add(a.url)
                anuncios.append(a)

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
    logger.info("[thegarage] coleta completa: %s", metricas)
    return anuncios, metricas


def _parsear_listagem(sessao: requests.Session, html: str, data_coleta: str) -> list[Anuncio]:
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []

    for art in soup.select("div.car-list > article"):
        titulo_tag = art.find(["h2", "h3", "h4"])
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else art.get_text(separator=" ", strip=True)[:80]
        if not titulo:
            continue

        link = art.find("a", href=True)
        url_anuncio = link["href"] if link else ""
        if not url_anuncio:
            continue
        if url_anuncio and not url_anuncio.startswith("http"):
            url_anuncio = BASE_URL + url_anuncio

        # Preço na página de detalhe
        preco = _buscar_preco_detalhe(sessao, url_anuncio)
        if not preco or preco <= 0:
            continue

        marca, modelo, ano = inferir_marca_modelo_ano(titulo)
        if not modelo:
            continue

        anuncios.append(Anuncio(
            titulo=titulo, preco=preco, marca=marca, modelo=modelo,
            ano=ano, versao=None, url=url_anuncio, fonte=FONTE,
            data_coleta=data_coleta,
        ))
        time.sleep(DETAIL_RATE_LIMIT)

    return anuncios


def _buscar_preco_detalhe(sessao: requests.Session, url: str) -> Optional[float]:
    html = _requisitar(sessao, url)
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    # Preço em <dd> que contém "R$"
    for dd in soup.find_all("dd"):
        txt = dd.get_text(strip=True)
        if "R$" in txt:
            return normalizar_preco(txt)
    # Fallback: qualquer tag com R$
    for tag in soup.find_all(string=lambda t: t and "R$" in t):
        return normalizar_preco(tag.strip())
    return None


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
            logger.warning("[thegarage] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
