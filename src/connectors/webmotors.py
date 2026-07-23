"""
Conector Webmotors.
Site: https://www.webmotors.com.br
Motor: API interna JSON (endpoint /api/search/car)
Estratégia: requests contra a API interna do site, sem autenticação.
             O filtro de ano até 2000 (clássicos) é passado via a URL amigável
             do site no parâmetro `url` — os parâmetros soltos de ano da API
             (yearEnd/yearTo/…) são ignorados pelo backend.

Parâmetros que a API realmente respeita:
  url            = URL amigável do site já com o filtro (…/estoque/ate.2000?…)
  actualPage     = 1, 2, 3 … (base-1)
  displayPerPage = 24 (resultados por página)
  showCount      = "true" (necessário para vir Pagination.PageTotal preenchido)

Observações descobertas na auditoria (2026-07-23):
  - Os nomes antigos (`pagina`, `quantidade`, `anoate`) eram ignorados: a API
    devolvia sempre a página 1 sem filtro de ano.
  - Sem `url`, o filtro de ano não é aplicado (vinham carros 2024/2025/2026).
  - O total real (≤2000) é ~212 páginas ≈ 5.070 anúncios.

Anti-bot (PerimeterX): o bloqueio é reputacional por IP — um IP "fresco" passa
~185 páginas antes do primeiro 403 e, uma vez marcado, é bloqueado
agressivamente por horas. Solução: rotear cada requisição por um IP residencial
DIFERENTE do pool DataImpulse (novo `sessid` a cada `requests_proxies()`), já
que a listagem é stateless. Assim nenhum IP acumula tráfego suficiente para ser
marcado. Sem as env vars DATAIMPULSE_* o conector conecta direto (degrada para
o comportamento antigo, que satura o IP após ~185 páginas). Custo medido:
~73 KB/página → coleta completa ~15 MB ≈ US$0,015 a US$1/GB.
"""
from __future__ import annotations

import logging
import os
import re
import time
import unicodedata
from datetime import date
from typing import Optional

import requests

from src.connectors._browser import proxy_configurado, requests_proxies
from src.pipeline.normalizer import normalizar_preco, normalizar_texto, separar_marca_modelo_versao_obs
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "webmotors"
API_URL = "https://www.webmotors.com.br/api/search/car"
SITE_BASE = "https://www.webmotors.com.br"
ANO_MAXIMO_CLASSICO = 2000
# URL amigável do site que carrega o filtro "até 2000" no backend da API.
FILTRO_URL = (
    f"{SITE_BASE}/carros/estoque/ate.{ANO_MAXIMO_CLASSICO}"
    f"?tipoveiculo=carros&anoate={ANO_MAXIMO_CLASSICO}"
)
QUANTIDADE_POR_PAGINA = 24
# UA do app mobile Android — contorna PerimeterX que bloqueia browsers headless
USER_AGENT = "com.webmotors.app/5.0 (Android 13; Pixel 6)"
TIMEOUT = 40  # proxy residencial é mais lento que conexão direta
MAX_RETRIES = 4  # cada tentativa sai de um IP diferente, então retentar tem valor real
BACKOFF = 2.0
RATE_LIMIT = 1.0
# Resiliência ao 403 do PerimeterX durante a coleta completa. Com IP rotativo um
# 403 é raro (IP do pool que já estava marcado) e a retentativa já pega outro IP,
# então a pausa é curta — não precisamos "esperar o IP esfriar" como sem proxy.
PAUSA_APOS_BLOQUEIO = 5.0    # segundos-base; cresce a cada falha seguida
MAX_FALHAS_SEGUIDAS = 6      # após N páginas seguidas sem resposta, desiste


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """Busca por marca+modelo no Webmotors, limitado a carros clássicos (≤2000).

    A API não filtra por marca/modelo de forma confiável, então varremos a
    listagem de clássicos e filtramos localmente pelo título.
    """
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for pg in range(1, paginas + 1):
        dados = _requisitar(sessao, _params_base(pg))
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


def coletar_completo(max_paginas: int = 300) -> tuple[list[Anuncio], dict]:
    """Coleta todos os anúncios de carros clássicos (≤ 2000)."""
    sessao = _criar_sessao()
    if proxy_configurado():
        logger.info("[webmotors] usando proxy residencial DataImpulse (IP rotativo por requisição)")
    else:
        logger.warning(
            "[webmotors] DATAIMPULSE_* não configurado — conectando direto; o "
            "PerimeterX satura o IP após ~185 páginas e bloqueia o resto"
        )
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0
    falhas_seguidas = 0

    pg = 1
    while pg <= max_paginas:
        dados = _requisitar(sessao, _params_base(pg))
        if dados is None:
            # 403 do PerimeterX é intermitente: não aborta a coleta inteira.
            # Pausa (progressiva) e tenta a MESMA página de novo; só desiste
            # após MAX_FALHAS_SEGUIDAS páginas seguidas sem resposta.
            erros += 1
            falhas_seguidas += 1
            if falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                logger.warning("[webmotors] %d falhas seguidas na pág %d, encerrando", falhas_seguidas, pg)
                break
            espera = PAUSA_APOS_BLOQUEIO * falhas_seguidas
            logger.warning("[webmotors] sem resposta na pág %d, aguardando %.0fs e retentando", pg, espera)
            time.sleep(espera)
            continue

        falhas_seguidas = 0
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
        pg += 1
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
        "url": FILTRO_URL,
        "actualPage": pagina,
        "displayPerPage": QUANTIDADE_POR_PAGINA,
        "showCount": "true",
        "order": 1,  # relevância
    }


def _extrair_listings(dados: dict) -> list[dict]:
    """Extrai a lista de anúncios da resposta JSON."""
    if isinstance(dados, list):
        return dados
    for chave in ("SearchResults", "results", "data", "items", "listings"):
        if chave in dados and isinstance(dados[chave], list):
            return dados[chave]
    return []


def _tem_proxima(dados: dict, pagina_atual: int) -> bool:
    """Verifica se há próxima página na resposta (Pagination.PageTotal)."""
    pag = dados.get("Pagination") or {}
    total_paginas = pag.get("PageTotal") or pag.get("pageTotal")
    if total_paginas:
        return pagina_atual < int(total_paginas)
    # Sem contagem confiável: continua enquanto a página vier cheia.
    items = _extrair_listings(dados)
    return len(items) >= QUANTIDADE_POR_PAGINA


def _slug_do_photopath(item: dict) -> str:
    """Extrai o slug oficial do anúncio do caminho das fotos.

    Ex.: '…/fiat-uno-1.0-mille-eletronic-8v-gasolina-4p-manual-wmimagem10095…jpg'
         → 'fiat-uno-1.0-mille-eletronic-8v-gasolina-4p-manual'
    """
    media = item.get("Media") or {}
    fotos = media.get("Photos") or []
    caminho = ""
    if fotos and isinstance(fotos[0], dict):
        caminho = fotos[0].get("PhotoPath") or ""
    if not caminho:
        caminho = item.get("PhotoPath") or ""
    if not caminho:
        return ""
    nome = os.path.basename(caminho.replace("\\", "/"))
    slug = re.split(r"-?wmimagem", nome, maxsplit=1, flags=re.IGNORECASE)[0]
    slug = slug.strip("-")
    # Formatos legados vêm colados e/ou com a extensão da imagem: rejeita para
    # cair no slug derivado do título (limpo e consistente).
    if "." in slug or "-" not in slug:
        return ""
    return slug


def _slugificar(texto: str) -> str:
    """Fallback: gera um slug a partir de um texto livre (ex.: título)."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return t.strip("-")


def _montar_url(item: dict, titulo: str) -> str:
    """Monta a URL do anúncio: /comprar/{slug}/{UniqueId}."""
    uid = item.get("UniqueId") or item.get("id") or item.get("unique_id") or ""
    slug = _slug_do_photopath(item) or _slugificar(titulo)
    if slug and uid:
        return f"{SITE_BASE}/comprar/{slug}/{uid}"
    if uid:
        return f"{SITE_BASE}/comprar/{uid}"
    return SITE_BASE


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

        # Campo estruturado da API passa pelo catálogo antes de gravar, como
        # toda fonte de marca/modelo estruturada (ver separar_marca_modelo_versao_obs).
        marca, modelo, versao_modelo, obs = separar_marca_modelo_versao_obs(marca, modelo)

        # A API tem campo "Version" próprio (mais confiável que o que sobra
        # ao separar o "Model") — só cai pro derivado do modelo na ausência.
        versao = None
        ver_obj = spec.get("Version") or {}
        if isinstance(ver_obj, dict):
            versao = ver_obj.get("Value") or None
        elif isinstance(ver_obj, str):
            versao = ver_obj or None
        versao = versao or versao_modelo

        # Ano
        ano = (
            spec.get("YearModel")
            or spec.get("YearFabrication")
            or item.get("year_model")
            or item.get("year_fabrication")
            or item.get("ano")
        )
        try:
            ano = int(float(ano)) if ano else None
        except (ValueError, TypeError):
            ano = None

        # Salvaguarda: mesmo com o filtro na URL, descarta qualquer ano > 2000.
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

        # Título sintético
        partes = [p for p in [marca, modelo, versao, str(ano) if ano else ""] if p]
        titulo = " ".join(partes) if partes else f"{marca} {modelo}".strip()

        if not modelo:
            continue

        url_anuncio = _montar_url(item, titulo)

        anuncios.append(Anuncio(
            titulo=titulo,
            preco=preco,
            marca=marca,
            modelo=modelo,
            ano=ano,
            versao=versao,
            obs=obs,
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
        # IP residencial novo a cada tentativa (novo sessid do pool DataImpulse).
        # Se o proxy não estiver configurado, requests_proxies() devolve None e a
        # requisição sai direto — degradando para o comportamento antigo.
        proxies = requests_proxies()
        try:
            r = sessao.get(API_URL, params=params, proxies=proxies, timeout=TIMEOUT)
            if r.status_code == 403:
                # IP marcado pelo PerimeterX: a próxima tentativa sai de outro IP.
                logger.warning("[webmotors] 403 do PerimeterX (tentativa %d/%d) — trocando de IP", i, MAX_RETRIES)
                if i < MAX_RETRIES:
                    time.sleep(BACKOFF)
                continue
            r.raise_for_status()
            data = r.json()
            # PerimeterX retorna 200 com JSON de challenge quando bloqueia
            if isinstance(data, dict) and "appId" in data and "jsClientSrc" in data:
                logger.warning("[webmotors] challenge PerimeterX (tentativa %d/%d) — trocando de IP", i, MAX_RETRIES)
                if i < MAX_RETRIES:
                    time.sleep(BACKOFF)
                continue
            return data
        except requests.RequestException as exc:
            logger.warning("[webmotors] tentativa %d/%d: %s", i, MAX_RETRIES, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
        except ValueError as exc:
            # Corpo não-JSON costuma ser página de challenge — tenta outro IP.
            logger.warning("[webmotors] JSON inválido (tentativa %d/%d): %s", i, MAX_RETRIES, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
