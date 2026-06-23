"""
Conector ABC Classificados — carros clássicos.
Site: https://www.abcclassificados.com.br/carros/classicos
Motor: Custom (schema.org)
Estratégia: requests + BeautifulSoup, filtrando por décadas (pré-2000).

Não há paginação convencional — os anúncios são filtrados por décadas
via parâmetro ?decada=XX. Iteramos todas as décadas pré-2000.
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

FONTE = "abcclassificados"
BASE_URL = "https://www.abcclassificados.com.br/carros/classicos"
DECADAS = ["20", "30", "40", "50", "60", "70", "80", "90"]
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.0


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """Busca por marca+modelo varrendo todas as décadas."""
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for decada in DECADAS:
        url = f"{BASE_URL}?decada={decada}"
        html = _requisitar(sessao, url)
        if html is None:
            continue

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

    logger.info("[abcclassificados] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    """Coleta todos os anúncios varrendo todas as décadas."""
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0

    for decada in DECADAS:
        url = f"{BASE_URL}?decada={decada}"
        logger.info("[abcclassificados] década %s", decada)
        html = _requisitar(sessao, url)
        if html is None:
            erros += 1
            continue
        for a in _parsear(html, data_coleta):
            if a.url not in seen:
                seen.add(a.url)
                anuncios.append(a)
        time.sleep(RATE_LIMIT)

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": len(DECADAS) - erros,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[abcclassificados] coleta completa: %s", metricas)
    return anuncios, metricas


def _parsear(html: str, data_coleta: str) -> list[Anuncio]:
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []

    for item in soup.find_all("div", class_="generic-item"):
        # Título: combina marca + modelo do schema.org
        marca_tag = item.find(attrs={"itemprop": "brand"})
        marca_txt = marca_tag.get_text(strip=True) if marca_tag else ""

        nome_tag = item.find(attrs={"itemprop": "name"})
        if not nome_tag:
            nome_tag = item.find("a")
        titulo = nome_tag.get_text(strip=True) if nome_tag else marca_txt

        if not titulo:
            continue

        # Preço
        preco_tag = item.find(attrs={"itemprop": "lowPrice"})
        if not preco_tag:
            preco_tag = item.find(attrs={"itemprop": "price"})
        preco = normalizar_preco(preco_tag.get_text(strip=True)) if preco_tag else None
        if not preco or preco <= 0:
            continue

        # URL
        link = item.find("a", href=True)
        url_anuncio = link["href"] if link else ""
        if url_anuncio and not url_anuncio.startswith("http"):
            url_anuncio = "https://www.abcclassificados.com.br" + url_anuncio

        marca, modelo, ano = inferir_marca_modelo_ano(titulo)
        if not marca and marca_txt:
            marca = marca_txt.upper()
        if not modelo:
            continue

        anuncios.append(Anuncio(
            titulo=titulo, preco=preco, marca=marca, modelo=modelo,
            ano=ano, versao=None, url=url_anuncio, fonte=FONTE,
            data_coleta=data_coleta,
        ))
    return anuncios


def _criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return s


def _requisitar(sessao: requests.Session, url: str) -> Optional[str]:
    for i in range(1, MAX_RETRIES + 1):
        try:
            r = sessao.get(url, timeout=TIMEOUT, verify=False)
            r.raise_for_status()
            return r.text
        except requests.RequestException as exc:
            logger.warning("[abcclassificados] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
