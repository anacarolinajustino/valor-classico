"""
Conector GG World.
Site: https://www.ggworld.com.br
Loja de clássicos em São Paulo (Brooklin); ~15 veículos, plataforma Wix.

ATENÇÃO: O site Wix carrega veículos adicionais via botão "Load More"
(JavaScript/AJAX), impossibilitando paginação com requests. Além disso,
os cards de veículos não possuem links individuais rastreáveis para
cada anúncio. Conector criado para futura ativação com Playwright.

Estrutura esperada (a confirmar com renderização JS):
  Cards com título, preço e status "VENDIDO" / preço ativo.
  Sem URL individual por veículo (cards são modais ou âncoras JS).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "ggworld"
BASE_URL = "https://www.ggworld.com.br"


def coletar_completo(max_paginas: int = 5) -> tuple[list[Anuncio], dict]:
    raise ConnectionError(
        "ggworld.com.br usa Wix com 'Load More' via JavaScript e não possui links "
        "individuais por veículo. Requer Playwright para coleta. "
        "Fonte desativada até implementação com renderização JS."
    )


def buscar(marca: str, modelo: str, paginas: int = 1) -> list[Anuncio]:
    logger.warning("[ggworld] fonte inativa (Wix JS). Retornando lista vazia.")
    return []


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    return []
