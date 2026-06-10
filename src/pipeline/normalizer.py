"""
Normalização de preço e texto para o pipeline do Valor Clássico.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


def normalizar_preco(valor_bruto: str) -> Optional[float]:
    """
    Converte string de preço em float.

    Exemplos aceitos:
        'R$180.000,00'  -> 180000.0
        '180.000,00'    -> 180000.0
        '180000'        -> 180000.0
        'Consulte'      -> None
        ''              -> None
    """
    if not valor_bruto or not valor_bruto.strip():
        return None

    # Remover símbolo de moeda e espaços
    limpo = re.sub(r"[R$\s]", "", valor_bruto, flags=re.IGNORECASE)

    # Formato brasileiro: 180.000,00 → remover pontos de milhar, trocar vírgula por ponto
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    else:
        limpo = limpo.replace(".", "")

    try:
        resultado = float(limpo)
        return resultado if resultado > 0 else None
    except ValueError:
        return None


def remover_acentos(texto: str) -> str:
    """
    Remove acentos de uma string para uso em matching/indexação.
    O texto original é preservado para exibição.
    """
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_texto(texto: str) -> str:
    """
    Normalização completa para indexação/matching:
    - Remove acentos
    - Converte para UPPERCASE
    - Colapsa espaços duplicados
    - Remove pontuação irrelevante (mantém hífen e ponto)
    """
    sem_acento = remover_acentos(texto)
    maiusculo = sem_acento.upper()
    # Colapsar espaços
    sem_espacos_dup = re.sub(r"\s+", " ", maiusculo).strip()
    # Remover pontuação irrelevante (vírgula, parênteses, etc.), manter hífen e ponto
    limpo = re.sub(r"[^\w\s.\-]", "", sem_espacos_dup)
    return limpo


def inferir_marca_modelo_ano(titulo: str) -> tuple[str, str, Optional[int]]:
    """
    Infere marca, modelo e ano a partir do título do anúncio.

    Estratégia:
    - Último token de 4 dígitos (1900-2099) é o ano
    - Primeiro token é a marca
    - Tokens intermediários formam o modelo

    Exemplos:
        'Volkswagen Kombi 1975'       -> ('VOLKSWAGEN', 'KOMBI', 1975)
        'VW Fusca 1200 1962'          -> ('VW', 'FUSCA 1200', 1962)
        'Chevrolet Biscayne Sedan 1963' -> ('CHEVROLET', 'BISCAYNE SEDAN', 1963)
    """
    titulo_norm = normalizar_texto(titulo)
    tokens = titulo_norm.split()

    if not tokens:
        return ("", "", None)

    # Detectar ano: último token de 4 dígitos no intervalo 1900-2099
    ano: Optional[int] = None
    tokens_sem_ano = tokens[:]
    for i in range(len(tokens) - 1, -1, -1):
        match = re.fullmatch(r"(19|20)\d{2}", tokens[i])
        if match:
            ano = int(tokens[i])
            tokens_sem_ano = tokens[:i] + tokens[i + 1 :]
            break

    if not tokens_sem_ano:
        return ("", "", ano)

    marca = tokens_sem_ano[0]
    modelo = " ".join(tokens_sem_ano[1:]) if len(tokens_sem_ano) > 1 else ""

    return (marca, modelo, ano)
