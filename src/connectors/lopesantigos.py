"""
Conector Lopes Antigos.
Site: https://lopesantigos.com.br
Loja especializada em clássicos de alto padrão (São Paulo), consignação.

ATENÇÃO: O site retorna ECONNREFUSED para requisições de IPs de cloud
(AWS/Render). Pode ser proteção anti-bot ou bloqueio geográfico de
datacenter. Conector criado para futura ativação.

Estrutura esperada (a confirmar quando o acesso for restabelecido):
  Vitrine de consignação com clássicos totalmente restaurados.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "lopesantigos"
BASE_URL = "https://lopesantigos.com.br"


def coletar_completo(max_paginas: int = 50) -> tuple[list[Anuncio], dict]:
    raise ConnectionError(
        "lopesantigos.com.br retorna ECONNREFUSED para IPs de cloud (Render/AWS). "
        "Fonte desativada até que o acesso seja liberado."
    )


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    logger.warning("[lopesantigos] fonte inativa (ECONNREFUSED). Retornando lista vazia.")
    return []


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    return []
