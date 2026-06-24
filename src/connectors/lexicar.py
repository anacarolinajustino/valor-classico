"""
Conector Lexicar.
Site: https://lexicar.com.br
O maior banco de dados de carros brasileiros antigos; seção de classificados
chamada "Balcão" — referência histórica do nicho de clássicos nacionais.

ATENÇÃO: O site retorna ECONNREFUSED para requisições de IPs de cloud
(AWS/Render). Pode ser proteção anti-bot ou bloqueio geográfico de
datacenter. Conector criado para futura ativação.

Estrutura esperada (a confirmar quando o acesso for restabelecido):
  Layout datado mas ativo; classificados na seção /balcao/ ou similar.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "lexicar"
BASE_URL = "https://lexicar.com.br"


def coletar_completo(max_paginas: int = 50) -> tuple[list[Anuncio], dict]:
    raise ConnectionError(
        "lexicar.com.br retorna ECONNREFUSED para IPs de cloud (Render/AWS). "
        "Fonte desativada até que o acesso seja liberado."
    )


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    logger.warning("[lexicar] fonte inativa (ECONNREFUSED). Retornando lista vazia.")
    return []


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    return []
