"""
Conector Estação Raridades.
Site: https://estacaoraridades.com.br
Listing: /anuncios  — página única com ~41 veículos.

Estrutura do card (article.item):
  <div class="content-price">R$ 35.900</div>
  <div class="content-desc">
    <a href="anuncio/[brand]-[model]-[code]">Toyota . Paseo . 1995</a>
  </div>

Título no formato "Marca . Modelo . Ano"; URLs são relativas (sem barra inicial).
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

FONTE = "estacaoraridades"
BASE_URL = "https://estacaoraridades.com.br"
LISTING_URL = f"{BASE_URL}/anuncios"
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def coletar_completo(max_paginas: int = 5) -> tuple[list[Anuncio], dict]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0

    # Estação Raridades carrega tudo em uma página; tentamos /page/N/ por robustez.
    for pg in range(1, max_paginas + 1):
        url = LISTING_URL if pg == 1 else f"{LISTING_URL}?page={pg}"
        logger.info("[estacaoraridades] página %d — %s", pg, url)
        html = _requisitar(sessao, url)
        if html is None:
            erros += 1
            break

        items = parsear_listagem_html(html, data_coleta)
        if not items:
            break

        paginas_ok += 1
        novos = 0
        for a in items:
            if a.url not in seen:
                seen.add(a.url)
                anuncios.append(a)
                novos += 1

        # Sem paginação detectada: para após a primeira página
        if not _tem_proxima_pagina(html) or novos == 0:
            break

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_ok,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[estacaoraridades] coleta completa: %s", metricas)
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

    logger.info("[estacaoraridades] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """
    Extrai anúncios da listagem Estação Raridades.

    Itera por article.item; título em div.content-desc > a (formato "Marca . Modelo . Ano"),
    preço em div.content-price, URL no href do link.
    """
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for article in soup.find_all("article", class_="item"):
        # URL: primeiro link anuncio/ no card
        link = article.find("a", href=re.compile(r"anuncio/"))
        if not link:
            continue
        href = link.get("href", "")
        url = href if href.startswith("http") else f"{BASE_URL}/{href.lstrip('/')}"
        if url in seen:
            continue

        # Título: link dentro de content-desc ("Marca . Modelo . Ano")
        desc_div = article.find("div", class_="content-desc")
        title_link = desc_div.find("a") if desc_div else None
        titulo_raw = title_link.get_text(strip=True) if title_link else ""
        # Normaliza separador " . " → " "
        titulo = re.sub(r"\s*\.\s*", " ", titulo_raw).strip()
        if not titulo or len(titulo) < 4:
            continue

        # Preço: div.content-price
        price_div = article.find("div", class_="content-price")
        preco_raw = price_div.get_text(strip=True) if price_div else ""
        m = re.search(r"R\$\s*[\d.,]+", preco_raw)
        preco = normalizar_preco(m.group(0)) if m else None
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
        or soup.find("a", string=re.compile(r"próxima|next", re.I))
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
            logger.warning(
                "[estacaoraridades] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc
            )
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
