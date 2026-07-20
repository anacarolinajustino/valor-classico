"""
Conector Super Antigo — coleta anúncios de veículos clássicos.

Site: https://superantigo.com.br
Motor: Vite + React SPA — virou SPA puro sem SSR/API acessível via `requests`
(verificado 2026-07-09: a resposta é só o shell HTML vazio, sem dados;
antes funcionava via JSON ou HTML servidor). Requer Playwright para
renderizar antes de parsear.
  URL: /veiculos?showAllTypes=true&page=N&limit=24&sort=newest — na prática
  o param `page` não pagina mais (página 1 e 2 retornam os mesmos ~23 itens,
  abaixo do limit de 24: é o catálogo inteiro numa página só).

Compliance (verificado 2026-06-24):
- robots.txt: Allow: /veiculos/ ✅
- Rate limit: 1s entre páginas

Separação de responsabilidades:
- coletar_completo()      → I/O (Playwright), paginação completa
- buscar()                → I/O (Playwright), filtro por marca/modelo
- parsear_listagem_html() → função pura (BS4), usada nos testes de snapshot
"""
from __future__ import annotations

import logging
import re
import time
import urllib.parse
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from src.connectors._browser import criar_contexto
from src.pipeline.normalizer import normalizar_preco, normalizar_texto, separar_marca_modelo_versao_obs
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "superantigo"
BASE_URL = "https://www.superantigo.com.br"
LISTING_BASE = "https://superantigo.com.br"
LISTING_PATH = "/veiculos"
DEFAULT_LIMIT = 24
RATE_LIMIT = 1.0

_SLUG_PARA_MARCA: dict[str, str] = {
    "volkswagen": "VOLKSWAGEN",
    "ford": "FORD",
    "chevrolet": "CHEVROLET",
    "fiat": "FIAT",
    "toyota": "TOYOTA",
    "honda": "HONDA",
    "renault": "RENAULT",
    "peugeot": "PEUGEOT",
    "mercedes-benz": "MERCEDES-BENZ",
    "dodge": "DODGE",
    "jeep": "JEEP",
    "bmw": "BMW",
    "yamaha": "YAMAHA",
    "harley-davidson": "HARLEY-DAVIDSON",
}


# ── Interface pública ─────────────────────────────────────────────────────────

def coletar_completo(max_paginas: int = 200) -> tuple[list[Anuncio], dict]:
    """
    Coleta TODOS os anúncios do Super Antigo. Navega via Playwright (SPA sem
    SSR) por /veiculos?showAllTypes=true&page=N&limit=24&sort=newest — na
    prática só existe 1 página real hoje (ver módulo), mas o loop segue
    tentando `max_paginas` por segurança caso o catálogo cresça.
    """
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen_urls: set[str] = set()
    paginas_ok = 0
    erros = 0

    with criar_contexto() as ctx:
        page = ctx.new_page()
        for pagina in range(1, max_paginas + 1):
            url = _url_pagina(pagina)
            logger.info("[superantigo] página %d — %s", pagina, url)

            html = _navegar(page, url)
            if html is None:
                erros += 1
                break

            itens = parsear_listagem_html(html, data_coleta)
            if not itens:
                logger.info("[superantigo] página %d sem resultados — encerrando.", pagina)
                break

            paginas_ok += 1
            novos = 0
            for a in itens:
                if a.url not in seen_urls:
                    seen_urls.add(a.url)
                    anuncios.append(a)
                    novos += 1

            logger.info(
                "[superantigo] página %d: %d itens · %d novos (total: %d)",
                pagina, len(itens), novos, len(anuncios),
            )

            if novos == 0 or len(itens) < DEFAULT_LIMIT:
                logger.info("[superantigo] última página (%d).", pagina)
                break

            time.sleep(RATE_LIMIT)

    tempo_total = time.monotonic() - inicio
    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_ok,
        "urls_detalhe": len(seen_urls),
        "anuncios_validos": len(anuncios),
        "descartados_sem_preco_ou_modelo": 0,
        "erros_listagem": erros,
        "erros_detalhe": 0,
        "requisicoes": paginas_ok + erros,
        "latencia_p50_s": None,
        "latencia_p95_s": None,
        "tempo_total_s": round(tempo_total, 1),
        "segundos_por_anuncio": round(tempo_total / len(anuncios), 2) if anuncios else None,
    }
    logger.info("[superantigo] coleta completa: %s", metricas)
    return anuncios, metricas


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """
    Busca anúncios no Super Antigo por marca e modelo.
    Coleta até `paginas` páginas (Playwright) e filtra os resultados.
    """
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen_urls: set[str] = set()

    with criar_contexto() as ctx:
        page = ctx.new_page()
        for pagina in range(1, paginas + 1):
            url = _url_pagina(pagina)
            html = _navegar(page, url)
            if html is None:
                break

            itens = parsear_listagem_html(html, data_coleta)
            if not itens:
                break

            novos = 0
            for a in itens:
                if a.url in seen_urls:
                    continue
                titulo_norm = normalizar_texto(a.titulo)
                if modelo_norm and modelo_norm not in titulo_norm:
                    if not a.modelo or modelo_norm not in normalizar_texto(a.modelo):
                        continue
                if (marca_norm and a.marca
                        and normalizar_texto(a.marca) != marca_norm
                        and marca_norm not in titulo_norm):
                    continue
                seen_urls.add(a.url)
                anuncios.append(a)
                novos += 1

            if novos == 0 or len(itens) < DEFAULT_LIMIT:
                break
            time.sleep(RATE_LIMIT)

    logger.info("[superantigo] busca: %d anúncio(s)", len(anuncios))
    return anuncios


# ── Parsers públicos ──────────────────────────────────────────────────────────

def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """
    Extrai anúncios de HTML renderizado da listagem Super Antigo.

    Ponto de entrada público para testes de regressão com snapshot.

    Estratégia de extração por card:
    - Container: div pai do link de veículo (2 níveis acima do <a>)
    - Título:    h3 dentro da div.p-4
    - Preço:     regex R$ no texto da div.p-4
    - Marca:     segmento [3] da URL (slug → canônico)
    - Modelo:    segmento [4] da URL (slug capitalizado)
    - Ano:       primeiro 4-digit válido (1900-2026) no slug da URL
    - URL:       BASE_URL + href
    """
    soup = BeautifulSoup(html, "lxml")

    todos_links = soup.select("a[href^='/veiculos/carro/']")
    seen: set[str] = set()
    links_unicos = [
        a for a in todos_links
        if a.get("href") not in seen and not seen.add(a.get("href", ""))
    ]

    anuncios: list[Anuncio] = []

    for link_tag in links_unicos:
        href = link_tag.get("href", "")
        if not href:
            continue

        card = link_tag.parent
        if card:
            card = card.parent

        if not card:
            continue

        content = card.find("div", class_=lambda c: c and "p-4" in c.split())
        if not content:
            continue

        h3 = content.find("h3")
        titulo = h3.get_text(strip=True) if h3 else ""
        if not titulo:
            continue

        card_txt = content.get_text(separator=" ", strip=True)
        preco_match = re.search(r"R\$\s*([\d.,]+)", card_txt)
        preco_bruto = preco_match.group(0) if preco_match else ""
        preco = normalizar_preco(preco_bruto)
        if preco is None or preco <= 0:
            continue

        partes = href.split("/")
        marca = _slug_para_marca(partes[3] if len(partes) > 3 else "")
        modelo_raw = partes[4].replace("-", " ").upper() if len(partes) > 4 else ""
        slug_final = partes[5] if len(partes) > 5 else ""
        ano = _extrair_ano_do_slug(slug_final)

        if not modelo_raw:
            continue

        # Marca/modelo vêm do slug da URL (estruturado) — passa pelo catálogo
        # antes de gravar, como toda fonte estruturada (ver separar_marca_modelo_versao_obs).
        marca, modelo_raw, versao, obs = separar_marca_modelo_versao_obs(marca, modelo_raw)

        anuncios.append(
            Anuncio(
                titulo=titulo,
                preco=preco,
                marca=marca,
                modelo=modelo_raw,
                ano=ano,
                versao=versao,
                obs=obs,
                url=BASE_URL + href,
                fonte=FONTE,
                data_coleta=data_coleta,
            )
        )

    return anuncios


# ── Helpers internos ──────────────────────────────────────────────────────────

def _url_pagina(pagina: int) -> str:
    params = urllib.parse.urlencode({
        "showAllTypes": "true",
        "page": str(pagina),
        "limit": str(DEFAULT_LIMIT),
        "sort": "newest",
    })
    return f"{LISTING_BASE}{LISTING_PATH}?{params}"


def _navegar(page, url: str) -> Optional[str]:
    """Navega até `url` no Playwright e devolve o HTML renderizado, ou None em erro."""
    try:
        page.goto(url, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2000)
        return page.content()
    except Exception as exc:
        logger.warning("[superantigo] erro ao navegar %s: %s", url, exc)
        return None


def _slug_para_marca(slug: str) -> str:
    return _SLUG_PARA_MARCA.get(slug.lower(), slug.upper().replace("-", " "))


def _extrair_ano_do_slug(slug: str) -> Optional[int]:
    """
    Extrai o ano de fabricação do slug final da URL.
    Padrão: {titulo-slug}-{ano_fab}-{ano_mod}-{id}
    """
    numeros = re.findall(r"\d{4}", slug)
    for n in numeros:
        v = int(n)
        if 1900 <= v <= 2026:
            return v
    return None
