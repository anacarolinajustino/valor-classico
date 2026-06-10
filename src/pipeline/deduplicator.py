"""
Deduplicação de anúncios por URL.
"""
from __future__ import annotations

from typing import Sequence

from src.pipeline.schema import Anuncio


def deduplicar(anuncios: Sequence[Anuncio]) -> list[Anuncio]:
    """
    Remove anúncios duplicados mantendo a primeira ocorrência de cada URL.
    """
    vistos: set[str] = set()
    resultado: list[Anuncio] = []
    for anuncio in anuncios:
        url_norm = anuncio.url.rstrip("/").lower()
        if url_norm not in vistos:
            vistos.add(url_norm)
            resultado.append(anuncio)
    return resultado
