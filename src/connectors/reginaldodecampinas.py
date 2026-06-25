"""
Conector Reginaldo de Campinas.
Site: https://reginaldodecampinas.com.br
Motor: WooCommerce

Estratégia em dois passos:
  1. WP REST API (/wp-json/wp/v2/product?product_cat=61) para listar URLs dos
     veículos à venda sem precisar scraping da página de listagem HTML — mais
     robusto contra bot-detection em IPs de datacenter (Render/Frankfurt).
  2. Para cada URL, buscar preço e status na página de detalhe.

Página de detalhe (tema customizado):
  <span>DISPONÍVEL | VENDIDO | RESERVADO</span>
  <h2>R$ 98.000,00</h2>

Os títulos incluem km e texto extra após o ano — são limpos por _limpar_titulo()
antes de passar para inferir_marca_modelo_ano. Marcas populares brasileiras
(FUSCA, KOMBI, etc.) são normalizadas para os nomes oficiais via _MARCA_ALIAS.
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
# WP REST API — categoria "Veículos à Venda" (ID 61), não requer autenticação
API_URL = f"{BASE_URL}/wp-json/wp/v2/product"
CAT_VENDA_ID = 61
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Apelidos populares brasileiros → marca oficial
_MARCA_ALIAS: dict[str, str] = {
    "FUSCA":    "VOLKSWAGEN",
    "KOMBI":    "VOLKSWAGEN",
    "SAVEIRO":  "VOLKSWAGEN",
    "GOL":      "VOLKSWAGEN",
    "PARATI":   "VOLKSWAGEN",
    "VOYAGE":   "VOLKSWAGEN",
    "BRASILIA":  "VOLKSWAGEN",
    "CORCEL":   "FORD",
    "ESCORT":   "FORD",
    "MAVERICK": "FORD",
    "PAMPA":    "FORD",
    "OPALA":    "CHEVROLET",
    "CARAVAN":  "CHEVROLET",
    "MONZA":    "CHEVROLET",
    "KADETT":   "CHEVROLET",
    "VECTRA":   "CHEVROLET",
    "MOTO":     None,   # genérico demais — descarta
}

# Remove km/milhas e o que vem depois (inclui espaço não-quebrável e chars especiais)
_KM_PAT = re.compile(
    r'[\s\xa0\W]*\d{1,3}(?:[.,]\d{3})*[\s\xa0.,]*(?:km|milhas|mil[\s\xa0]*km|kms)\b.*$',
    re.IGNORECASE,
)
# Remove sufixos decorativos após o ano
_SUFFIX_PAT = re.compile(
    r'[\s\xa0]+(?:RARIDADE|RARIDADE\s+ABSOLUTA|NOVISSIMO|NOVÍSSIMO|EM\s+BREVE|PROJETO|'
    r'PARA\s+IMPORTA[ÇC][ÃA]O|PLACA\s+PRETA|NA\s+NOTA\s+FISCAL|7LUGARES)\b.*$',
    re.IGNORECASE,
)


def _limpar_titulo(titulo: str) -> str:
    """Remove km, sufixos desnecessários e aplica alias de marca.
    Descarta títulos com R$ (indicam anúncios que não são veículos)."""
    if "R$" in titulo or "R&#" in titulo:
        return ""
    t = _KM_PAT.sub("", titulo).strip()
    t = _SUFFIX_PAT.sub("", t).strip()
    # Aplica alias: prepend marca oficial mas mantém apelido no modelo
    # "FUSCA 1985" → "VOLKSWAGEN FUSCA 1985" (marca=VW, modelo=FUSCA)
    partes = t.split(None, 1)
    if partes:
        primeiro = partes[0].upper()
        if primeiro in _MARCA_ALIAS:
            alias = _MARCA_ALIAS[primeiro]
            if alias is None:
                return ""   # marca genérica demais, descarta
            t = f"{alias} {t}"  # prepend
    return t.strip()


def coletar_completo(max_paginas: int = 50) -> tuple[list[Anuncio], dict]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    erros_detalhe = 0

    # Obtém URLs via WP REST API — evita scraping da listagem HTML que pode ser
    # bloqueado por bot-detection em IPs de datacenter (ex.: Render/Frankfurt).
    candidatos = _obter_urls_api(sessao)
    if not candidatos:
        logger.warning("[reginaldodecampinas] API retornou 0 candidatos")
        erros = 1

    logger.info("[reginaldodecampinas] %d candidatos via API", len(candidatos))

    for prod_url, titulo in candidatos:
        if prod_url in seen:
            continue
        seen.add(prod_url)

        time.sleep(RATE_LIMIT)
        detalhe_html = _requisitar(sessao, prod_url)
        if detalhe_html is None:
            erros_detalhe += 1
            continue

        status = _extrair_status_detalhe(detalhe_html)
        if status and "DISPONÍVEL" not in status:
            continue

        preco = _extrair_preco_detalhe(detalhe_html)
        if not preco or preco <= 0:
            continue

        titulo_limpo = _limpar_titulo(titulo)
        if not titulo_limpo:
            continue
        marca, modelo, ano = inferir_marca_modelo_ano(titulo_limpo)
        if not modelo:
            continue

        anuncios.append(Anuncio(
            titulo=titulo_limpo, preco=preco, marca=marca, modelo=modelo,
            ano=ano, versao=None, url=prod_url, fonte=FONTE,
            data_coleta=data_coleta,
        ))

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": 1 if candidatos else 0,
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

    for prod_url, titulo in _obter_urls_api(sessao):
        if prod_url in seen:
            continue
        titulo_limpo = _limpar_titulo(titulo)
        if not titulo_limpo:
            continue
        t = normalizar_texto(titulo_limpo)
        if modelo_norm and modelo_norm not in t:
            continue
        if marca_norm and marca_norm not in t:
            continue

        seen.add(prod_url)
        time.sleep(RATE_LIMIT)
        detalhe_html = _requisitar(sessao, prod_url)
        if detalhe_html is None:
            continue

        status = _extrair_status_detalhe(detalhe_html)
        if status and "DISPONÍVEL" not in status:
            continue

        preco = _extrair_preco_detalhe(detalhe_html)
        if not preco or preco <= 0:
            continue

        m_inf, mo_inf, ano = inferir_marca_modelo_ano(titulo_limpo)
        if not mo_inf:
            continue
        anuncios.append(Anuncio(
            titulo=titulo_limpo, preco=preco, marca=m_inf, modelo=mo_inf,
            ano=ano, versao=None, url=prod_url, fonte=FONTE,
            data_coleta=data_coleta,
        ))

    logger.info("[reginaldodecampinas] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """Compatibilidade: retorna itens sem preço (preço requer detalhe individual)."""
    anuncios = []
    for url, titulo in _parsear_listagem_urls(html):
        titulo_limpo = _limpar_titulo(titulo)
        if not titulo_limpo:
            continue
        marca, modelo, ano = inferir_marca_modelo_ano(titulo_limpo)
        if not modelo:
            continue
        anuncios.append(Anuncio(
            titulo=titulo_limpo, preco=None, marca=marca, modelo=modelo,
            ano=ano, versao=None, url=url, fonte=FONTE, data_coleta=data_coleta,
        ))
    return anuncios


# ── Helpers internos ──────────────────────────────────────────────────────────

def _obter_urls_api(sessao: requests.Session) -> list[tuple[str, str]]:
    """
    Obtém [(url, titulo)] de veículos via WP REST API.
    Mais robusto que scraping HTML para IPs de datacenter.
    """
    resultados: list[tuple[str, str]] = []
    pagina = 1
    while True:
        params = {
            "product_cat": CAT_VENDA_ID,
            "per_page": 100,
            "page": pagina,
            "_fields": "id,link,title",
        }
        try:
            r = sessao.get(API_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            items = r.json()
        except Exception as exc:
            logger.warning("[reginaldodecampinas] API erro pág %d: %s", pagina, exc)
            break
        if not items:
            break
        for item in items:
            url = item.get("link", "")
            titulo_raw = item.get("title", {}).get("rendered", "")
            titulo = re.sub(r"&#\d+;|&[a-z]+;", "", titulo_raw).strip()
            if url and titulo:
                resultados.append((url, titulo))
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        if pagina >= total_pages:
            break
        pagina += 1
    return resultados


def _extrair_status_detalhe(html: str) -> str:
    """Extrai badge de disponibilidade da página de detalhe (DISPONÍVEL/VENDIDO/etc.)."""
    soup = BeautifulSoup(html, "lxml")
    for span in soup.find_all("span"):
        t = span.get_text(strip=True).upper()
        if t in ("DISPONÍVEL", "VENDIDO", "RESERVADO", "EM BREVE"):
            return t
    return ""


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
