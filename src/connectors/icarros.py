"""
Conector iCarros.
Site: https://www.icarros.com.br
Motor: HTML server-rendered (JSP) com dados estruturados schema.org embutidos.
Estratégia: requests puro (sem browser/proxy — o site responde 200 a um
             User-Agent de navegador comum). A listagem embute um bloco
             `<script type="application/ld+json">` do tipo `ItemList` com 20
             anúncios por página, cada um com o TÍTULO completo (marca + modelo
             + versão + ano), a URL absoluta e o preço. O título é a fonte mais
             rica (mantém o trim, que pesa no preço), então é parseado via
             `inferir_marca_modelo_versao_obs_ano`, igual ao conector da OLX —
             melhor que os campos `brand`/`model` do bloco `Vehicle`, que trazem
             o modelo sem versão.

Filtro de ano: aplicado no servidor pela query `sop=...amf_2000...` (ano máximo
de fabricação 2000) — o mesmo filtro que a busca manual do site gera. Ainda
assim mantemos o corte de ano client-side como defesa em profundidade.

Paginação: parâmetro `&pag=N` (1-based). Cada página traz ~20 anúncios; a
listagem termina quando o `ItemList` vem vazio (medido 2026-07-23: ~17 páginas,
334 clássicos ≤2000).
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
import time
from datetime import date
from typing import Optional

import requests

from src.pipeline.normalizer import inferir_marca_modelo_versao_obs_ano, normalizar_preco
from src.pipeline.persistence import ANO_CORTE_CLASSICO
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "icarros"
SITE_BASE = "https://www.icarros.com.br"
# Listagem já filtrada por ano de fabricação até 2000 (sop=...amf_2000...),
# o mesmo filtro que a busca manual do site produz.
LISTA_URL = (
    "https://www.icarros.com.br/ache/listaanuncios.jsp"
    "?bid=1&sop=esc_4.1_-amf_2000.1_-.1_-"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TIMEOUT = 25
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.0

_LD_JSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """Varre a listagem de clássicos e filtra localmente por marca/modelo.

    A listagem do iCarros não tem filtro de marca/modelo por URL confiável, então
    coletamos as páginas e filtramos pelo título — igual ao conector da OLX.
    """
    from src.pipeline.normalizer import normalizar_texto

    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    todos = _coletar(max_paginas=paginas)[0]
    anuncios: list[Anuncio] = []
    for a in todos:
        titulo_norm = normalizar_texto(a.titulo)
        if modelo_norm and modelo_norm not in titulo_norm and modelo_norm not in normalizar_texto(a.modelo):
            continue
        if marca_norm and normalizar_texto(a.marca) != marca_norm and marca_norm not in titulo_norm:
            continue
        anuncios.append(a)
    logger.info("[icarros] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def coletar_completo(max_paginas: int = 60, ano_ate: int = ANO_CORTE_CLASSICO) -> tuple[list[Anuncio], dict]:
    """Coleta todos os anúncios de carros clássicos (≤ ano_ate)."""
    inicio = time.monotonic()
    anuncios, metricas = _coletar(max_paginas=max_paginas, ano_ate=ano_ate)
    metricas["tempo_total_s"] = round(time.monotonic() - inicio, 1)
    logger.info("[icarros] coleta completa: %s", metricas)
    return anuncios, metricas


# ── Helpers internos ───────────────────────────────────────────────────────────

def _coletar(max_paginas: int, ano_ate: int = ANO_CORTE_CLASSICO) -> tuple[list[Anuncio], dict]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    paginas_ok = 0
    erros = 0
    descartados = 0
    descartados_ano = 0

    for pg in range(1, max_paginas + 1):
        html = _requisitar(sessao, pg)
        if html is None:
            erros += 1
            break

        items = _extrair_itemlist(html)
        if not items:
            break

        paginas_ok += 1
        novos = 0
        for it in items:
            a, motivo = _parsear_item(it, data_coleta, ano_ate)
            if a is None:
                if motivo == "ano":
                    descartados_ano += 1
                else:
                    descartados += 1
                continue
            if a.url in seen:
                continue
            seen.add(a.url)
            anuncios.append(a)
            novos += 1

        logger.info("[icarros] pág %d: %d itens → %d novos (total: %d)", pg, len(items), novos, len(anuncios))

        # Fim da listagem: página sem nenhum anúncio novo (só patrocinados repetidos).
        if novos == 0:
            break
        time.sleep(RATE_LIMIT)

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_ok,
        "anuncios_validos": len(anuncios),
        "descartados_sem_preco_ou_modelo": descartados,
        "descartados_ano_fora_corte": descartados_ano,
        "erros_listagem": erros,
    }
    return anuncios, metricas


def _extrair_itemlist(html: str) -> list[dict]:
    """Extrai os itens do bloco ld+json do tipo ItemList (20 por página)."""
    for bloco in _LD_JSON_RE.findall(html):
        try:
            d = json.loads(bloco)
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict) and d.get("@type") == "ItemList":
            els = d.get("itemListElement") or []
            return [e.get("item") or {} for e in els if isinstance(e, dict)]
    return []


def _parsear_item(item: dict, data_coleta: str, ano_ate: int) -> tuple[Optional[Anuncio], Optional[str]]:
    """Converte um item do ItemList em Anuncio. Retorna (anuncio, motivo_descarte)."""
    if not isinstance(item, dict):
        return None, "vazio"

    titulo = _html.unescape((item.get("name") or "").strip())
    url = _html.unescape((item.get("url") or "").strip())
    if url and url.startswith("/"):
        url = SITE_BASE + url
    if not titulo or not url:
        return None, "vazio"

    # Preço: offers.price ("27900") ou o title não tem preço.
    offers = item.get("offers") or {}
    preco_raw = offers.get("price") if isinstance(offers, dict) else None
    preco: Optional[float] = None
    if isinstance(preco_raw, (int, float)):
        preco = float(preco_raw)
    elif isinstance(preco_raw, str):
        preco = normalizar_preco(preco_raw)
    if not preco or preco <= 0:
        return None, "sem_preco"

    # O título já traz marca+modelo+versão+ano — mesma inferência da OLX, que
    # preserva o trim (melhor que os campos brand/model do bloco Vehicle).
    marca, modelo, versao, obs, ano = inferir_marca_modelo_versao_obs_ano(titulo)
    if not modelo:
        return None, "sem_modelo"

    # Corte de ano (defesa em profundidade — o servidor já filtra por amf_2000).
    if not ano or not (1900 <= ano <= ano_ate):
        return None, "ano"

    return Anuncio(
        titulo=titulo,
        preco=preco,
        marca=marca,
        modelo=modelo,
        ano=ano,
        versao=versao,
        obs=obs,
        url=url,
        fonte=FONTE,
        data_coleta=data_coleta,
    ), None


def _url_pagina(pagina: int) -> str:
    return LISTA_URL if pagina <= 1 else f"{LISTA_URL}&pag={pagina}"


def _criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    return s


def _requisitar(sessao: requests.Session, pagina: int) -> Optional[str]:
    url = _url_pagina(pagina)
    for i in range(1, MAX_RETRIES + 1):
        try:
            r = sessao.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = "utf-8"  # o site declara utf-8 mas o requests às vezes erra a detecção
            return r.text
        except requests.RequestException as exc:
            logger.warning("[icarros] pág %d tentativa %d/%d: %s", pagina, i, MAX_RETRIES, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
