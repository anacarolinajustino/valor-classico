"""
Base compartilhada para conectores WordPress/WooCommerce.

Todos os sites WooCommerce do projeto seguem o mesmo padrão HTML:
  - li.product                          → container do anúncio
  - h2.woocommerce-loop-product__title  → título
  - span.woocommerce-Price-amount       → preço
  - a.woocommerce-LoopProduct-link      → URL do anúncio
  - a.next (paginação)                  → próxima página
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

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.0


def criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return s


def requisitar(sessao: requests.Session, url: str) -> Optional[str]:
    for i in range(1, MAX_RETRIES + 1):
        try:
            r = sessao.get(url, timeout=TIMEOUT, verify=False)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except requests.RequestException as exc:
            logger.warning("tentativa %d/%d falhou %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None


def parsear_produtos(html: str, fonte: str, data_coleta: str) -> list[Anuncio]:
    """Extrai anúncios de uma página de listagem WooCommerce."""
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []

    for produto in soup.find_all("li", class_="product"):
        titulo_tag = (
            produto.find("h2", class_=re.compile(r"woocommerce-loop-product__title", re.I))
            or produto.find("h2")
            or produto.find("h3")
        )
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else ""
        if not titulo:
            continue

        preco_tag = produto.find("span", class_="woocommerce-Price-amount")
        preco = normalizar_preco(preco_tag.get_text(strip=True)) if preco_tag else None
        if not preco or preco <= 0:
            continue

        link = (
            produto.find("a", class_=re.compile(r"woocommerce-LoopProduct-link", re.I))
            or produto.find("a", href=True)
        )
        url_anuncio = link["href"] if link and link.get("href") else ""

        marca, modelo, ano = inferir_marca_modelo_ano(titulo)
        if not modelo:
            continue

        anuncios.append(Anuncio(
            titulo=titulo, preco=preco, marca=marca, modelo=modelo,
            ano=ano, versao=None, url=url_anuncio, fonte=fonte,
            data_coleta=data_coleta,
        ))
    return anuncios


def tem_proxima_pagina(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    return bool(
        soup.find("a", class_=re.compile(r"\bnext\b", re.I))
        or soup.find("a", rel="next")
    )


def buscar(
    base_url: str,
    listing_path: str,
    fonte: str,
    marca: str,
    modelo: str,
    paginas: int = 2,
) -> list[Anuncio]:
    """Busca anúncios por marca+modelo usando WordPress search (?s=)."""
    import urllib.parse

    sessao = criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []

    for pagina in range(1, paginas + 1):
        termo = urllib.parse.quote_plus(modelo.lower())
        url = f"{base_url}/?s={termo}" if pagina == 1 else f"{base_url}/?s={termo}&paged={pagina}"
        logger.info("[%s] busca página %d — %s", fonte, pagina, url)

        html = requisitar(sessao, url)
        if html is None:
            break

        itens = parsear_produtos(html, fonte, data_coleta)

        if marca_norm:
            itens = [
                a for a in itens
                if not a.marca
                or normalizar_texto(a.marca) == marca_norm
                or marca_norm in normalizar_texto(a.titulo)
            ]
        if modelo_norm:
            itens = [
                a for a in itens
                if not a.modelo
                or modelo_norm in normalizar_texto(a.modelo)
                or normalizar_texto(a.modelo) in modelo_norm
                or modelo_norm in normalizar_texto(a.titulo)
            ]
        anuncios.extend(itens)

        if not tem_proxima_pagina(html):
            break
        if pagina < paginas:
            time.sleep(RATE_LIMIT)

    logger.info("[%s] busca: %d anúncio(s)", fonte, len(anuncios))
    return anuncios


def coletar_completo(
    base_url: str,
    listing_path: str,
    fonte: str,
    max_paginas: int = 100,
) -> tuple[list[Anuncio], dict]:
    """Coleta TODOS os anúncios do site (ingestão batch)."""
    sessao = criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen_urls: set[str] = set()
    paginas_lidas = 0
    erros = 0

    for pagina in range(1, max_paginas + 1):
        url = (
            f"{base_url}{listing_path}"
            if pagina == 1
            else f"{base_url}{listing_path}page/{pagina}/"
        )
        logger.info("[%s] listagem página %d", fonte, pagina)
        html = requisitar(sessao, url)
        if html is None:
            erros += 1
            break

        paginas_lidas += 1
        for a in parsear_produtos(html, fonte, data_coleta):
            if a.url not in seen_urls:
                seen_urls.add(a.url)
                anuncios.append(a)

        if not tem_proxima_pagina(html):
            break
        time.sleep(RATE_LIMIT)

    metricas = {
        "fonte": fonte,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_lidas,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[%s] coleta completa: %s", fonte, metricas)
    return anuncios, metricas
