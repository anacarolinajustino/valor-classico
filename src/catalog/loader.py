"""
Carregamento do catálogo canônico de veículos a partir do CSV Webmotors.

Estratégia de matching (spike):
1. Exact match por (marca_normalized, modelo_normalized)
2. Fuzzy match com difflib.SequenceMatcher threshold >= 0.80
"""
from __future__ import annotations

import csv
import difflib
import logging
from pathlib import Path
from typing import Optional

from src.pipeline.normalizer import normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

# Caminho padrão do CSV do catálogo
CSV_PADRAO = Path("/Users/ana.justino/Downloads/base_dados_webmotors.csv")

# Suplemento manual: modelos ausentes do CSV principal.
# Chaves já normalizadas (uppercase, sem acento). Ranges = anos de produção no Brasil.
_SUPLEMENTO: dict[tuple[str, str], set[int]] = {
    ("FIAT",    "IDEA"):  set(range(2005, 2017)),  # lançamento 2005, descontinuado 2016
    ("RENAULT", "LOGAN"): set(range(2006, 2016)),  # lançamento 2006 no Brasil, 1ª geração
    ("PEUGEOT", "207"):   set(range(2007, 2014)),  # lançamento 2007 no Brasil, fim 2013
    ("HONDA",   "CR-V"):  set(range(1997, 2024)),  # 1ª geração no Brasil a partir de 1997
    ("TOYOTA",  "SW4"):   set(range(1992, 2024)),  # nome SW4 no Brasil desde ~1992
}

# Índice em memória: (marca_norm, modelo_norm) -> set de anos disponíveis
_catalogo: dict[tuple[str, str], set[int]] = {}
_carregado = False


def carregar_catalogo(caminho: Optional[Path] = None) -> dict[tuple[str, str], set[int]]:
    """
    Carrega o CSV do catálogo em memória como dict indexado por
    (marca_normalizada, modelo_normalizado) -> set de anos.

    Idempotente: se já carregado, retorna o cache existente.
    """
    global _catalogo, _carregado

    if _carregado:
        return _catalogo

    caminho_csv = caminho or CSV_PADRAO
    catalogo: dict[tuple[str, str], set[int]] = {}

    try:
        with open(caminho_csv, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for linha in reader:
                marca_raw = linha.get("nome_marca", "").strip()
                modelo_raw = linha.get("nome_modelo", "").strip()
                ano_raw = linha.get("ano_modelo", "").strip()

                if not marca_raw or not modelo_raw:
                    continue

                marca_norm = normalizar_texto(marca_raw)
                modelo_norm = normalizar_texto(modelo_raw)
                chave = (marca_norm, modelo_norm)

                try:
                    ano = int(ano_raw) if ano_raw else 0
                except ValueError:
                    ano = 0

                if chave not in catalogo:
                    catalogo[chave] = set()
                if ano > 0:
                    catalogo[chave].add(ano)

        _catalogo = catalogo
        _carregado = True
        logger.info("Catálogo carregado: %d entradas de marca+modelo", len(catalogo))

    except FileNotFoundError:
        logger.warning("CSV do catálogo não encontrado: %s", caminho_csv)
        _catalogo = {}

    # Mesclar suplemento (independente de o CSV ter sido encontrado ou não)
    for chave, anos_sup in _SUPLEMENTO.items():
        _catalogo.setdefault(chave, set()).update(anos_sup)
    logger.info(
        "Suplemento aplicado: %d entradas adicionadas/estendidas", len(_SUPLEMENTO)
    )
    _carregado = True

    return _catalogo


def resetar_cache() -> None:
    """Reseta o cache do catálogo (útil para testes)."""
    global _catalogo, _carregado
    _catalogo = {}
    _carregado = False


def match_anuncio(anuncio: Anuncio, caminho: Optional[Path] = None) -> Anuncio:
    """
    Tenta fazer matching do anúncio com o catálogo canônico.

    Estratégia:
    1. Exact match por (marca_norm, modelo_norm) → confidence=high, strategy=normalized_exact
    2. Fuzzy match com SequenceMatcher >= 0.80 → confidence=medium, strategy=fuzzy
    3. Sem match → confidence=unmatched, strategy=none

    Retorna novo Anuncio com match_confidence e match_strategy atualizados.
    """
    catalogo = carregar_catalogo(caminho)

    if not catalogo:
        return anuncio

    marca_norm = normalizar_texto(anuncio.marca)
    modelo_norm = normalizar_texto(anuncio.modelo)

    # 1. Exact match
    if (marca_norm, modelo_norm) in catalogo:
        return _com_match(anuncio, "high", "normalized_exact")

    # 2. Fuzzy match — busca apenas dentro dos modelos da mesma marca
    marcas_catalogo = {chave[0] for chave in catalogo}
    melhor_marca = _melhor_fuzzy(marca_norm, list(marcas_catalogo), threshold=0.80)

    if melhor_marca:
        modelos_da_marca = [chave[1] for chave in catalogo if chave[0] == melhor_marca]
        melhor_modelo = _melhor_fuzzy(modelo_norm, modelos_da_marca, threshold=0.80)
        if melhor_modelo:
            return _com_match(anuncio, "medium", "fuzzy")

    return _com_match(anuncio, "unmatched", "none")


def _melhor_fuzzy(alvo: str, candidatos: list[str], threshold: float) -> Optional[str]:
    """Retorna o melhor candidato fuzzy acima do threshold, ou None."""
    if not alvo or not candidatos:
        return None
    matches = difflib.get_close_matches(alvo, candidatos, n=1, cutoff=threshold)
    return matches[0] if matches else None


def _com_match(anuncio: Anuncio, confidence: str, strategy: str) -> Anuncio:
    """Cria cópia do anúncio com os campos de matching atualizados."""
    from dataclasses import replace
    return replace(anuncio, match_confidence=confidence, match_strategy=strategy)
