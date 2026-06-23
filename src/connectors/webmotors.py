"""
Conector Webmotors.
Site: https://www.webmotors.com.br
Motor: API interna JSON (endpoint /api/search/car)
Estratégia: requests contra a API interna do site, sem autenticação.
             Filtra por anoate=2000 para focar em carros clássicos.

Parâmetros principais:
  tipoveiculo  = "carros"
  pagina       = 1, 2, 3 … (base-1)
  quantidade   = 24 (resultados por página)
  anoate       = 2000 (ano até — filtra clássicos)
  marca        = ex. "VOLKSWAGEN"
  modelo       = ex. "FUSCA"
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

FONTE = "webmotors"
API_URL = "https://www.webmotors.com.br/api/search/car"
SITE_BASE = "https://www.webmotors.com.br"
ANO_MAXIMO_CLASSICO = 2000
QUANTIDADE_POR_PAGINA = 24
# UA do app mobile Android — contorna PerimeterX que bloqueia browsers headless
USER_AGENT = "com.webmotors.app/5.0 (Android 13; Pixel 6)"
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.5


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """Busca por marca+modelo no Webmotors, limitado a carros clássicos (≤2000)."""
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for pg in range(1, paginas + 1):
        params = _params_base(pg)
        if marca:
            params["marca"] = marca.upper()
        if modelo:
            params["modelo"] = modelo.upper()

        dados = _requisitar(sessao, params)
        if dados is None:
            break

        items = _extrair_listings(dados)
        if not items:
            break

        for a in _parsear(items, data_coleta):
            if a.url in seen:
                continue
            titulo_norm = normalizar_texto(a.titulo)
            if modelo_norm and modelo_norm not in titulo_norm:
                continue
            if marca_norm and a.marca and normalizar_texto(a.marca) != marca_norm and marca_norm not in titulo_norm:
                continue
            seen.add(a.url)
            anuncios.append(a)

        if not _tem_proxima(dados, pg):
            break
        time.sleep(RATE_LIMIT)

    logger.info("[webmotors] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    """Coleta todos os anúncios de carros clássicos (≤ %d)."""
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0

    for pg in range(1, max_paginas + 1):
        dados = _requisitar(sessao, _params_base(pg))
        if dados is None:
            erros += 1
            break

        items = _extrair_listings(dados)
        if not items:
            break

        paginas_ok += 1
        for a in _parsear(items, data_coleta):
            if a.url not in seen:
                seen.add(a.url)
                anuncios.append(a)

        if not _tem_proxima(dados, pg):
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
    logger.info("[webmotors] coleta completa: %s", metricas)
    return anuncios, metricas


# ── Helpers internos ───────────────────────────────────────────────────────────

def _params_base(pagina: int) -> dict:
    return {
        "tipoveiculo": "carros",
        "pagina": pagina,
        "quantidade": QUANTIDADE_POR_PAGINA,
        "anoate": ANO_MAXIMO_CLASSICO,
        "order": 1,  # relevância
    }


def _extrair_listings(dados: dict) -> list[dict]:
    """Extrai a lista de anúncios da resposta JSON."""
    # Webmotors pode retornar em 'SearchResults' ou 'results' ou lista direta
    if isinstance(dados, list):
        return dados
    for chave in ("SearchResults", "results", "data", "items", "listings"):
        if chave in dados and isinstance(dados[chave], list):
            return dados[chave]
    return []


def _tem_proxima(dados: dict, pagina_atual: int) -> bool:
    """Verifica se há próxima página na resposta."""
    total_paginas = (
        dados.get("TotalPages")
        or dados.get("total_pages")
        or dados.get("totalPages")
    )
    if total_paginas is not None:
        return pagina_atual < int(total_paginas)
    total_count = dados.get("TotalCount") or dados.get("total") or 0
    return pagina_atual * QUANTIDADE_POR_PAGINA < int(total_count)


def _parsear(items: list[dict], data_coleta: str) -> list[Anuncio]:
    anuncios: list[Anuncio] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        # Título e campos — Webmotors aninha em Specification ou direto
        spec = item.get("Specification") or item
        make_obj  = spec.get("Make")  or {}
        model_obj = spec.get("Model") or {}

        marca  = (make_obj.get("Value")  if isinstance(make_obj, dict)  else make_obj  or "").upper()
        modelo = (model_obj.get("Value") if isinstance(model_obj, dict) else model_obj or "").upper()

        if not marca:
            marca = (item.get("make") or item.get("marca") or "").upper()
        if not modelo:
            modelo = (item.get("model") or item.get("modelo") or "").upper()

        versao = None
        ver_obj = spec.get("Version") or {}
        if isinstance(ver_obj, dict):
            versao = ver_obj.get("Value") or None
        elif isinstance(ver_obj, str):
            versao = ver_obj or None

        # Ano
        ano = (
            spec.get("YearModel")
            or spec.get("YearFabrication")
            or item.get("year_model")
            or item.get("year_fabrication")
            or item.get("ano")
        )
        try:
            ano = int(ano) if ano else None
        except (ValueError, TypeError):
            ano = None

        # Filtra apenas clássicos
        if ano and ano > ANO_MAXIMO_CLASSICO:
            continue

        # Preço
        prices = item.get("Prices") or item
        preco_raw = (
            prices.get("Price")
            or prices.get("price")
            or item.get("preco")
            or item.get("valor")
        )
        preco: Optional[float] = None
        if isinstance(preco_raw, (int, float)):
            preco = float(preco_raw)
        elif isinstance(preco_raw, str):
            preco = normalizar_preco(preco_raw)
        if not preco or preco <= 0:
            continue

        # URL
        uid = item.get("UniqueId") or item.get("id") or item.get("unique_id") or ""
        slug = item.get("Path") or item.get("path") or item.get("slug") or ""
        if slug:
            url_anuncio = SITE_BASE + ("/" if not slug.startswith("/") else "") + slug
        elif uid:
            url_anuncio = f"{SITE_BASE}/comprar/{uid}"
        else:
            url_anuncio = SITE_BASE

        # Título sintético
        partes = [p for p in [marca, modelo, versao, str(ano) if ano else ""] if p]
        titulo = " ".join(partes) if partes else f"{marca} {modelo}".strip()

        if not modelo:
            continue

        anuncios.append(Anuncio(
            titulo=titulo,
            preco=preco,
            marca=marca,
            modelo=modelo,
            ano=ano,
            versao=versao,
            url=url_anuncio,
            fonte=FONTE,
            data_coleta=data_coleta,
        ))
    return anuncios


def _criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    return s


def _requisitar(sessao: requests.Session, params: dict) -> Optional[dict]:
    for i in range(1, MAX_RETRIES + 1):
        try:
            r = sessao.get(API_URL, params=params, timeout=TIMEOUT)
            if r.status_code == 403:
                logger.warning("[webmotors] bloqueado por PerimeterX (403)")
                return None
            r.raise_for_status()
            data = r.json()
            # PerimeterX retorna 200 com JSON de challenge quando bloqueia
            if isinstance(data, dict) and "appId" in data and "jsClientSrc" in data:
                logger.warning("[webmotors] resposta é challenge PerimeterX, não dados")
                return None
            return data
        except requests.RequestException as exc:
            logger.warning("[webmotors] tentativa %d/%d: %s", i, MAX_RETRIES, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
        except ValueError as exc:
            logger.warning("[webmotors] JSON inválido: %s", exc)
            return None
    return None
