"""
Conector Super Antigo — coleta anúncios de veículos clássicos.

Site: https://www.superantigo.com.br
Motor: Vite + React SPA (Client-Side Rendering)
Estratégia: Playwright headless (requests + BS4 retorna shell vazio de ~7.5KB)

Compliance (verificado 2026-05-30):
- robots.txt: Allow: /veiculos/ ✅  |  Disallow: /api/ (não utilizado)
- Rate limit: 2s entre páginas (browser é mais custoso que requests)
- User-Agent realista definido abaixo.

Separação de responsabilidades:
- buscar()              → I/O (Playwright), chama parsear_listagem_html()
- parsear_listagem_html() → função pura (BS4), usada nos testes de snapshot
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from src.pipeline.normalizer import normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
# Configurações do conector
# ────────────────────────────────────────────────
FONTE = "superantigo"
BASE_URL = "https://www.superantigo.com.br"
LISTING_PATH = "/veiculos"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT_PAGINA = 30_000   # ms — timeout do Playwright por navegação
TIMEOUT_SELECTOR = 15_000  # ms — aguardar cards carregarem
RATE_LIMIT_SEGUNDOS = 2.0  # entre páginas (browser é pesado)

# Mapeamento slug de URL → nome canônico da marca
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


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """
    Busca anúncios no Super Antigo por marca e modelo.

    Usa Playwright (headless Chromium) para renderizar o SPA e coletar o HTML.
    Para paginação, clica no botão "próxima página" em vez de navegar por URL
    (os links de paginação usam href="#" — controle 100% client-side).

    Args:
        marca:   Nome da marca (ex.: "VOLKSWAGEN"). Usado para pós-filtragem.
        modelo:  Nome do modelo (ex.: "FUSCA"). Usado no filtro de URL.
        paginas: Número máximo de páginas a coletar (default 2).

    Returns:
        Lista de Anuncio normalizados. Anúncios sem preço válido são descartados.
    """
    try:
        from playwright.sync_api import sync_playwright  # import tardio — opcional
    except ImportError as exc:
        raise RuntimeError(
            "Playwright não instalado. Execute: pip install playwright && "
            "python -m playwright install chromium"
        ) from exc

    inicio = time.monotonic()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=USER_AGENT, locale="pt-BR")
            pw_page = ctx.new_page()

            url_inicial = _url_busca(marca, modelo)
            logger.info("[superantigo] navegando para %s", url_inicial)

            pw_page.goto(url_inicial, timeout=TIMEOUT_PAGINA, wait_until="networkidle")

            for pagina in range(1, paginas + 1):
                # Aguardar cards carregarem
                try:
                    pw_page.wait_for_selector(
                        "a[href^='/veiculos/carro/']",
                        timeout=TIMEOUT_SELECTOR,
                    )
                except Exception:
                    logger.warning("[superantigo] timeout aguardando cards na página %d.", pagina)
                    break

                html = pw_page.content()
                itens = parsear_listagem_html(html, data_coleta)

                # Pós-filtragem por marca
                if marca_norm:
                    itens = [
                        a for a in itens
                        if not a.marca
                        or normalizar_texto(a.marca) == marca_norm
                        or marca_norm in normalizar_texto(a.titulo)
                    ]

                # Pós-filtragem por modelo
                if modelo_norm:
                    itens = [
                        a for a in itens
                        if not a.modelo
                        or modelo_norm in normalizar_texto(a.modelo)
                        or normalizar_texto(a.modelo) in modelo_norm
                        or modelo_norm in normalizar_texto(a.titulo)
                    ]

                logger.info("[superantigo] página %d: %d anúncio(s).", pagina, len(itens))
                anuncios.extend(itens)

                # Avançar para próxima página via click (paginação JS)
                if pagina < paginas:
                    avancar = pw_page.query_selector(
                        "a[aria-label='Ir para a próxima página']"
                    )
                    if not avancar:
                        logger.info("[superantigo] última página atingida (%d).", pagina)
                        break
                    # Verificar se botão está desabilitado
                    disabled = avancar.get_attribute("disabled")
                    aria_disabled = avancar.get_attribute("aria-disabled")
                    if disabled is not None or aria_disabled == "true":
                        logger.info("[superantigo] última página atingida (%d).", pagina)
                        break

                    avancar.click()
                    pw_page.wait_for_load_state("networkidle", timeout=10_000)
                    time.sleep(RATE_LIMIT_SEGUNDOS)

            browser.close()

    except Exception as exc:
        logger.error("[superantigo] erro durante coleta: %s", exc)
        raise

    latencia = time.monotonic() - inicio
    logger.info(
        "[superantigo] busca concluída: %d anúncio(s) em %.1fs",
        len(anuncios), latencia,
    )
    return anuncios


# ────────────────────────────────────────────────
# Parser puro — testável sem browser
# ────────────────────────────────────────────────

def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """
    Extrai anúncios de um HTML renderizado da listagem Super Antigo.

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

    # Coletar links únicos de veículos
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

        # Card container (2 níveis acima do <a>: div.relative → card)
        card = link_tag.parent
        if card:
            card = card.parent

        if not card:
            continue

        # Seção de conteúdo textual do card (div com classe p-4)
        content = card.find("div", class_=lambda c: c and "p-4" in c.split())
        if not content:
            continue

        # Título
        h3 = content.find("h3")
        titulo = h3.get_text(strip=True) if h3 else ""
        if not titulo:
            continue

        # Preço — regex no texto do card
        card_txt = content.get_text(separator=" ", strip=True)
        preco_match = re.search(r"R\$\s*([\d.,]+)", card_txt)
        preco_bruto = preco_match.group(0) if preco_match else ""
        preco = normalizar_preco(preco_bruto)
        if preco is None or preco <= 0:
            continue

        # Campos da URL: /veiculos/carro/{marca}/{modelo}/{slug-ano-id}
        partes = href.split("/")
        marca = _slug_para_marca(partes[3] if len(partes) > 3 else "")
        modelo_raw = partes[4].replace("-", " ").upper() if len(partes) > 4 else ""
        slug_final = partes[5] if len(partes) > 5 else ""
        ano = _extrair_ano_do_slug(slug_final)

        if not modelo_raw:
            continue

        url_anuncio = BASE_URL + href

        anuncios.append(
            Anuncio(
                titulo=titulo,
                preco=preco,
                marca=marca,
                modelo=modelo_raw,
                ano=ano,
                versao=None,
                url=url_anuncio,
                fonte=FONTE,
                data_coleta=data_coleta,
            )
        )

    return anuncios


# ────────────────────────────────────────────────
# Helpers internos
# ────────────────────────────────────────────────

def _url_busca(marca: str, modelo: str) -> str:
    """Monta URL de listagem com filtros de marca e modelo."""
    import urllib.parse

    marca_slug = marca.lower().replace(" ", "-")
    modelo_slug = modelo.lower().replace(" ", "-")
    params = urllib.parse.urlencode({
        "brand": marca_slug,
        "model": modelo_slug,
        "vehicleType": "car",
        "page": "1",
        "limit": "12",
    })
    return f"{BASE_URL}{LISTING_PATH}?{params}"


def _slug_para_marca(slug: str) -> str:
    """Converte slug de URL (ex: 'volkswagen') para nome canônico ('VOLKSWAGEN')."""
    return _SLUG_PARA_MARCA.get(slug.lower(), slug.upper().replace("-", " "))


def _extrair_ano_do_slug(slug: str) -> Optional[int]:
    """
    Extrai o ano de fabricação do slug final da URL.

    Padrão: {titulo-slug}-{ano_fab}-{ano_mod}-{id}
    Ex: 'vw-fusca-cabriole-1500-1979-1979-443' → 1979

    Estratégia: pegar o primeiro número de 4 dígitos no intervalo 1900-2026.
    """
    numeros = re.findall(r"\d{4}", slug)
    for n in numeros:
        v = int(n)
        if 1900 <= v <= 2026:
            return v
    return None
