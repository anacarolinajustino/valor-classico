"""
Conector SoCarrão.
Site: https://www.socarrao.com.br
Motor: React SPA com API REST própria (sc-api-prod.socarrao.com.br)
Estratégia: chama a API JSON diretamente via requests, sem precisar de Playwright.
Endpoint inferido: GET /api/v1/vehicles?page=N&category=classic (ajuste conforme necessário)
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Optional

import requests

from src.pipeline.normalizer import normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "socarrao"
API_BASE = "https://sc-api-prod.socarrao.com.br"
# Endpoint de busca — pode precisar de ajuste caso a API mude
ENDPOINT = "/api/v1/vehicles"
SITE_BASE = "https://www.socarrao.com.br"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.5


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for pg in range(1, paginas + 1):
        params: dict = {"page": pg, "q": modelo or marca}
        dados = _requisitar_api(sessao, params)
        if dados is None:
            break
        for a in _parsear(dados, data_coleta):
            if a.url in seen:
                continue
            titulo_norm = normalizar_texto(a.titulo)
            if modelo_norm and modelo_norm not in titulo_norm:
                continue
            if marca_norm and a.marca and normalizar_texto(a.marca) != marca_norm and marca_norm not in titulo_norm:
                continue
            seen.add(a.url)
            anuncios.append(a)
        time.sleep(RATE_LIMIT)

    logger.info("[socarrao] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0

    for pg in range(1, max_paginas + 1):
        params: dict = {"page": pg}
        dados = _requisitar_api(sessao, params)
        if dados is None:
            erros += 1
            break

        items = _parsear(dados, data_coleta)
        if not items:
            break

        paginas_ok += 1
        for a in items:
            if a.url not in seen:
                seen.add(a.url)
                anuncios.append(a)

        # Para paginação da API: verifica se há próxima página
        if not _tem_proxima_api(dados):
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
    logger.info("[socarrao] coleta completa: %s", metricas)
    return anuncios, metricas


def _parsear(dados: dict | list, data_coleta: str) -> list[Anuncio]:
    """Parseia resposta JSON da API do SoCarrão."""
    anuncios: list[Anuncio] = []

    # A resposta pode ser {"data": [...]} ou diretamente uma lista
    if isinstance(dados, dict):
        items = dados.get("data") or dados.get("vehicles") or dados.get("items") or []
    else:
        items = dados

    for item in items:
        if not isinstance(item, dict):
            continue

        marca = (item.get("brand") or item.get("marca") or "").upper()
        modelo = (item.get("model") or item.get("modelo") or "").upper()
        ano_raw = item.get("year") or item.get("ano")
        try:
            ano = int(ano_raw) if ano_raw else None
        except (ValueError, TypeError):
            ano = None

        titulo = item.get("title") or item.get("titulo") or f"{marca} {modelo} {ano or ''}".strip()
        if not titulo or not modelo:
            continue

        preco_raw = item.get("price") or item.get("preco") or item.get("valor")
        preco = None
        if isinstance(preco_raw, (int, float)):
            preco = float(preco_raw)
        elif isinstance(preco_raw, str):
            preco = normalizar_preco(preco_raw)
        if not preco or preco <= 0:
            continue

        slug = item.get("slug") or item.get("id") or ""
        url_anuncio = f"{SITE_BASE}/veiculo/{slug}" if slug else SITE_BASE

        anuncios.append(Anuncio(
            titulo=titulo, preco=preco, marca=marca, modelo=modelo,
            ano=ano, versao=None, url=url_anuncio, fonte=FONTE,
            data_coleta=data_coleta,
        ))
    return anuncios


def _tem_proxima_api(dados: dict | list) -> bool:
    if isinstance(dados, dict):
        meta = dados.get("meta") or dados.get("pagination") or {}
        current = meta.get("current_page", 1)
        last = meta.get("last_page") or meta.get("total_pages")
        if last:
            return current < last
        return bool(dados.get("next_page_url") or dados.get("next"))
    return False


def _criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Origin": SITE_BASE,
        "Referer": SITE_BASE + "/",
    })
    return s


def _requisitar_api(sessao: requests.Session, params: dict) -> Optional[dict | list]:
    url = API_BASE + ENDPOINT
    for i in range(1, MAX_RETRIES + 1):
        try:
            r = sessao.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            logger.warning("[socarrao] tentativa %d/%d: %s", i, MAX_RETRIES, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
        except ValueError as exc:
            logger.warning("[socarrao] JSON inválido: %s", exc)
            return None
    return None
