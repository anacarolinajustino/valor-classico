"""
Conector Estação Raridades.
Site: https://estacaoraridades.com.br
Listing: /anuncios  — página única com ~40 veículos.

Estrutura do card:
  <div class="listing-card">
    <a href="anuncio/[brand]-[model]-[code]">    ← URL relativa
      <img alt="[BRAND MODEL]">
      <h3>[TITULO]</h3>
      <span class="price">R$ 35.900</span>
    </a>
  </div>

URL relativa é resolvida para https://estacaoraridades.com.br/anuncio/...
O slug da URL traz a marca no primeiro segmento (ex: "volkswagen" → "VOLKSWAGEN").
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

    Localiza cards (div.listing-card ou divs contendo <a href="anuncio/...">),
    extrai título do <h3>, preço do <span class="price"> ou padrão R$,
    e resolve URLs relativas.

    A marca é extraída do primeiro segmento do slug da URL quando ausente no título.
    """
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    # Seleciona cards com link "anuncio/..."
    card_links = soup.find_all("a", href=re.compile(r"anuncio/"))

    for link in card_links:
        href = link.get("href", "")
        if not href:
            continue
        # Resolve URL relativa
        if href.startswith("http"):
            url = href
        elif href.startswith("/"):
            url = BASE_URL + href
        else:
            url = f"{BASE_URL}/{href}"

        if url in seen:
            continue

        # Título: de <h3> dentro do link; fallback para <img alt>
        h3 = link.find("h3") or link.find("h2")
        titulo_parcial = h3.get_text(strip=True) if h3 else ""
        if not titulo_parcial:
            img = link.find("img")
            titulo_parcial = img.get("alt", "") if img else ""

        if not titulo_parcial:
            continue

        # Extrai marca do slug da URL: anuncio/[brand]-[model]-[code]
        slug = href.rstrip("/").split("/")[-1]
        slug_parts = slug.split("-")
        brand_from_slug = slug_parts[0].upper() if slug_parts else ""

        # Se o título já começa com a marca, usa diretamente; senão, prepend
        if brand_from_slug and not titulo_parcial.upper().startswith(brand_from_slug):
            titulo = f"{brand_from_slug} {titulo_parcial}"
        else:
            titulo = titulo_parcial

        # Preço: <span class="price"> ou padrão R$ dentro do link ou card pai
        preco = None
        price_span = link.find("span", class_=re.compile(r"price", re.I))
        if price_span:
            preco = normalizar_preco(price_span.get_text(strip=True))
        if not preco or preco <= 0:
            m = re.search(r"R\$\s*[\d.,]+", link.get_text(separator=" ", strip=True))
            if m:
                preco = normalizar_preco(m.group(0))
        if not preco or preco <= 0:
            # Tenta no card pai
            card = link.parent
            if card:
                m = re.search(r"R\$\s*[\d.,]+", card.get_text(separator=" ", strip=True))
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
