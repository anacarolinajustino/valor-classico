"""
Conector Super Antigo — coleta anúncios de veículos clássicos.

Site: https://superantigo.com.br
Motor: Vite + React SPA
Estratégia: requests direto via query params de paginação.
  URL: /veiculos?showAllTypes=true&page=N&limit=24&sort=newest
  A resposta pode ser JSON (API REST) ou HTML com dados renderizados.
  _parsear_resposta() tenta JSON primeiro; fallback para parsear_listagem_html().

Compliance (verificado 2026-06-24):
- robots.txt: Allow: /veiculos/ ✅
- Rate limit: 1s entre páginas

Separação de responsabilidades:
- coletar_completo()    → I/O (requests), paginação completa
- buscar()              → I/O (requests), filtro por marca/modelo
- parsear_listagem_html() → função pura (BS4), usada nos testes de snapshot
- _parsear_resposta()   → tenta JSON, cai para HTML
- _parsear_json()       → parser JSON com detecção de estrutura
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.pipeline.normalizer import inferir_marca_modelo_ano, normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "superantigo"
BASE_URL = "https://www.superantigo.com.br"
LISTING_BASE = "https://superantigo.com.br"
LISTING_PATH = "/veiculos"
DEFAULT_LIMIT = 24
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

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
    Coleta TODOS os anúncios do Super Antigo via paginação por query params.
    URL: /veiculos?showAllTypes=true&page=N&limit=24&sort=newest
    """
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen_urls: set[str] = set()
    paginas_ok = 0
    erros = 0

    for pagina in range(1, max_paginas + 1):
        url = _url_pagina(pagina)
        logger.info("[superantigo] página %d — %s", pagina, url)

        conteudo = _requisitar(sessao, url)
        if conteudo is None:
            erros += 1
            break

        itens = _parsear_resposta(conteudo, data_coleta)
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

        if len(itens) < DEFAULT_LIMIT:
            logger.info("[superantigo] página incompleta — última página (%d).", pagina)
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
    Coleta até `paginas` páginas e filtra os resultados por marca/modelo.
    """
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen_urls: set[str] = set()

    for pagina in range(1, paginas + 1):
        url = _url_pagina(pagina)
        conteudo = _requisitar(sessao, url)
        if conteudo is None:
            break

        itens = _parsear_resposta(conteudo, data_coleta)
        if not itens:
            break

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

        if len(itens) < DEFAULT_LIMIT:
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

        anuncios.append(
            Anuncio(
                titulo=titulo,
                preco=preco,
                marca=marca,
                modelo=modelo_raw,
                ano=ano,
                versao=None,
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


def _parsear_resposta(conteudo: str, data_coleta: str) -> list[Anuncio]:
    """Tenta JSON; fallback para HTML."""
    try:
        dados = json.loads(conteudo)
        itens = _parsear_json(dados, data_coleta)
        if itens:
            logger.debug("[superantigo] resposta JSON: %d itens", len(itens))
            return itens
    except (json.JSONDecodeError, TypeError):
        pass

    logger.debug("[superantigo] resposta HTML — usando parsear_listagem_html")
    return parsear_listagem_html(conteudo, data_coleta)


def _parsear_json(dados: object, data_coleta: str) -> list[Anuncio]:
    """
    Extrai anúncios de uma resposta JSON com detecção automática de estrutura.

    Suporta:
    - Lista direta: [{"title": ..., "price": ...}, ...]
    - Objeto com chave de lista: {"data": [...]} / {"vehicles": [...]} / etc.
    """
    veiculos: list[dict] = []

    if isinstance(dados, list):
        veiculos = dados
    elif isinstance(dados, dict):
        for chave in ("data", "vehicles", "items", "results", "ads", "veiculos", "listings"):
            if chave in dados and isinstance(dados[chave], list):
                veiculos = dados[chave]
                break
        if not veiculos:
            for v in dados.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    veiculos = v
                    break

    if not veiculos:
        return []

    anuncios: list[Anuncio] = []

    for v in veiculos:
        if not isinstance(v, dict):
            continue

        titulo = (v.get("title") or v.get("name") or v.get("titulo") or "").strip()

        preco_raw = (v.get("price") or v.get("preco") or v.get("valor")
                     or v.get("salePrice") or 0)
        if isinstance(preco_raw, (int, float)):
            preco = float(preco_raw) if preco_raw > 0 else None
        else:
            preco = normalizar_preco(str(preco_raw))

        if not preco or preco <= 0:
            continue

        # URL do anúncio
        url_anuncio = (v.get("url") or v.get("link") or v.get("permalink") or "").strip()
        slug = str(v.get("slug") or v.get("id") or "")
        if not url_anuncio and slug:
            brand_slug = normalizar_texto(v.get("brand") or v.get("marca") or "").replace(" ", "-")
            model_slug = normalizar_texto(v.get("model") or v.get("modelo") or "").replace(" ", "-")
            if brand_slug and model_slug:
                url_anuncio = f"{BASE_URL}/veiculos/carro/{brand_slug}/{model_slug}/{slug}"
            else:
                url_anuncio = f"{BASE_URL}/veiculos/{slug}"
        elif url_anuncio and not url_anuncio.startswith("http"):
            url_anuncio = BASE_URL + url_anuncio

        if not url_anuncio:
            continue

        marca = (v.get("brand") or v.get("marca") or "").strip()
        modelo_raw = (v.get("model") or v.get("modelo") or "").strip()

        ano_raw = (v.get("year") or v.get("fabricationYear") or v.get("ano")
                   or v.get("yearFabrication") or v.get("year_fabrication") or 0)
        try:
            ano = int(ano_raw) if ano_raw else None
        except (ValueError, TypeError):
            ano = None

        if not marca or not modelo_raw:
            m, mo, a = inferir_marca_modelo_ano(titulo)
            if not marca:
                marca = m
            if not modelo_raw:
                modelo_raw = mo
            if ano is None:
                ano = a

        if not modelo_raw:
            continue

        if not titulo:
            titulo = f"{marca} {modelo_raw} {ano or ''}".strip()

        anuncios.append(Anuncio(
            titulo=titulo,
            preco=preco,
            marca=marca.upper() if marca else "",
            modelo=modelo_raw.upper() if modelo_raw else "",
            ano=ano,
            versao=None,
            url=url_anuncio,
            fonte=FONTE,
            data_coleta=data_coleta,
        ))

    return anuncios


def _criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    return s


def _requisitar(sessao: requests.Session, url: str) -> Optional[str]:
    for i in range(1, MAX_RETRIES + 1):
        try:
            r = sessao.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return r.text
        except requests.RequestException as exc:
            logger.warning("[superantigo] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
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
