"""
Carregamento do catálogo canônico de veículos a partir do CSV.

Estratégia de matching:
1. Exact match por (marca_normalized, modelo_normalized) → confidence=high, strategy=normalized_exact
2. Fuzzy match com difflib.SequenceMatcher threshold >= 0.80 → confidence=medium, strategy=fuzzy
3. Sem match → confidence=unmatched, strategy=none

Quando há match de marca+modelo e o anúncio tem versão, tenta também normalizar
a versão contra as versões canônicas do catálogo para esse (marca, modelo, ano).
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

CSV_PADRAO = Path(__file__).parent.parent.parent / "data" / "base_marcamodelo.csv"

# Suplemento manual: modelos ausentes do CSV principal.
# Chaves já normalizadas (uppercase, sem acento). Ranges = anos de produção no Brasil.
_SUPLEMENTO: dict[tuple[str, str], set[int]] = {
    ("FIAT",    "IDEA"):  set(range(2005, 2017)),
    ("RENAULT", "LOGAN"): set(range(2006, 2016)),
    ("PEUGEOT", "207"):   set(range(2007, 2014)),
    ("HONDA",   "CR-V"):  set(range(1997, 2024)),
    ("TOYOTA",  "SW4"):   set(range(1992, 2024)),
}

# (marca_norm, modelo_norm) -> set de anos disponíveis
_catalogo: dict[tuple[str, str], set[int]] = {}
# (marca_norm, modelo_norm, ano) -> lista de versões normalizadas do catálogo
_versoes: dict[tuple[str, str, int], list[str]] = {}
_carregado = False


def carregar_catalogo(caminho: Optional[Path] = None) -> dict[tuple[str, str], set[int]]:
    """
    Carrega o CSV do catálogo em memória como dict indexado por
    (marca_normalizada, modelo_normalizado) -> set de anos.

    Idempotente: se já carregado, retorna o cache existente.
    """
    global _catalogo, _versoes, _carregado

    if _carregado:
        return _catalogo

    caminho_csv = caminho or CSV_PADRAO
    catalogo: dict[tuple[str, str], set[int]] = {}
    versoes: dict[tuple[str, str, int], list[str]] = {}

    try:
        with open(caminho_csv, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for linha in reader:
                marca_raw = linha.get("nome_marca", "").strip()
                modelo_raw = linha.get("nome_modelo", "").strip()
                ano_raw = linha.get("ano_modelo", "").strip()
                versao_raw = linha.get("nome_versao", "").strip()

                if not marca_raw or not modelo_raw:
                    continue

                marca_norm = normalizar_texto(marca_raw)
                modelo_norm = normalizar_texto(modelo_raw)
                chave = (marca_norm, modelo_norm)

                try:
                    ano = int(ano_raw) if ano_raw else 0
                except ValueError:
                    ano = 0

                catalogo.setdefault(chave, set())
                if ano > 0:
                    catalogo[chave].add(ano)
                    if versao_raw:
                        chave_v = (marca_norm, modelo_norm, ano)
                        versoes.setdefault(chave_v, []).append(normalizar_texto(versao_raw))

        _catalogo = catalogo
        _versoes = versoes
        _carregado = True
        logger.info("Catálogo carregado: %d entradas de marca+modelo", len(catalogo))

    except FileNotFoundError:
        logger.warning("CSV do catálogo não encontrado: %s", caminho_csv)
        _catalogo = {}
        _versoes = {}

    for chave, anos_sup in _SUPLEMENTO.items():
        _catalogo.setdefault(chave, set()).update(anos_sup)
    logger.info("Suplemento aplicado: %d entradas adicionadas/estendidas", len(_SUPLEMENTO))
    _carregado = True

    return _catalogo


def resetar_cache() -> None:
    """Reseta o cache do catálogo (útil para testes)."""
    global _catalogo, _versoes, _carregado
    _catalogo = {}
    _versoes = {}
    _carregado = False


def match_anuncio(anuncio: Anuncio, caminho: Optional[Path] = None) -> Anuncio:
    """
    Tenta fazer matching do anúncio com o catálogo canônico.

    Estratégia:
    1. Exact match por (marca_norm, modelo_norm) → confidence=high, strategy=normalized_exact
    2. Fuzzy match com SequenceMatcher >= 0.80 → confidence=medium, strategy=fuzzy
    3. Sem match → confidence=unmatched, strategy=none

    Quando há match, tenta também normalizar a versão do anúncio contra as versões
    canônicas do catálogo para aquele (marca, modelo, ano).

    Retorna novo Anuncio com match_confidence, match_strategy e versao atualizados.
    """
    catalogo = carregar_catalogo(caminho)

    if not catalogo:
        return anuncio

    marca_norm = normalizar_texto(anuncio.marca)
    modelo_norm = normalizar_texto(anuncio.modelo)

    # 1. Exact match
    if (marca_norm, modelo_norm) in catalogo:
        versao_canonical = _normalizar_versao(marca_norm, modelo_norm, anuncio.ano, anuncio.versao)
        return _com_match(anuncio, "high", "normalized_exact", versao_canonical)

    # 2. Fuzzy match — busca apenas dentro dos modelos da mesma marca
    marcas_catalogo = {chave[0] for chave in catalogo}
    melhor_marca = _melhor_fuzzy(marca_norm, list(marcas_catalogo), threshold=0.80)

    if melhor_marca:
        modelos_da_marca = [chave[1] for chave in catalogo if chave[0] == melhor_marca]
        melhor_modelo = _melhor_fuzzy(modelo_norm, modelos_da_marca, threshold=0.80)
        if melhor_modelo:
            return _com_match(anuncio, "medium", "fuzzy", None)

    return _com_match(anuncio, "unmatched", "none", None)


def _normalizar_versao(
    marca_norm: str,
    modelo_norm: str,
    ano: Optional[int],
    versao: Optional[str],
) -> Optional[str]:
    """
    Tenta casar a versão do anúncio com as versões canônicas do catálogo
    para aquele (marca, modelo, ano). Retorna a versão canônica se encontrada,
    ou None se não houver dados suficientes para normalizar.
    """
    if not versao or not ano:
        return None
    candidatos = _versoes.get((marca_norm, modelo_norm, ano), [])
    if not candidatos:
        return None
    versao_norm = normalizar_texto(versao)
    if not versao_norm:
        return None
    if versao_norm in candidatos:
        return versao_norm
    return _melhor_fuzzy(versao_norm, candidatos, threshold=0.75)


def _melhor_fuzzy(alvo: str, candidatos: list[str], threshold: float) -> Optional[str]:
    """Retorna o melhor candidato fuzzy acima do threshold, ou None."""
    if not alvo or not candidatos:
        return None
    matches = difflib.get_close_matches(alvo, candidatos, n=1, cutoff=threshold)
    return matches[0] if matches else None


def _com_match(
    anuncio: Anuncio,
    confidence: str,
    strategy: str,
    versao_canonical: Optional[str],
) -> Anuncio:
    """Cria cópia do anúncio com os campos de matching (e versão canônica) atualizados."""
    from dataclasses import replace
    updates: dict = {"match_confidence": confidence, "match_strategy": strategy}
    if versao_canonical is not None:
        updates["versao"] = versao_canonical
    return replace(anuncio, **updates)
