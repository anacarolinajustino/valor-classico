"""
Conector Reginaldo de Campinas.
Site: https://reginaldodecampinas.com.br
Motor: WooCommerce

Particularidade: preços NÃO aparecem na listagem — estão apenas nas páginas
de detalhe de cada produto. Estratégia em dois passos:
  1. Coletar URLs dos itens DISPONÍVEL na listagem.
  2. Para cada URL, buscar o preço na página de detalhe.

Estrutura da listagem (WooCommerce li.product):
  <li class="product">
    <a href="/produto/[slug]/">
      <span>DISPONÍVEL | VENDIDO | RESERVADO</span>
      <img ...>
      <h3>[título com ano e km]</h3>
    </a>
  </li>

Página de detalhe (tema customizado):
  <h2>R$ 98.000,00</h2>
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

FONTE = "reginaldodecampinas"
BASE_URL = "https://reginaldodecampinas.com.br"
LISTING_URL = f"{BASE_URL}/categoria-produto/veiculos-venda/"
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def coletar_completo(max_paginas: int = 50) -> tuple[list[Anuncio], dict]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0
    erros_detalhe = 0

    for pg in range(1, max_paginas + 1):
        url = LISTING_URL if pg == 1 else f"{LISTING_URL}page/{pg}/"
        logger.info("[reginaldodecampinas] listagem página %d", pg)
        html = _requisitar(sessao, url)
        if html is None:
            erros += 1
            break

        candidatos = _parsear_listagem_urls(html)
        if not candidatos:
            break

        paginas_ok += 1
        for prod_url, titulo in candidatos:
            if prod_url in seen:
                continue
            seen.add(prod_url)

            time.sleep(RATE_LIMIT)
            detalhe_html = _requisitar(sessao, prod_url)
            if detalhe_html is None:
                erros_detalhe += 1
                continue

            preco = _extrair_preco_detalhe(detalhe_html)
            if not preco or preco <= 0:
                continue

            marca, modelo, ano = inferir_marca_modelo_ano(titulo)
            if not modelo:
                continue

            anuncios.append(Anuncio(
                titulo=titulo, preco=preco, marca=marca, modelo=modelo,
                ano=ano, versao=None, url=prod_url, fonte=FONTE,
                data_coleta=data_coleta,
            ))

        if not _tem_proxima_pagina(html):
            break

        time.sleep(RATE_LIMIT)

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_ok,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "erros_detalhe": erros_detalhe,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[reginaldodecampinas] coleta completa: %s", metricas)
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

        for prod_url, titulo in _parsear_listagem_urls(html):
            if prod_url in seen:
                continue
            t = normalizar_texto(titulo)
            if modelo_norm and modelo_norm not in t:
                continue
            if marca_norm and marca_norm not in t:
                continue

            seen.add(prod_url)
            time.sleep(RATE_LIMIT)
            detalhe_html = _requisitar(sessao, prod_url)
            if detalhe_html is None:
                continue

            preco = _extrair_preco_detalhe(detalhe_html)
            if not preco or preco <= 0:
                continue

            m_inf, mo_inf, ano = inferir_marca_modelo_ano(titulo)
            if not mo_inf:
                continue
            anuncios.append(Anuncio(
                titulo=titulo, preco=preco, marca=m_inf, modelo=mo_inf,
                ano=ano, versao=None, url=prod_url, fonte=FONTE,
                data_coleta=data_coleta,
            ))

        if not _tem_proxima_pagina(html):
            break
        time.sleep(RATE_LIMIT)

    logger.info("[reginaldodecampinas] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """Compatibilidade: retorna itens sem preço (preço requer detalhe individual)."""
    anuncios = []
    for url, titulo in _parsear_listagem_urls(html):
        marca, modelo, ano = inferir_marca_modelo_ano(titulo)
        if not modelo:
            continue
        anuncios.append(Anuncio(
            titulo=titulo, preco=None, marca=marca, modelo=modelo,
            ano=ano, versao=None, url=url, fonte=FONTE, data_coleta=data_coleta,
        ))
    return anuncios


# ── Helpers internos ──────────────────────────────────────────────────────────

def _parsear_listagem_urls(html: str) -> list[tuple[str, str]]:
    """
    Retorna [(url, titulo)] somente de produtos DISPONÍVEL.
    Ignora VENDIDO, RESERVADO, EM BREVE, etc.
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[tuple[str, str]] = []

    for li in soup.find_all("li", class_="product"):
        link = li.find("a", href=True)
        if not link:
            continue
        url = link.get("href", "")
        if not url or "/produto/" not in url:
            continue

        badge = link.find("span")
        status = badge.get_text(strip=True).upper() if badge else ""
        if status and "DISPONÍVEL" not in status:
            continue

        h = li.find(["h3", "h2"]) or link.find(["h3", "h2"])
        titulo = h.get_text(strip=True) if h else ""
        if not titulo:
            continue

        items.append((url, titulo))

    return items


def _extrair_preco_detalhe(html: str) -> Optional[float]:
    """
    Extrai preço de página de detalhe WooCommerce com tema customizado.
    O tema usa <h2>R$ 98.000,00</h2> em vez do padrão WooCommerce.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["h2", "h3", "p"]):
        t = tag.get_text(strip=True)
        if "R$" in t and re.search(r"\d", t):
            preco = normalizar_preco(t)
            if preco and preco > 0:
                return preco
    price_span = soup.find("span", class_="woocommerce-Price-amount")
    if price_span:
        return normalizar_preco(price_span.get_text(strip=True))
    return None


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
            logger.warning("[reginaldodecampinas] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
