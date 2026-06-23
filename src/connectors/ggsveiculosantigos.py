"""
Conector GGS Veículos Antigos.
Site: https://ggsveiculosantigos.com.br
Motor: WordPress + WooCommerce 6.6.1
Estratégia: requests + BeautifulSoup (server-side rendering)
"""
from __future__ import annotations
from src.connectors._woocommerce import buscar as _buscar, coletar_completo as _coletar
from src.pipeline.schema import Anuncio

FONTE = "ggsveiculosantigos"
BASE_URL = "https://ggsveiculosantigos.com.br"
LISTING_PATH = "/loja/"


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    return _buscar(BASE_URL, LISTING_PATH, FONTE, marca, modelo, paginas)


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    return _coletar(BASE_URL, LISTING_PATH, FONTE, max_paginas)
