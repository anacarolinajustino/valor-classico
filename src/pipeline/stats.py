"""
Cálculo estatístico base sobre uma lista de anúncios.
"""
from __future__ import annotations

from typing import Sequence

from src.pipeline.schema import Anuncio


def calcular(anuncios: Sequence[Anuncio]) -> dict:
    """
    Calcula estatísticas de preço sobre a lista de anúncios fornecida.

    Retorna um dict com:
        media: float
        mediana: float
        minimo: float
        maximo: float
        amostra: int
        data_coleta_mais_recente: str  (ISO 8601 da coleta mais recente)
    """
    com_preco = [a for a in anuncios if a.preco is not None]

    if not com_preco:
        return {
            "media": 0.0,
            "mediana": 0.0,
            "minimo": 0.0,
            "maximo": 0.0,
            "amostra": 0,
            "data_coleta_mais_recente": "",
        }

    precos = sorted(a.preco for a in com_preco)  # type: ignore[misc]
    n = len(precos)

    media = sum(precos) / n
    mediana = _mediana(precos)
    minimo = precos[0]
    maximo = precos[-1]

    # Data de coleta mais recente (comparação lexicográfica é suficiente para ISO 8601)
    data_mais_recente = max(a.data_coleta for a in com_preco)

    return {
        "media": round(media, 2),
        "mediana": round(mediana, 2),
        "minimo": minimo,
        "maximo": maximo,
        "amostra": n,
        "data_coleta_mais_recente": data_mais_recente,
    }


def _mediana(valores_ordenados: list[float]) -> float:
    n = len(valores_ordenados)
    meio = n // 2
    if n % 2 == 1:
        return valores_ordenados[meio]
    return (valores_ordenados[meio - 1] + valores_ordenados[meio]) / 2
