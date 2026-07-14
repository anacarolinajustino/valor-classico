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
- coletar_categoria()→ navega a categoria /autos-e-pecas/ com filtro de ano rs/re
                       no servidor, fatiado por faixas de ano (modo principal)
- coletar_completo() → ponto de entrada do painel admin (app.py chama `mod.coletar_completo()`
                       genericamente p/ toda fonte); delega para coletar_categoria()
- coletar_por_termo()→ batch por um único termo de busca (uso pontual/manual, não é chamado
                       pelo painel admin)
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


def _faixas_ano(ano_ate: int) -> list[tuple[int, int]]:
    """
    Fatias de ano para a coleta de categoria, cada uma abaixo de ~5.000
    resultados (teto de paginação da OLX: ~100 páginas × 50 cards — depois
    disso o site repete a última página real em vez de avançar).

    Contagens medidas em 2026-07-14: 1900-1959 (133), 1960-1969 (553),
    1970-1979 (2.836), 1980-1989 (3.791), 1990-1994 (4.108). De 1995 em
    diante o volume anual cresce demais pra agrupar década (1995-1999
    sozinho tem 8.157) — fatia ano a ano até o corte.
    """
    faixas = [(1900, 1959), (1960, 1969), (1970, 1979), (1980, 1989), (1990, 1994)]
    faixas += [(a, a) for a in range(1995, ano_ate + 1)]
    return [(de, min(ate, ano_ate)) for de, ate in faixas if de <= ano_ate]


def coletar_categoria(
    max_paginas: int = 120,
    ano_ate: int = ANO_CORTE_CLASSICO,
    faixas: list[tuple[int, int]] | None = None,
) -> tuple[list[Anuncio], dict]:
    """
    Coleta anúncios da categoria OLX /autos-e-pecas/carros-vans-e-utilitarios
    com filtro de ano aplicado NO SERVIDOR via parâmetros rs/re (descoberto
    pelo usuário em 2026-07-14 — o teste antigo usava sf/ae, que a OLX
    ignora, por isso o conector filtrava só client-side e desperdiçava ~98%
    da banda com carros modernos).

    Como a OLX limita a paginação a ~100 páginas por consulta (~5.000
    resultados), a coleta é fatiada por faixas de ano (_faixas_ano), cada
    faixa abaixo do teto. O parser mantém o filtro de ano client-side como
    defesa em profundidade.

    É a estratégia principal: cobre o universo inteiro de anúncios até
    `ano_ate` (~21.400 em 2026-07-14) sem depender de termos de busca.

    Args:
        max_paginas: Teto de páginas POR FAIXA de ano (default 120 — um pouco
                     acima do teto real de ~100 pra guarda de repetição agir).
        ano_ate:     Corte de ano (default ANO_CORTE_CLASSICO=2000).
        faixas:      Faixas de ano a varrer (default: _faixas_ano(ano_ate)).
                     Útil pra recoletar só faixas que falharam numa rodada.

    Returns:
        (anuncios, metricas)
    """
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()
    faixas = faixas if faixas is not None else _faixas_ano(ano_ate)
    anuncios: list[Anuncio] = []
    seen_urls: set[str] = set()
    paginas_lidas = 0
    erros = 0
    descartados = 0
    descartados_ano = 0
    latencias: list[float] = []
    page_size = 50  # OLX pagina ~50 cards/página (observado 2026-07-09)

    logger.info(
        "[olx] categoria: %d faixas de ano até %d, max %d páginas/faixa",
        len(faixas), ano_ate, max_paginas,
    )

    try:
        with criar_contexto() as ctx:
            pw_page = ctx.new_page()

            for ano_de, ano_fim in faixas:
                # URLs brutas (todos os cards, válidos ou não) vistas nesta
                # faixa — detecta o teto de paginação: além dele a OLX devolve
                # a última página real repetida, em vez de 404/página vazia.
                urls_brutas_faixa: set[str] = set()
                antes = len(anuncios)

                for pagina in range(1, max_paginas + 1):
                    url_pagina = _url_categoria(pagina, ano_de, ano_fim)
                    logger.info("[olx] faixa %d-%d pág %d — %s", ano_de, ano_fim, pagina, url_pagina)

                    # Soluços transitórios de rede/proxy são comuns em coletas
                    # longas (2026-07-14: 2 em 400 páginas, cada um matando a
                    # faixa inteira) — tenta a mesma página de novo antes de
                    # desistir da faixa.
                    t0 = time.monotonic()
                    erro_nav: Exception | None = None
                    for tentativa in range(1, 3):
                        try:
                            pw_page.goto(url_pagina, timeout=TIMEOUT_PAGINA, wait_until="domcontentloaded")
                            erro_nav = None
                            break
                        except Exception as exc:
                            erro_nav = exc
                            logger.warning(
                                "[olx] erro de navegação faixa %d-%d pág %d (tentativa %d/2): %s",
                                ano_de, ano_fim, pagina, tentativa, exc,
                            )
                            time.sleep(RATE_LIMIT_SEGUNDOS)
                    if erro_nav is not None:
                        erros += 1
                        break
                    latencias.append(time.monotonic() - t0)

                    html = pw_page.content()
                    urls_pagina = _urls_cards(html)
                    itens, disc_sem_preco, disc_ano, total_cards = _parsear_ads_dom(html, data_coleta, ano_ate)

                    if not total_cards:
                        logger.info("[olx] faixa %d-%d pág %d: sem anúncios — fim da faixa.", ano_de, ano_fim, pagina)
                        break

                    if urls_pagina and urls_pagina <= urls_brutas_faixa:
                        logger.info(
                            "[olx] faixa %d-%d pág %d: página repetida (teto de paginação) — fim da faixa.",
                            ano_de, ano_fim, pagina,
                        )
                        break
                    urls_brutas_faixa |= urls_pagina

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
                        "[olx] faixa %d-%d pág %d: %d brutos → %d válidos → %d novos (total: %d)",
                        ano_de, ano_fim, pagina, total_cards, len(itens), novos, len(anuncios),
                    )

                    if total_cards < page_size:
                        logger.info("[olx] faixa %d-%d: página incompleta — última página (%d).", ano_de, ano_fim, pagina)
                        break

                    time.sleep(RATE_LIMIT_SEGUNDOS)

                logger.info(
                    "[olx] faixa %d-%d concluída: +%d anúncios (acumulado: %d)",
                    ano_de, ano_fim, len(anuncios) - antes, len(anuncios),
                )
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
        "faixas_ano": [f"{de}-{ate}" for de, ate in faixas],
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


def coletar_completo(
    max_paginas: int = 120,
    ano_ate: int = ANO_CORTE_CLASSICO,
) -> tuple[list[Anuncio], dict]:
    """
    Ponto de entrada da coleta batch da OLX — chamado pelo dispatcher genérico
    do painel admin (`app.py` faz `mod.coletar_completo()` sem argumentos para
    toda fonte). Delega para coletar_categoria(): categoria inteira com filtro
    de ano rs/re no servidor, fatiada por faixas de ano.

    Antes desta função varria só o termo fixo "carros antigos", o que cobria
    apenas anúncios cujo título continha essa frase literal (uma fração
    pequena e repetitiva do catálogo real da OLX) — ver coletar_por_termo()
    para essa estratégia antiga, ainda disponível para uso pontual/manual.

    Args:
        max_paginas: Teto de páginas por faixa de ano (default 120).
        ano_ate:     Corte de ano (default ANO_CORTE_CLASSICO).

    Returns:
        (anuncios, metricas)
    """
    return coletar_categoria(max_paginas=max_paginas, ano_ate=ano_ate)


def coletar_por_termo(max_paginas: int = 50, termo: str = TERMO_BATCH) -> tuple[list[Anuncio], dict]:
    """
    Coleta anúncios da OLX em batch para um único termo de busca.

    Cobertura limitada ao que o próprio buscador da OLX casar com `termo`
    (fraco para termos genéricos como "carros antigos" — prefira
    coletar_categoria()/coletar_completo() para cobertura ampla). Mantida para
    uso pontual/manual (ex.: `scripts/ingest_olx.py --modo termo`).

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


def _urls_cards(html: str) -> set[str]:
    """
    URLs de TODOS os cards da página (válidos ou não pro nosso filtro) —
    usado pra detectar o teto de paginação da OLX, que repete a última
    página real em vez de retornar vazio quando o offset passa do limite.
    """
    soup = BeautifulSoup(html, "lxml")
    return {
        link["href"].strip()
        for link in soup.select("section.olx-adcard a.olx-adcard__link")
        if link.get("href")
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


def _url_categoria(
    pagina: int = 1,
    ano_de: int = 1900,
    ano_ate: int = ANO_CORTE_CLASSICO,
) -> str:
    """
    Monta URL da categoria OLX com filtro de ano rs/re (aplicado no servidor).

    rs = ano mínimo, re = ano máximo — descobertos pelo usuário em 2026-07-14.
    (Os parâmetros sf/ae testados em 2026-07-09 eram os errados: a OLX os
    ignora silenciosamente, o que levou à conclusão incorreta de que não
    havia filtro de ano por URL.)
    """
    params: dict[str, str] = {"rs": str(ano_de), "re": str(ano_ate)}
    if pagina > 1:
        params["o"] = str(pagina)
    return f"{BASE_URL}?{urllib.parse.urlencode(params)}"
