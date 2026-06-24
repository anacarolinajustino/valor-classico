"""
Conector Registro 9.
Site: https://registro9.com.br
Plataforma: classificados exclusivos para clássicos brasileiros.

ATENÇÃO: O site retorna ECONNREFUSED para requisições de IPs de cloud
(AWS/Render). Pode ser proteção anti-bot ou bloqueio geográfico de
datacenter. Conector criado para futura ativação.

Estrutura esperada (a confirmar quando o acesso for restabelecido):
  Classificados completos com fotos de alta qualidade e ficha técnica.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "registro9"
BASE_URL = "https://registro9.com.br"


def coletar_completo(max_paginas: int = 50) -> tuple[list[Anuncio], dict]:
    raise ConnectionError(
        "registro9.com.br retorna ECONNREFUSED para IPs de cloud (Render/AWS). "
        "Fonte desativada até que o acesso seja liberado."
    )


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    logger.warning("[registro9] fonte inativa (ECONNREFUSED). Retornando lista vazia.")
    return []


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    return []
