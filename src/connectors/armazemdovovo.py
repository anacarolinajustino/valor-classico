"""
Conector Armazém do Vovô.
Site: https://armazemdovovo.com.br
Motor: custom (jQuery, server-rendered) — não é WooCommerce nem SPA.

Estratégia: página de listagem única em /anuncios traz todos os anúncios
ativos (21 em 2026-07-09, sem paginação real — o link "próxima página"
aponta pra si mesmo quando só há 1 página). Cada card já expõe marca,
modelo, preço e ano diretamente no HTML da listagem — sem precisar de
página de detalhe.

Nota histórica: este conector foi criado como stub em 2026-06-23 (só
levantava ConnectionError) porque testes anteriores bateram 403 do
Cloudflare. Reverificado em 2026-07-09: o site responde 200 normalmente
a requisições simples via `requests` (sem proxy) — implementado do zero.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.pipeline.normalizer import normalizar_preco, normalizar_texto, separar_marca_modelo_versao_obs
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "armazemdovovo"
BASE_URL = "https://armazemdovovo.com.br"
LISTING_PATH = "/anuncios"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0


def coletar_completo(max_paginas: int = 50) -> tuple[list[Anuncio], dict]:
    """Coleta os anúncios ativos do Armazém do Vovô (página única de listagem)."""
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()

    html = _requisitar(sessao, f"{BASE_URL}{LISTING_PATH}")
    anuncios = _parsear(html, data_coleta) if html else []

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "anuncios_validos": len(anuncios),
        "erros_listagem": 0 if html else 1,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[armazemdovovo] coleta completa: %s", metricas)
    return anuncios, metricas


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)

    html = _requisitar(sessao, f"{BASE_URL}{LISTING_PATH}")
    if not html:
        return []

    anuncios = []
    for a in _parsear(html, data_coleta):
        titulo_norm = normalizar_texto(a.titulo)
        if modelo_norm and modelo_norm not in titulo_norm:
            continue
        if marca_norm and a.marca and normalizar_texto(a.marca) != marca_norm and marca_norm not in titulo_norm:
            continue
        anuncios.append(a)

    logger.info("[armazemdovovo] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """Ponto de entrada público para testes de regressão com snapshot."""
    return _parsear(html, data_coleta)


def _parsear(html: str, data_coleta: str) -> list[Anuncio]:
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []

    for card in soup.select("a.st-card__link"):
        badge = card.select_one(".st-card__badge")
        if badge and "vendid" in badge.get_text(strip=True).lower():
            continue  # já vendido — ignora individualmente, não a fonte inteira

        marca_tag = card.select_one(".st-card__brand")
        modelo_tag = card.select_one(".st-card__model")
        marca = marca_tag.get_text(strip=True).upper() if marca_tag else ""
        modelo = modelo_tag.get_text(strip=True).upper() if modelo_tag else ""
        if not modelo:
            continue

        # Marca/modelo vêm de tags HTML dedicadas (estruturado) — passa pelo
        # catálogo antes de gravar, como toda fonte estruturada (ver separar_marca_modelo_versao_obs).
        marca, modelo, versao, obs = separar_marca_modelo_versao_obs(marca, modelo)

        valor_txt = _spec_valor(card, "Valor")
        preco = normalizar_preco(valor_txt) if valor_txt else None
        if not preco or preco <= 0:
            continue

        ano_txt = _spec_valor(card, "Ano")
        ano: Optional[int] = None
        if ano_txt and ano_txt.strip().isdigit():
            ano = int(ano_txt.strip())

        href = card.get("href", "")
        url_anuncio = f"{BASE_URL}/{href.lstrip('/')}" if href and not href.startswith("http") else href

        titulo = f"{marca} {modelo}".strip()

        anuncios.append(Anuncio(
            titulo=titulo, preco=preco, marca=marca, modelo=modelo,
            ano=ano, versao=versao, obs=obs, url=url_anuncio, fonte=FONTE,
            data_coleta=data_coleta,
        ))

    return anuncios


def _spec_valor(card, label: str) -> Optional[str]:
    """Extrai o valor de uma linha `.st-card__spec-row` pelo texto do label (Valor/Ano/KM)."""
    for row in card.select(".st-card__spec-row"):
        label_tag = row.select_one(".st-card__spec-label")
        if label_tag and label_tag.get_text(strip=True) == label:
            value_tag = row.select_one(".st-card__spec-value")
            return value_tag.get_text(strip=True) if value_tag else None
    return None


def _criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
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
            logger.warning("[armazemdovovo] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
