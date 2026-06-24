"""
Conector Poa Parts.
Site: https://www.poaparts.com.br
Listing: /veiculos  — ~20 veículos, página única (plataforma Wix SSR).

Estrutura do card (Wix server-side rendered):
  <a href="https://www.poaparts.com.br/product-page/[slug]">
    <img src="..."/>
    CHEVROLET C10 SCOTTSDALE V8 DIESEL 1982
    <div>PreçoR$ 190.000,00</div>
  </a>

Título: texto livre no nó de texto direto do <a> (antes do <div> de preço).
Preço: div interno com texto "PreçoR$ X" — normalizar_preco descarta "Preço".
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup, NavigableString

from src.pipeline.normalizer import inferir_marca_modelo_ano, normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "poaparts"
BASE_URL = "https://www.poaparts.com.br"
LISTING_URL = f"{BASE_URL}/veiculos"
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_LINK_PAT = re.compile(r"/product-page/[^/]+")


def coletar_completo(max_paginas: int = 5) -> tuple[list[Anuncio], dict]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0

    # Wix não tem paginação clássica — tenta uma página extra por robustez
    for pg in range(1, max_paginas + 1):
        url = LISTING_URL if pg == 1 else f"{LISTING_URL}?page={pg}"
        logger.info("[poaparts] página %d — %s", pg, url)
        html = _requisitar(sessao, url)
        if html is None:
            erros += 1
            break

        items = parsear_listagem_html(html, data_coleta)
        if not items:
            break

        paginas_ok += 1
        novos = sum(1 for a in items if a.url not in seen)
        for a in items:
            if a.url not in seen:
                seen.add(a.url)
                anuncios.append(a)

        if novos == 0:
            break

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_ok,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[poaparts] coleta completa: %s", metricas)
    return anuncios, metricas


def buscar(marca: str, modelo: str, paginas: int = 1) -> list[Anuncio]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    html = _requisitar(sessao, LISTING_URL)
    if html is None:
        return []

    for a in parsear_listagem_html(html, data_coleta):
        if a.url in seen:
            continue
        t = normalizar_texto(a.titulo)
        if modelo_norm and modelo_norm not in t and (
            not a.modelo or modelo_norm not in normalizar_texto(a.modelo)
        ):
            continue
        if marca_norm and a.marca and (
            normalizar_texto(a.marca) != marca_norm and marca_norm not in t
        ):
            continue
        seen.add(a.url)
        anuncios.append(a)

    logger.info("[poaparts] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """
    Extrai anúncios da listagem Poa Parts (Wix SSR).

    Localiza links /product-page/[slug]. O título é o nó de texto direto
    do <a> (uppercase "MARCA MODELO ANO"). O preço está num <div> interno
    com texto "PreçoR$ X" — normalizar_preco descarta caracteres não numéricos.
    """
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=_LINK_PAT):
        href = link.get("href", "")
        url = href if href.startswith("http") else BASE_URL + href
        if url in seen:
            continue

        # Título: primeiro nó de texto direto com conteúdo substancial
        titulo = ""
        for node in link.children:
            if isinstance(node, NavigableString):
                t = node.strip()
                if t and len(t) > 4:
                    titulo = t
                    break

        # Fallback: texto do link excluindo div de preço
        if not titulo:
            price_div = link.find("div")
            if price_div:
                price_div.extract()
            titulo = link.get_text(strip=True)

        if not titulo or len(titulo) < 4:
            continue

        # Preço: div interno contendo "R$" ou "Preço"
        preco = None
        for div in link.find_all(["div", "span", "p"]):
            txt = div.get_text(strip=True)
            if "R$" in txt or "Preco" in txt or "Preço" in txt:
                preco = normalizar_preco(txt)
                if preco and preco > 0:
                    break

        if not preco or preco <= 0:
            # Fallback: R$ no texto do link
            m = re.search(r"R\$\s*[\d.,]+", link.get_text(separator=" ", strip=True))
            if m:
                preco = normalizar_preco(m.group(0))

        if not preco or preco <= 0:
            continue

        seen.add(url)
        marca, modelo, ano = inferir_marca_modelo_ano(titulo)
        if not modelo:
            continue

        anuncios.append(Anuncio(
            titulo=titulo, preco=preco, marca=marca, modelo=modelo,
            ano=ano, versao=None, url=url, fonte=FONTE, data_coleta=data_coleta,
        ))

    return anuncios


# ── Helpers internos ──────────────────────────────────────────────────────────

def _criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    })
    return s


def _requisitar(sessao: requests.Session, url: str) -> Optional[str]:
    for i in range(1, MAX_RETRIES + 1):
        try:
            r = sessao.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except requests.RequestException as exc:
            logger.warning("[poaparts] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
