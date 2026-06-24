"""
Conector AutoClassic.
Site: https://autoclassic.com.br
Loja com showroom em São Paulo; clássicos importados e nacionais de alto nível.

ATENÇÃO: O site retorna ECONNREFUSED para requisições de IPs de cloud
(AWS/Render). Pode ser proteção anti-bot ou bloqueio geográfico de
datacenter. Conector criado para futura ativação.

Estrutura esperada (a confirmar quando o acesso for restabelecido):
  Showroom digital de clássicos especiais.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "autoclassic"
BASE_URL = "https://autoclassic.com.br"


def coletar_completo(max_paginas: int = 50) -> tuple[list[Anuncio], dict]:
    raise ConnectionError(
        "autoclassic.com.br retorna ECONNREFUSED para IPs de cloud (Render/AWS). "
        "Fonte desativada até que o acesso seja liberado."
    )


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    logger.warning("[autoclassic] fonte inativa (ECONNREFUSED). Retornando lista vazia.")
    return []


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    return []
