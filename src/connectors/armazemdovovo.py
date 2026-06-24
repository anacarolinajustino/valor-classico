"""
Conector Armazém do Vovô.
Site: https://armazemdovovo.com.br

ATENÇÃO: O site retorna HTTP 403 para requisições automatizadas (Cloudflare/bot
protection). Conector criado para futura ativação quando a situação mudar.
Adicionado em FONTES_INATIVAS em app.py.

Estrutura esperada (a confirmar quando o acesso for restabelecido):
  Classificados de veículos antigos, raros e motos especiais.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.pipeline.normalizer import inferir_marca_modelo_ano, normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "armazemdovovo"
BASE_URL = "https://armazemdovovo.com.br"
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def coletar_completo(max_paginas: int = 50) -> tuple[list[Anuncio], dict]:
    data_coleta = date.today().isoformat()
    raise ConnectionError(
        "armazemdovovo.com.br retorna 403 Forbidden para requisições automáticas "
        "(proteção Cloudflare). Fonte desativada até que o acesso seja liberado."
    )


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    logger.warning("[armazemdovovo] fonte inativa (403). Retornando lista vazia.")
    return []


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    return []
