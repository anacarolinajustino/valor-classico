"""
Conector L'Art de l'Automobile.
Site: https://lartdelautomobile.com.br
Motor: WordPress com cache pesado (LiteSpeed/Cloudflare)
Estratégia: Playwright (headless Chromium) para contornar cache agressivo.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Optional

from src.pipeline.normalizer import inferir_marca_modelo_ano, normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "lartdelautomobile"
BASE_URL = "https://lartdelautomobile.com.br"
LISTING_PATH = "/acervo"
RATE_LIMIT = 2.0
TIMEOUT = 30_000  # ms (Playwright)


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("[lartdelautomobile] Playwright não instalado.")
        return []

    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    data_coleta = date.today().isoformat()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))
        try:
            for pg in range(1, paginas + 1):
                url = f"{BASE_URL}{LISTING_PATH}/page/{pg}/" if pg > 1 else f"{BASE_URL}{LISTING_PATH}/"
                page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                html = page.content()
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
        finally:
            browser.close()

    logger.info("[lartdelautomobile] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("[lartdelautomobile] Playwright não instalado.")
        return [], {"fonte": FONTE, "erro": "playwright não instalado"}

    from bs4 import BeautifulSoup

    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))
        try:
            for pg in range(1, max_paginas + 1):
                url = f"{BASE_URL}{LISTING_PATH}/page/{pg}/" if pg > 1 else f"{BASE_URL}{LISTING_PATH}/"
                try:
                    page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                except Exception as exc:
                    logger.warning("[lartdelautomobile] página %d erro: %s", pg, exc)
                    erros += 1
                    break

                html = page.content()
                items = _parsear(html, data_coleta)
                if not items:
                    break

                paginas_ok += 1
                for a in items:
                    if a.url not in seen:
                        seen.add(a.url)
                        anuncios.append(a)

                soup = BeautifulSoup(html, "lxml")
                if not (soup.find("a", class_="next") or soup.find("a", rel="next")):
                    break
                time.sleep(RATE_LIMIT)
        finally:
            browser.close()

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_ok,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[lartdelautomobile] coleta completa: %s", metricas)
    return anuncios, metricas


def _parsear(html: str, data_coleta: str) -> list[Anuncio]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []

    # WordPress: produtos em li.product ou article
    items = (
        soup.select("li.product")
        or soup.select("article.post")
        or soup.select("div.product")
    )

    for item in items:
        titulo_tag = item.find(["h2", "h3", "h4"]) or item.find("a")
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else ""
        if not titulo:
            continue

        preco_tag = (
            item.select_one("span.woocommerce-Price-amount")
            or item.select_one(".price")
            or item.select_one(".preco")
            or item.find("b")
        )
        preco = normalizar_preco(preco_tag.get_text(strip=True)) if preco_tag else None
        if not preco or preco <= 0:
            continue

        link = item.find("a", href=True)
        url_anuncio = link["href"] if link else ""

        marca, modelo, ano = inferir_marca_modelo_ano(titulo)
        if not modelo:
            continue

        anuncios.append(Anuncio(
            titulo=titulo, preco=preco, marca=marca, modelo=modelo,
            ano=ano, versao=None, url=url_anuncio, fonte=FONTE,
            data_coleta=data_coleta,
        ))
    return anuncios
