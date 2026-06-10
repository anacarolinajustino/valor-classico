"""
Contrato canônico de dados do Valor Clássico.

Define a dataclass Anuncio que representa um anúncio normalizado,
independente da fonte coletora.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Valores válidos para os campos de matching
MATCH_CONFIDENCE_VALUES = frozenset({"high", "medium", "low", "unmatched"})
MATCH_STRATEGY_VALUES = frozenset(
    {"exact", "normalized_exact", "fuzzy", "manual_review", "none"}
)


@dataclass
class Anuncio:
    """Anúncio normalizado no contrato canônico do Valor Clássico."""

    titulo: str
    preco: Optional[float]
    marca: str
    modelo: str
    ano: Optional[int]
    versao: Optional[str]
    url: str
    fonte: str
    data_coleta: str          # ISO 8601 (YYYY-MM-DD)
    match_confidence: str = "unmatched"   # high / medium / low / unmatched
    match_strategy: str = "none"          # exact / normalized_exact / fuzzy / manual_review / none

    def __post_init__(self) -> None:
        if self.match_confidence not in MATCH_CONFIDENCE_VALUES:
            raise ValueError(
                f"match_confidence inválido: '{self.match_confidence}'. "
                f"Use um de: {sorted(MATCH_CONFIDENCE_VALUES)}"
            )
        if self.match_strategy not in MATCH_STRATEGY_VALUES:
            raise ValueError(
                f"match_strategy inválido: '{self.match_strategy}'. "
                f"Use um de: {sorted(MATCH_STRATEGY_VALUES)}"
            )


def validar(anuncio: Anuncio) -> bool:
    """
    Valida se um anúncio tem os campos mínimos obrigatórios.

    Retorna True se válido; False se deve ser descartado.
    Regras:
    - preco deve ser um float positivo
    - modelo não pode ser vazio
    """
    if not anuncio.modelo or not anuncio.modelo.strip():
        return False
    if anuncio.preco is None or anuncio.preco <= 0:
        return False
    return True
