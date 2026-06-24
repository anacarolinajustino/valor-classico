"""
Conector OldCar (Estadão).
Site: https://oldcar.estadao.com.br
Portal de classificados do jornal O Estado de S. Paulo focado em carros
antigos, clássicos, hot rods e especiais. Tradição no meio.

ATENÇÃO: O servidor do Estadão bloqueia requisições automatizadas
(retorna erro de conexão para IPs de cloud). Conector criado para
futura ativação.

Estrutura esperada (a confirmar quando o acesso for restabelecido):
  Portal de classificados com anúncios de particulares e revendas.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "oldcar"
BASE_URL = "https://oldcar.estadao.com.br"


def coletar_completo(max_paginas: int = 50) -> tuple[list[Anuncio], dict]:
    raise ConnectionError(
        "oldcar.estadao.com.br bloqueia requisições automatizadas de IPs de cloud. "
        "Fonte desativada até que o acesso seja liberado."
    )


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    logger.warning("[oldcar] fonte inativa (bloqueada pelo Estadão). Retornando lista vazia.")
    return []


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    return []
