"""
Conector Salvajoli.
Site: https://www.salvajoli.com.br
Motor: WordPress custom (blog-style listings)
Estratégia: requests + BeautifulSoup
Seletores: div.post-modern-title.titulo-carro > a (título), small (preço),
           paginação via ?page=N
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

FONTE = "salvajoli"
BASE_URL = "https://www.salvajoli.com.br"
LISTING_PATH = "/estoque"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.5


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for pg in range(1, paginas + 1):
        url = f"{BASE_URL}{LISTING_PATH}?page={pg}" if pg > 1 else f"{BASE_URL}{LISTING_PATH}"
        html = _requisitar(sessao, url)
        if html is None:
            break
        for a in _parsear(html, data_coleta):
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

    logger.info("[salvajoli] busca: %d anúncio(s)", len(anuncios))
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
        url = f"{BASE_URL}{LISTING_PATH}?page={pg}" if pg > 1 else f"{BASE_URL}{LISTING_PATH}"
        html = _requisitar(sessao, url)
        if html is None:
            erros += 1
            break

        items = _parsear(html, data_coleta)
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
    logger.info("[salvajoli] coleta completa: %s", metricas)
    return anuncios, metricas


def _parsear(html: str, data_coleta: str) -> list[Anuncio]:
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []

    for card in soup.find_all("div", class_=lambda c: c and "post-modern-header" in c):
        # Título
        titulo_tag = card.select_one("div.post-modern-title a") or card.select_one(".titulo-carro a") or card.find("a")
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else ""
        if not titulo:
            continue

        # Preço via <small> ou span com preço
        preco = None
        small = card.find("small")
        if small:
            preco = normalizar_preco(small.get_text(strip=True))
        if not preco:
            preco_tag = card.find(class_=lambda c: c and "preco" in c.lower() if c else False)
            if preco_tag:
                preco = normalizar_preco(preco_tag.get_text(strip=True))
        if not preco or preco <= 0:
            continue

        link = titulo_tag if titulo_tag and titulo_tag.name == "a" else card.find("a", href=True)
        url_anuncio = link["href"] if link and link.has_attr("href") else ""
        if url_anuncio and not url_anuncio.startswith("http"):
            url_anuncio = BASE_URL + url_anuncio

        marca, modelo, ano = inferir_marca_modelo_ano(titulo)
        if not modelo:
            continue

        anuncios.append(Anuncio(
            titulo=titulo, preco=preco, marca=marca, modelo=modelo,
            ano=ano, versao=None, url=url_anuncio, fonte=FONTE,
            data_coleta=data_coleta,
        ))
    return anuncios


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
            logger.warning("[salvajoli] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
