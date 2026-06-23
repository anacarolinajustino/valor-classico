"""
Conector GGS Veículos Antigos.
Site: https://ggsveiculosantigos.com.br
Motor: WordPress + WooCommerce (sem slug /loja/, usa ?post_type=product)
"""
from __future__ import annotations

import logging
import time
from datetime import date

from src.connectors._woocommerce import (
    criar_sessao, parsear_produtos, requisitar, tem_proxima_pagina,
    buscar as _buscar,
)
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "ggsveiculosantigos"
BASE_URL = "https://ggsveiculosantigos.com.br"
RATE_LIMIT = 1.0


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    return _buscar(BASE_URL, "/", FONTE, marca, modelo, paginas)


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    sessao = criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0

    for pg in range(1, max_paginas + 1):
        url = (
            f"{BASE_URL}/?post_type=product"
            if pg == 1
            else f"{BASE_URL}/?post_type=product&paged={pg}"
        )
        html = requisitar(sessao, url)
        if html is None:
            erros += 1
            break

        items = parsear_produtos(html, FONTE, data_coleta)
        if not items:
            break

        paginas_ok += 1
        for a in items:
            if a.url not in seen:
                seen.add(a.url)
                anuncios.append(a)

        if not tem_proxima_pagina(html):
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
    logger.info("[ggsveiculosantigos] coleta completa: %s", metricas)
    return anuncios, metricas
