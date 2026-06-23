"""
Conector Franz Veículos Antigos.
Site: https://franzveiculosantigos.com.br
Motor: WordPress + WooCommerce
Estratégia: requests + BeautifulSoup (server-side rendering)
"""
from __future__ import annotations
from src.connectors._woocommerce import buscar as _buscar, coletar_completo as _coletar
from src.pipeline.schema import Anuncio

FONTE = "franzveiculosantigos"
BASE_URL = "https://franzveiculosantigos.com.br"
LISTING_PATH = "/loja/"


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    return _buscar(BASE_URL, LISTING_PATH, FONTE, marca, modelo, paginas)


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    return _coletar(BASE_URL, LISTING_PATH, FONTE, max_paginas)
