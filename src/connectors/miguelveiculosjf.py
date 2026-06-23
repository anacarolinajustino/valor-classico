"""
Conector Miguel Veículos JF.
Site: https://www.miguelveiculosjf.com.br
Motor: Custom (REST-style URLs)
Estratégia: requests + BeautifulSoup
Seletores: div.veiculo-horizontal, URL /veiculo/carro/{marca}/{modelo}/{trim}/{ano}/{id}/
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

FONTE = "miguelveiculosjf"
BASE_URL = "https://www.miguelveiculosjf.com.br"
LISTING_PATH = "/veiculos/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.5

_URL_PATTERN = re.compile(
    r"/veiculo/carro/(?P<marca>[^/]+)/(?P<modelo>[^/]+)/[^/]+/(?P<ano>\d{4})(?:-\d{4})?/\d+/"
)


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for pg in range(1, paginas + 1):
        url = f"{BASE_URL}{LISTING_PATH}?pagina={pg}"
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

    logger.info("[miguelveiculosjf] busca: %d anúncio(s)", len(anuncios))
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
        url = f"{BASE_URL}{LISTING_PATH}?pagina={pg}"
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
    logger.info("[miguelveiculosjf] coleta completa: %s", metricas)
    return anuncios, metricas


def _parsear(html: str, data_coleta: str) -> list[Anuncio]:
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []

    for item in soup.find_all("div", class_="veiculo-horizontal"):
        link = item.find("a", href=True)
        url_anuncio = link["href"] if link else ""
        if url_anuncio and not url_anuncio.startswith("http"):
            url_anuncio = BASE_URL + url_anuncio

        # Extrair marca/modelo/ano direto da URL estruturada
        marca_url = modelo_url = ano_url = None
        if url_anuncio:
            m = _URL_PATTERN.search(url_anuncio)
            if m:
                marca_url = m.group("marca").replace("-", " ").upper()
                modelo_url = m.group("modelo").replace("-", " ").upper()
                ano_url = int(m.group("ano"))

        titulo_tag = item.find(["h2", "h3", "h4", "h5", "strong"])
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else (
            f"{marca_url} {modelo_url} {ano_url}" if marca_url else ""
        )
        if not titulo:
            continue

        preco_tag = (
            item.select_one("span.preco-atual")
            or item.select_one(".preco")
            or item.select_one(".valor")
            or item.find("b")
        )
        # Fallback: data-preco no elemento de leads
        if not preco_tag:
            leads = item.select_one("ul.leads[data-preco]")
            preco_raw = leads["data-preco"] if leads else None
        else:
            preco_raw = preco_tag.get_text(strip=True)
        preco = normalizar_preco(preco_raw) if preco_raw else None
        if not preco or preco <= 0:
            continue

        if marca_url and modelo_url:
            marca, modelo, ano = marca_url, modelo_url, ano_url
        else:
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
            logger.warning("[miguelveiculosjf] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
