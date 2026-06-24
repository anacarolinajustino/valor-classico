"""
Conector CIA 66 Motorsports.
Site: https://www.cia66motorsports.com.br
Listing: /index/categoria/veiculos-a-venda/

Estrutura do card (PHP customizado):
  <a href="/produto/veiculos-a-venda/[marca]/[modelo-ano]/[id]/">
    <h3>Buggy BRM M10 2005</h3>
    <div class="price">R$ R$ 79.000,00</div>
    <div>[status: Disponível / Vendido / Com o proprietário]</div>
  </a>

Preço pode aparecer duplicado como "R$ R$ valor" — normalizar_preco trata
pois descarta tudo que não seja dígito, vírgula ou ponto.

Paginação: ?pagina=N  (página 1 não usa parâmetro).
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

FONTE = "cia66motorsports"
BASE_URL = "https://www.cia66motorsports.com.br"
LISTING_URL = f"{BASE_URL}/index/categoria/veiculos-a-venda/"
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_LINK_PAT = re.compile(r"/produto/veiculos-a-venda/")


def coletar_completo(max_paginas: int = 50) -> tuple[list[Anuncio], dict]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0

    for pg in range(1, max_paginas + 1):
        url = LISTING_URL if pg == 1 else f"{LISTING_URL}?pagina={pg}"
        logger.info("[cia66motorsports] página %d — %s", pg, url)
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
        time.sleep(RATE_LIMIT)

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_ok,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[cia66motorsports] coleta completa: %s", metricas)
    return anuncios, metricas


def buscar(marca: str, modelo: str, paginas: int = 3) -> list[Anuncio]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for pg in range(1, paginas + 1):
        url = LISTING_URL if pg == 1 else f"{LISTING_URL}?pagina={pg}"
        html = _requisitar(sessao, url)
        if html is None:
            break
        items = parsear_listagem_html(html, data_coleta)
        if not items:
            break
        for a in items:
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
        time.sleep(RATE_LIMIT)

    logger.info("[cia66motorsports] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """
    Extrai anúncios da listagem CIA 66 Motorsports.

    Localiza links /produto/veiculos-a-venda/, extrai h3 como título e
    busca padrão R$ no texto do card. Inclui carros vendidos (preços
    históricos úteis para referência de mercado).
    """
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=_LINK_PAT):
        href = link.get("href", "")
        url = href if href.startswith("http") else BASE_URL + href
        if url in seen:
            continue

        # Título: h3 dentro do link ou do container pai
        titulo = ""
        h3 = link.find("h3") or link.find("h2")
        if h3:
            titulo = h3.get_text(strip=True)
        if not titulo:
            node = link.parent
            for _ in range(4):
                if node is None:
                    break
                h = node.find(["h2", "h3"])
                if h:
                    titulo = h.get_text(strip=True)
                    break
                node = node.parent

        if not titulo or len(titulo) < 4:
            continue

        # Preço: padrão R$ no texto do card
        card_text = link.get_text(separator=" ", strip=True)
        preco = None
        m = re.search(r"R\$\s*(?:R\$\s*)?([\d.,]+)", card_text)
        if m:
            preco = normalizar_preco("R$ " + m.group(1))
        if not preco or preco <= 0:
            # Fallback: qualquer R$ no container pai
            node = link.parent
            for _ in range(4):
                if node is None:
                    break
                inner = {a.get("href") for a in node.find_all("a", href=_LINK_PAT)}
                if len(inner) <= 2:
                    m2 = re.search(r"R\$\s*[\d.,]+", node.get_text(separator=" ", strip=True))
                    if m2:
                        preco = normalizar_preco(m2.group(0))
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
            logger.warning("[cia66motorsports] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
