"""
Conector Gustavo Brasil.
Site: http://gustavobrasil.com.br
Motor: WordPress + WooCommerce
Estratégia: requests + BeautifulSoup (server-side rendering)
"""
from __future__ import annotations
from src.connectors._woocommerce import buscar as _buscar, coletar_completo as _coletar
from src.pipeline.schema import Anuncio

FONTE = "gustavobrasil"
BASE_URL = "http://gustavobrasil.com.br"
LISTING_PATH = "/carros/"


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    return _buscar(BASE_URL, LISTING_PATH, FONTE, marca, modelo, paginas)


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    return _coletar(BASE_URL, LISTING_PATH, FONTE, max_paginas)
