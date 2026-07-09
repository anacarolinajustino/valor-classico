"""
Conector GG World.
Site: https://www.ggworld.com.br
Loja de clássicos em São Paulo (Brooklin), plataforma Wix, site de uma
página só (os links do menu "VEÍCULOS"/"CONTATO" apontam pra própria home —
não há rota de listagem separada).

Estratégia: os veículos ficam numa galeria Wix na home. Um botão "Load More"
injeta mais cards via JS (sem paginação por URL) — requer Playwright. Os
cards não têm link individual por veículo (não são âncoras), então o campo
`url` usa um slug estável do título em vez de uma página real. Cards já
vendidos mostram "VENDIDO" no lugar do preço — são ignorados individualmente,
não descartam a fonte inteira (mesmo princípio do classicospremium/franz).
"""
from __future__ import annotations

import logging
from datetime import date

from src.connectors._browser import criar_contexto
from src.pipeline.normalizer import inferir_marca_modelo_ano, normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "ggworld"
BASE_URL = "https://www.ggworld.com.br"
_LOAD_MORE_TEXTS = ["Load More", "Ver mais", "VER MAIS", "Carregar mais", "Mostrar mais"]


def coletar_completo(max_paginas: int = 5) -> tuple[list[Anuncio], dict]:
    data_coleta = date.today().isoformat()
    cards = _coletar_cards()
    anuncios: list[Anuncio] = []
    vendidos = 0
    descartados = 0

    for titulo, preco_txt in cards:
        anuncio = _montar_anuncio(titulo, preco_txt, data_coleta)
        if anuncio == "vendido":
            vendidos += 1
        elif anuncio:
            anuncios.append(anuncio)
        else:
            descartados += 1

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "cards_total": len(cards),
        "anuncios_validos": len(anuncios),
        "vendidos_ignorados": vendidos,
        "descartados_sem_preco_ou_modelo": descartados,
    }
    logger.info("[ggworld] coleta completa: %s", metricas)
    return anuncios, metricas


def buscar(marca: str, modelo: str, paginas: int = 1) -> list[Anuncio]:
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []

    for titulo, preco_txt in _coletar_cards():
        titulo_norm = normalizar_texto(titulo)
        if modelo_norm and modelo_norm not in titulo_norm:
            continue
        if marca_norm and marca_norm not in titulo_norm:
            continue
        anuncio = _montar_anuncio(titulo, preco_txt, data_coleta)
        if anuncio and anuncio != "vendido":
            anuncios.append(anuncio)

    logger.info("[ggworld] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def _montar_anuncio(titulo: str, preco_txt: str, data_coleta: str):
    """Retorna Anuncio, None (sem preço/modelo válido) ou "vendido" (já vendido)."""
    if "vendid" in preco_txt.lower():
        return "vendido"

    preco = normalizar_preco(preco_txt)
    if not preco or preco <= 0:
        return None

    marca, modelo, ano = inferir_marca_modelo_ano(titulo)
    if not modelo:
        return None

    slug = normalizar_texto(titulo).replace(" ", "-")
    return Anuncio(
        titulo=titulo, preco=preco, marca=marca, modelo=modelo,
        ano=ano, versao=None, url=f"{BASE_URL}/#{slug}", fonte=FONTE,
        data_coleta=data_coleta,
    )


def _coletar_cards() -> list[tuple[str, str]]:
    """Abre o browser, clica em 'Load More' até esgotar e devolve (titulo, preco_ou_status) por card."""
    with criar_contexto() as ctx:
        page = ctx.new_page()
        page.goto(BASE_URL, wait_until="load", timeout=60000)
        page.wait_for_timeout(3000)

        botao = None
        for texto in _LOAD_MORE_TEXTS:
            loc = page.get_by_text(texto, exact=False)
            if loc.count() > 0:
                botao = loc.first
                break

        if botao:
            for _ in range(20):
                try:
                    botao.scroll_into_view_if_needed(timeout=3000)
                    botao.click(timeout=3000)
                    page.wait_for_timeout(1200)
                except Exception:
                    break

        cards = page.locator("div.item-container-regular").all()
        resultado: list[tuple[str, str]] = []
        for c in cards:
            texto = c.inner_text().strip()
            partes = [p.strip() for p in texto.split("\n") if p.strip()]
            if len(partes) < 2:
                continue
            resultado.append((partes[0], partes[-1]))
        return resultado
