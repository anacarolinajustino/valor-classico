"""
Conector OLX Brasil — coleta anúncios de veículos via Playwright + __NEXT_DATA__.

Site: https://www.olx.com.br
Motor: Next.js SSR
Estratégia: Playwright headless com proxy residencial DataImpulse + stealth
(via `src.connectors._browser.criar_contexto()`, mesma receita do Mercado
Livre) — requests puro retorna 403 Cloudflare em todas as URLs, e Playwright
"puro" sem stealth também é bloqueado por detecção de fingerprint de
automação (2026-07-09: mesmo padrão de bloqueio do ML antes do stealth).

Compliance (verificado 2026-06-14):
- robots.txt: /autos-e-pecas/ ✅ permitido | /q/* Disallowed (usamos ?q= param — ok)
- Rate limit: 2s entre páginas (Playwright é custoso, igual ao SuperAntigo)

Separação de responsabilidades:
- buscar()           → I/O (Playwright), chama parsear_listagem()
- parsear_listagem() → função pura (__NEXT_DATA__ JSON), usada nos testes de snapshot
- coletar_categoria()→ navega a categoria /autos-e-pecas/ com filtro de ano (modo principal)
- coletar_completo() → batch por um único termo de busca
- coletar_sweep()    → varre TERMOS_SWEEP numa sessão única (fallback)
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from src.connectors._browser import criar_contexto
from src.pipeline.normalizer import inferir_marca_modelo_ano, normalizar_preco, normalizar_texto
from src.pipeline.persistence import ANO_CORTE_CLASSICO
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
# Configurações do conector
# ────────────────────────────────────────────────
FONTE = "olx"
BASE_URL = "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios"
TIMEOUT_PAGINA = 30_000   # ms — timeout do Playwright por navegação
RATE_LIMIT_SEGUNDOS = 2.0  # entre páginas (browser é custoso)
TERMO_BATCH = "carros antigos"

# Termos usados no sweep — fallback caso coletar_categoria() não cubra bem
TERMOS_SWEEP: list[str] = [
    "fusca", "kombi", "brasilia volkswagen", "karmann ghia", "variant volkswagen",
    "maverick ford", "corcel ford", "galaxie ford", "rural willys", "opala chevrolet",
    "chevette", "veraneio", "c10 chevrolet", "dodge dart", "dodge charger",
    "bandeirante", "gol quadrado", "puma carro", "sp1 volkswagen", "carros antigos",
]


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """
    Busca anúncios na OLX por marca e modelo via Playwright.

    Args:
        marca:   Nome da marca (ex.: "VOLKSWAGEN"). Usado para pós-filtragem.
        modelo:  Nome do modelo (ex.: "FUSCA"). Usado no termo de busca.
        paginas: Número máximo de páginas a coletar (default 2).

    Returns:
        Lista de Anuncio normalizados com ano <= ANO_CORTE_CLASSICO.
    """
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []

    try:
        with criar_contexto() as ctx:
            pw_page = ctx.new_page()

            for pagina in range(1, paginas + 1):
                url_pagina = _url_busca(modelo, pagina)
                logger.info("[olx] buscando página %d — %s", pagina, url_pagina)

                try:
                    pw_page.goto(url_pagina, timeout=TIMEOUT_PAGINA, wait_until="domcontentloaded")
                except Exception as exc:
                    logger.warning("[olx] timeout navegando para %s: %s", url_pagina, exc)
                    break

                html = pw_page.content()
                itens = parsear_listagem(html, data_coleta)

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

                logger.info("[olx] página %d: %d anúncio(s).", pagina, len(itens))
                anuncios.extend(itens)

                if pagina < paginas:
                    time.sleep(RATE_LIMIT_SEGUNDOS)

    except Exception as exc:
        logger.error("[olx] erro durante busca: %s", exc)
        raise

    latencia = time.monotonic() - inicio
    logger.info("[olx] busca concluída: %d anúncio(s) em %.1fs", len(anuncios), latencia)
    return anuncios


def coletar_categoria(
    max_paginas: int = 200,
    ano_ate: int = ANO_CORTE_CLASSICO,
) -> tuple[list[Anuncio], dict]:
    """
    Coleta anúncios diretamente da categoria OLX /autos-e-pecas/carros-vans-e-utilitarios.
    OLX não suporta filtro de ano por URL — a filtragem é feita exclusivamente
    pelo campo regdate no __NEXT_DATA__ (client-side, em _parsear_ads).

    É a estratégia principal: cobre toda a categoria sem depender de termos de busca.

    Args:
        max_paginas: Teto de páginas (default 200). OLX normalmente limita a ~100-150.
        ano_ate:     Filtro de ano no URL e no parser (default ANO_CORTE_CLASSICO=2000).

    Returns:
        (anuncios, metricas)
    """
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()
    anuncios: list[Anuncio] = []
    seen_urls: set[str] = set()
    paginas_lidas = 0
    erros = 0
    descartados = 0
    descartados_ano = 0
    latencias: list[float] = []
    page_size = 50  # OLX pagina ~50 cards/página (observado 2026-07-09)

    logger.info("[olx] categoria: iniciando coleta até ano %d, max %d páginas", ano_ate, max_paginas)

    try:
        with criar_contexto() as ctx:
            pw_page = ctx.new_page()

            for pagina in range(1, max_paginas + 1):
                url_pagina = _url_categoria(pagina, ano_ate)
                logger.info("[olx] categoria pág %d — %s", pagina, url_pagina)

                t0 = time.monotonic()
                try:
                    pw_page.goto(url_pagina, timeout=TIMEOUT_PAGINA, wait_until="domcontentloaded")
                except Exception as exc:
                    logger.warning("[olx] timeout pág %d: %s", pagina, exc)
                    erros += 1
                    break
                latencias.append(time.monotonic() - t0)

                html = pw_page.content()
                itens, disc_sem_preco, disc_ano, total_cards = _parsear_ads_dom(html, data_coleta, ano_ate)

                if not total_cards:
                    logger.warning("[olx] categoria pág %d: sem anúncios — parando.", pagina)
                    break

                descartados += disc_sem_preco
                descartados_ano += disc_ano
                paginas_lidas += 1

                novos = 0
                for a in itens:
                    if a.url not in seen_urls:
                        seen_urls.add(a.url)
                        anuncios.append(a)
                        novos += 1

                logger.info(
                    "[olx] categoria pág %d: %d brutos → %d válidos → %d novos (total: %d)",
                    pagina, total_cards, len(itens), novos, len(anuncios),
                )

                if total_cards < page_size:
                    logger.info("[olx] categoria: página incompleta — última página (%d).", pagina)
                    break

                time.sleep(RATE_LIMIT_SEGUNDOS)

    except Exception as exc:
        logger.error("[olx] erro durante coleta de categoria: %s", exc)
        raise

    tempo_total = time.monotonic() - inicio
    lat_ord = sorted(latencias)
    metricas = {
        "fonte": FONTE,
        "modo": "categoria",
        "ano_ate": ano_ate,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_lidas,
        "urls_detalhe": len(seen_urls),
        "anuncios_validos": len(anuncios),
        "descartados_sem_preco_ou_modelo": descartados,
        "descartados_ano_fora_corte": descartados_ano,
        "erros_listagem": erros,
        "erros_detalhe": 0,
        "requisicoes": len(latencias),
        "latencia_p50_s": round(lat_ord[len(lat_ord) // 2], 2) if lat_ord else None,
        "latencia_p95_s": round(lat_ord[int(len(lat_ord) * 0.95)], 2) if lat_ord else None,
        "tempo_total_s": round(tempo_total, 1),
        "segundos_por_anuncio": round(tempo_total / len(anuncios), 2) if anuncios else None,
    }
    logger.info("[olx] categoria concluída: %s", metricas)
    return anuncios, metricas


def coletar_completo(max_paginas: int = 50, termo: str = TERMO_BATCH) -> tuple[list[Anuncio], dict]:
    """
    Coleta anúncios da OLX em batch para um único termo de busca.

    Args:
        max_paginas: Teto de páginas a coletar (default 50).
        termo:       Termo de busca (default "carros antigos").

    Returns:
        (anuncios, metricas)
    """
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()
    seen_urls: set[str] = set()

    try:
        with criar_contexto() as ctx:
            pw_page = ctx.new_page()
            anuncios, parcial = _varrer_termo(pw_page, termo, max_paginas, data_coleta, seen_urls)
    except Exception as exc:
        logger.error("[olx] erro durante coleta: %s", exc)
        raise

    tempo_total = time.monotonic() - inicio
    latencias = parcial["latencias"]
    lat_ord = sorted(latencias)
    metricas = {
        "fonte": FONTE,
        "modo": "termo",
        "termo": termo,
        "data_coleta": data_coleta,
        "paginas_listagem": parcial["paginas_lidas"],
        "urls_detalhe": len(seen_urls),
        "anuncios_validos": len(anuncios),
        "descartados_sem_preco_ou_modelo": parcial["descartados"],
        "descartados_ano_fora_corte": parcial["descartados_ano"],
        "erros_listagem": parcial["erros"],
        "erros_detalhe": 0,
        "requisicoes": len(latencias),
        "latencia_p50_s": round(lat_ord[len(lat_ord) // 2], 2) if lat_ord else None,
        "latencia_p95_s": round(lat_ord[int(len(lat_ord) * 0.95)], 2) if lat_ord else None,
        "tempo_total_s": round(tempo_total, 1),
        "segundos_por_anuncio": round(tempo_total / len(anuncios), 2) if anuncios else None,
    }
    logger.info("[olx] coleta completa: %s", metricas)
    return anuncios, metricas


def coletar_sweep(
    max_paginas_por_termo: int = 20,
    termos: list[str] | None = None,
) -> tuple[list[Anuncio], dict]:
    """
    Varredura por termos: itera TERMOS_SWEEP numa única sessão de browser.
    Fallback — prefira coletar_categoria() para cobertura mais completa.

    Args:
        max_paginas_por_termo: Teto de páginas por termo (default 20).
        termos: Lista de termos. Default: TERMOS_SWEEP.

    Returns:
        (anuncios, metricas)
    """
    termos = termos or TERMOS_SWEEP
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()
    seen_urls: set[str] = set()
    todos_anuncios: list[Anuncio] = []
    total_paginas = 0
    total_erros = 0
    total_descartados = 0
    total_descartados_ano = 0
    todas_latencias: list[float] = []

    logger.info("[olx] sweep: %d termos, até %d páginas/termo", len(termos), max_paginas_por_termo)

    try:
        with criar_contexto() as ctx:
            pw_page = ctx.new_page()

            for i, termo in enumerate(termos, 1):
                logger.info("[olx] sweep %d/%d — '%s'", i, len(termos), termo)
                antes = len(todos_anuncios)

                anuncios_termo, parcial = _varrer_termo(
                    pw_page, termo, max_paginas_por_termo, data_coleta, seen_urls
                )
                todos_anuncios.extend(anuncios_termo)
                total_paginas += parcial["paginas_lidas"]
                total_erros += parcial["erros"]
                total_descartados += parcial["descartados"]
                total_descartados_ano += parcial["descartados_ano"]
                todas_latencias.extend(parcial["latencias"])

                logger.info(
                    "[olx] sweep '%s': +%d anúncios (acumulado: %d)",
                    termo, len(todos_anuncios) - antes, len(todos_anuncios),
                )

    except Exception as exc:
        logger.error("[olx] erro durante sweep: %s", exc)
        raise

    tempo_total = time.monotonic() - inicio
    lat_ord = sorted(todas_latencias)
    metricas = {
        "fonte": FONTE,
        "modo": "sweep",
        "termos": termos,
        "data_coleta": data_coleta,
        "paginas_listagem": total_paginas,
        "urls_detalhe": len(seen_urls),
        "anuncios_validos": len(todos_anuncios),
        "descartados_sem_preco_ou_modelo": total_descartados,
        "descartados_ano_fora_corte": total_descartados_ano,
        "erros_listagem": total_erros,
        "erros_detalhe": 0,
        "requisicoes": len(todas_latencias),
        "latencia_p50_s": round(lat_ord[len(lat_ord) // 2], 2) if lat_ord else None,
        "latencia_p95_s": round(lat_ord[int(len(lat_ord) * 0.95)], 2) if lat_ord else None,
        "tempo_total_s": round(tempo_total, 1),
        "segundos_por_anuncio": round(tempo_total / len(todos_anuncios), 2) if todos_anuncios else None,
    }
    logger.info("[olx] sweep concluído: %s", metricas)
    return todos_anuncios, metricas


# ────────────────────────────────────────────────
# Parser puro — testável sem browser
# ────────────────────────────────────────────────

def parsear_listagem(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """
    Extrai anúncios de HTML renderizado da OLX via cards `section.olx-adcard`.

    Ponto de entrada público para testes de regressão com snapshot.
    Aplica filtro ANO_CORTE_CLASSICO internamente (AC3).

    Args:
        html:        HTML completo da página (renderizado, com os cards de anúncio).
        data_coleta: Data ISO 8601 (default "2000-01-01").

    Returns:
        Lista de Anuncio com ano <= ANO_CORTE_CLASSICO e preço > 0.
    """
    anuncios, _, _, _ = _parsear_ads_dom(html, data_coleta)
    return anuncios


# ────────────────────────────────────────────────
# Helpers internos
# ────────────────────────────────────────────────

def _varrer_termo(
    pw_page: Any,
    termo: str,
    max_paginas: int,
    data_coleta: str,
    seen_urls: set[str],
) -> tuple[list[Anuncio], dict]:
    """
    Coleta todas as páginas de um único termo usando um page Playwright existente.
    Mutaciona seen_urls para deduplicação cross-termo.
    """
    anuncios: list[Anuncio] = []
    paginas_lidas = 0
    erros = 0
    descartados = 0
    descartados_ano = 0
    latencias: list[float] = []
    page_size = 50  # OLX pagina ~50 cards/página (observado 2026-07-09)

    for pagina in range(1, max_paginas + 1):
        url_pagina = _url_busca(termo, pagina)
        logger.info("[olx] '%s' pág %d — %s", termo, pagina, url_pagina)

        t0 = time.monotonic()
        try:
            pw_page.goto(url_pagina, timeout=TIMEOUT_PAGINA, wait_until="domcontentloaded")
        except Exception as exc:
            logger.warning("[olx] timeout '%s' pág %d: %s", termo, pagina, exc)
            erros += 1
            break
        latencias.append(time.monotonic() - t0)

        html = pw_page.content()
        itens, disc_sem_preco, disc_ano, total_cards = _parsear_ads_dom(html, data_coleta)
        descartados += disc_sem_preco
        descartados_ano += disc_ano
        paginas_lidas += 1

        novos = 0
        for a in itens:
            if a.url not in seen_urls:
                seen_urls.add(a.url)
                anuncios.append(a)
                novos += 1

        logger.info(
            "[olx] '%s' pág %d: %d brutos → %d válidos → %d novos (único total: %d)",
            termo, pagina, total_cards, len(itens), novos, len(seen_urls),
        )

        if total_cards < page_size:
            logger.info("[olx] '%s': página incompleta — fim do termo.", termo)
            break

        if pagina < max_paginas:
            time.sleep(RATE_LIMIT_SEGUNDOS)

    return anuncios, {
        "paginas_lidas": paginas_lidas,
        "erros": erros,
        "descartados": descartados,
        "descartados_ano": descartados_ano,
        "latencias": latencias,
    }


def _parsear_ads_dom(
    html: str,
    data_coleta: str,
    ano_ate: int = ANO_CORTE_CLASSICO,
) -> tuple[list[Anuncio], int, int, int]:
    """
    Extrai anúncios dos cards `section.olx-adcard` do HTML renderizado.

    A OLX removia o ano num campo estruturado (`properties[].regdate`) quando
    a listagem vinha de `<script id="__NEXT_DATA__">` — esse script sumiu do
    frontend (verificado 2026-07-09, site migrado para Next.js App Router sem
    embutir os dados da busca em JSON). O ano agora só existe no título
    ("Volkswagen Fusca Fusca (gasolina) 1970"), extraído via
    `inferir_marca_modelo_ano`.

    Returns:
        (anuncios, descartados_sem_preco_ou_modelo, descartados_ano_fora_corte, total_cards)
    """
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("section.olx-adcard")
    anuncios: list[Anuncio] = []
    descartados_sem_preco = 0
    descartados_ano = 0

    for card in cards:
        link = card.select_one("a.olx-adcard__link")
        url = link.get("href", "").strip() if link else ""
        if not url:
            descartados_sem_preco += 1
            continue

        title_tag = card.select_one("h2.olx-adcard__title")
        titulo = (
            title_tag.get_text(strip=True) if title_tag
            else (link.get("title") or "").strip()
        )
        if not titulo:
            descartados_sem_preco += 1
            continue

        price_tag = card.select_one("h3.olx-adcard__price")
        preco = normalizar_preco(price_tag.get_text(strip=True)) if price_tag else None
        if preco is None or preco <= 0:
            descartados_sem_preco += 1
            continue

        marca, modelo, ano = inferir_marca_modelo_ano(titulo)
        if not modelo:
            descartados_sem_preco += 1
            continue

        # Filtro de ruído obrigatório: apenas veículos até ano_ate
        if not ano or not (1900 <= ano <= ano_ate):
            descartados_ano += 1
            continue

        anuncios.append(
            Anuncio(
                titulo=titulo,
                preco=preco,
                marca=marca,
                modelo=modelo,
                ano=ano,
                versao=None,
                url=url,
                fonte=FONTE,
                data_coleta=data_coleta,
            )
        )

    if descartados_ano:
        logger.debug("[olx] descartados por ano fora do corte: %d", descartados_ano)

    return anuncios, descartados_sem_preco, descartados_ano, len(cards)


def _url_busca(termo: str, pagina: int = 1) -> str:
    """Monta URL de busca OLX com paginação via ?o=N (1-based)."""
    params: dict[str, str] = {"q": termo}
    if pagina > 1:
        params["o"] = str(pagina)
    return f"{BASE_URL}?{urllib.parse.urlencode(params)}"


def _url_categoria(pagina: int = 1, ano_ate: int = ANO_CORTE_CLASSICO) -> str:
    """
    Monta URL da categoria OLX sem filtro de ano.

    OLX Brasil ignora parâmetros de ano no URL (testado: sf=1&ae=2000 retorna
    carros de todos os anos). Filtragem por ano feita exclusivamente em
    _parsear_ads() via campo regdate do __NEXT_DATA__.
    """
    params: dict[str, str] = {}
    if pagina > 1:
        params["o"] = str(pagina)
    return f"{BASE_URL}?{urllib.parse.urlencode(params)}" if params else BASE_URL
