"""
Conector Carangos Legais.
Site: https://carangoslegais.com.br
Motor: WordPress

Listing: /classicos-a-venda/  (paginação WordPress: /page/N/)
Posts individuais: /antigos-a-venda/[slug]/

Estrutura do card (WordPress post loop):
  - Link: href="/antigos-a-venda/[slug]/"
  - Título: no texto do link ou em h2/h3 dentro do card
  - Preço: "R$ 25.000,00" em algum elemento do card
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

FONTE = "carangoslegais"
BASE_URL = "https://carangoslegais.com.br"
LISTING_URL = f"{BASE_URL}/classicos-a-venda/"
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_LINK_PAT = re.compile(r"/antigos-a-venda/[^/]+/")


def coletar_completo(max_paginas: int = 50) -> tuple[list[Anuncio], dict]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0

    for pg in range(1, max_paginas + 1):
        url = LISTING_URL if pg == 1 else f"{LISTING_URL}page/{pg}/"
        logger.info("[carangoslegais] página %d — %s", pg, url)
        html = _requisitar(sessao, url)
        if html is None:
            erros += 1
            break

        items = parsear_listagem_html(html, data_coleta)
        if not items:
            break

        paginas_ok += 1
        for a in items:
            if a.url not in seen:
                seen.add(a.url)
                anuncios.append(a)

        if not _tem_proxima_pagina(html):
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
    logger.info("[carangoslegais] coleta completa: %s", metricas)
    return anuncios, metricas


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for pg in range(1, paginas + 1):
        url = LISTING_URL if pg == 1 else f"{LISTING_URL}page/{pg}/"
        html = _requisitar(sessao, url)
        if html is None:
            break
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
        if not _tem_proxima_pagina(html):
            break
        time.sleep(RATE_LIMIT)

    logger.info("[carangoslegais] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """
    Extrai anúncios do Carangos Legais.

    Localiza links para /antigos-a-venda/[slug]/, sobe até encontrar um
    container isolado (somente esse veículo + preço R$), extrai título e preço.
    """
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=_LINK_PAT):
        url = link.get("href", "")
        if not url or url in seen:
            continue

        # Título: do próprio link ou do heading dentro do card
        titulo = link.get_text(strip=True)
        if not titulo or len(titulo) < 4:
            heading = link.find(["h2", "h3", "h4"])
            titulo = heading.get_text(strip=True) if heading else ""

        # Se o link não tem texto útil, sobe para o card e procura heading
        if not titulo or len(titulo) < 4:
            card = link.parent
            for _ in range(5):
                if card is None:
                    break
                heading = card.find(["h2", "h3", "h4"])
                if heading:
                    titulo = heading.get_text(strip=True)
                    if titulo and len(titulo) > 4:
                        break
                card = card.parent

        if not titulo or len(titulo) < 4:
            continue

        # Preço: sobe até um container isolado (apenas este veículo) com R$
        node = link.parent
        preco = None
        for _ in range(10):
            if node is None:
                break
            inner_links = {
                a.get("href") for a in node.find_all("a", href=_LINK_PAT)
            }
            txt = node.get_text(separator=" ", strip=True)
            m = re.search(r"R\$\s*[\d.,]+", txt)
            if m and len(inner_links) == 1:
                preco = normalizar_preco(m.group(0))
                if preco and preco > 0:
                    break
            elif m and len(inner_links) > 1 and inner_links == {url}:
                preco = normalizar_preco(m.group(0))
                if preco and preco > 0:
                    break
            node = node.parent

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

def _tem_proxima_pagina(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    return bool(
        soup.find("a", class_=re.compile(r"\bnext\b", re.I))
        or soup.find("a", rel="next")
    )


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
            logger.warning("[carangoslegais] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
