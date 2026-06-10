"""
Filtro de outliers de preço por IQR (Interquartile Range).
"""
from __future__ import annotations

from typing import Sequence

from src.pipeline.schema import Anuncio


def filtrar_outliers(anuncios: Sequence[Anuncio], fator_iqr: float = 1.5) -> list[Anuncio]:
    """
    Remove anúncios com preços considerados outliers usando o método IQR.

    Um preço é outlier se:
        preco < Q1 - fator_iqr * IQR  OU  preco > Q3 + fator_iqr * IQR

    Anúncios sem preço (preco=None) são preservados na saída.
    Se houver menos de 4 anúncios com preço, nenhum é removido (sem
    amostra estatisticamente significativa).
    """
    com_preco = [a for a in anuncios if a.preco is not None]
    sem_preco = [a for a in anuncios if a.preco is None]

    if len(com_preco) < 4:
        return list(anuncios)

    precos = sorted(a.preco for a in com_preco)  # type: ignore[misc]
    n = len(precos)

    q1 = _percentil(precos, 25)
    q3 = _percentil(precos, 75)
    iqr = q3 - q1

    limite_inf = q1 - fator_iqr * iqr
    limite_sup = q3 + fator_iqr * iqr

    filtrados = [a for a in com_preco if limite_inf <= a.preco <= limite_sup]  # type: ignore[operator]
    return filtrados + sem_preco


def _percentil(valores_ordenados: list[float], p: float) -> float:
    """Calcula percentil p (0-100) de uma lista já ordenada."""
    n = len(valores_ordenados)
    if n == 0:
        return 0.0
    idx = (p / 100) * (n - 1)
    lower = int(idx)
    upper = lower + 1
    if upper >= n:
        return valores_ordenados[lower]
    fracao = idx - lower
    return valores_ordenados[lower] * (1 - fracao) + valores_ordenados[upper] * fracao
