"""
Conector Classic Car Brasil.
Site: https://classiccarbr.com.br
Motor: Elementor (WordPress)
Listing: /veiculos/ — página única ou com paginação WordPress /page/N/.

Estrutura do card Elementor:
  div.card-wrapper (ou equivalente)
    a href="/automoveis/[slug]/"  → imagem
    h3 > a href="/automoveis/..."  → título
    p.price                        → preço
    a "Mais Detalhes"              → redundante
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

FONTE = "classiccarbr"
BASE_URL = "https://classiccarbr.com.br"
LISTING_URL = f"{BASE_URL}/veiculos/"
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

    for pg in range(1, max_paginas + 1):
        url = LISTING_URL if pg == 1 else f"{LISTING_URL}page/{pg}/"
        logger.info("[classiccarbr] página %d — %s", pg, url)
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
    logger.info("[classiccarbr] coleta completa: %s", metricas)
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

    logger.info("[classiccarbr] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """
    Extrai anúncios da listagem Elementor.

    Estratégia primária: localiza <p class="price"> → sobe até container com link
    /automoveis/ → extrai título do heading e URL do link.
    Estratégia de fallback: percorre links /automoveis/ diretamente.
    """
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    # ── Estratégia 1: âncora no elemento de preço ────────────────────────────
    for preco_tag in soup.find_all(
        lambda t: t.name in ("p", "span", "div")
        and re.search(r"price", " ".join(t.get("class") or []), re.I)
    ):
        preco = normalizar_preco(preco_tag.get_text(strip=True))
        if not preco or preco <= 0:
            continue

        card = preco_tag
        for _ in range(8):
            card = card.parent
            if card is None:
                break
            if card.find("a", href=re.compile(r"/automoveis/")):
                inner_urls = {
                    a.get("href") for a in card.find_all("a", href=re.compile(r"/automoveis/"))
                }
                if len(inner_urls) == 1:
                    break

        if card is None:
            continue

        vehicle_link = card.find("a", href=re.compile(r"/automoveis/"))
        if not vehicle_link:
            continue
        url = vehicle_link.get("href", "")
        if not url or url in seen:
            continue
        seen.add(url)

        titulo = _extrair_titulo(card, url)
        if not titulo:
            continue

        marca, modelo, ano = inferir_marca_modelo_ano(titulo)
        if not modelo:
            continue

        anuncios.append(Anuncio(
            titulo=titulo, preco=preco, marca=marca, modelo=modelo,
            ano=ano, versao=None, url=url, fonte=FONTE, data_coleta=data_coleta,
        ))

    # ── Estratégia 2: fallback por links /automoveis/ ───────────────────────
    if not anuncios:
        for link in soup.find_all("a", href=re.compile(r"/automoveis/[^/]+/")):
            url = link.get("href", "")
            if not url or url in seen:
                continue
            titulo = link.get_text(strip=True)
            if not titulo or len(titulo) < 5 or "mais detalhes" in titulo.lower():
                continue
            seen.add(url)

            node = link.parent
            preco = None
            for _ in range(10):
                if node is None:
                    break
                inner_urls = {
                    a.get("href") for a in node.find_all("a", href=re.compile(r"/automoveis/"))
                }
                m = re.search(r"R\$\s*[\d.,]+", node.get_text(separator=" ", strip=True))
                if m and len(inner_urls) <= 3:
                    preco = normalizar_preco(m.group(0))
                    if preco and preco > 0:
                        break
                node = node.parent

            if not preco or preco <= 0:
                continue
            marca, modelo, ano = inferir_marca_modelo_ano(titulo)
            if not modelo:
                continue
            anuncios.append(Anuncio(
                titulo=titulo, preco=preco, marca=marca, modelo=modelo,
                ano=ano, versao=None, url=url, fonte=FONTE, data_coleta=data_coleta,
            ))

    return anuncios


# ── Helpers internos ──────────────────────────────────────────────────────────

def _extrair_titulo(card, url: str) -> str:
    heading = card.find(["h2", "h3", "h4"])
    if heading:
        t = heading.get_text(strip=True)
        if t and len(t) > 4:
            return t
    for a in card.find_all("a", href=re.compile(r"/automoveis/")):
        t = a.get_text(strip=True)
        if t and len(t) > 4 and "mais detalhes" not in t.lower():
            return t
    return url.rstrip("/").split("/")[-1].replace("-", " ").title()


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
            logger.warning("[classiccarbr] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
