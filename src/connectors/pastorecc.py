"""
Conector Pastore CC.
Site: https://www.pastorecc.com.br
Motor: WordPress + WooCommerce + LiteSpeed Cache
Estratégia: requests + BeautifulSoup (server-side rendering)
"""
from __future__ import annotations
from src.connectors._woocommerce import buscar as _buscar, coletar_completo as _coletar
from src.pipeline.schema import Anuncio

FONTE = "pastorecc"
BASE_URL = "https://www.pastorecc.com.br"
LISTING_PATH = "/carros/antigos-e-colecao/"


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    return _buscar(BASE_URL, LISTING_PATH, FONTE, marca, modelo, paginas)


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    return _coletar(BASE_URL, LISTING_PATH, FONTE, max_paginas)
