"""
Catálogos de referência EXTERNOS (não-FIPE), de fontes estrangeiras.

Este módulo é deliberadamente ISOLADO do catálogo canônico: nada aqui é
carregado por `src.catalog.loader.carregar_catalogo()`, e nenhum conector ou
etapa do pipeline importa daqui. Os CSVs que ele lê são material de consulta
e auditoria — quem decide promover um par pro catálogo de verdade é a usuária,
pelo suplemento manual do painel.

Motivo do isolamento: as fontes estrangeiras (the-oldtimers.com,
classic.com) cobrem o mercado europeu/americano e desconhecem o carro
nacional. Misturá-las direto no catálogo canônico traria grafia em inglês
("C-Class", "3 Series") pro pipeline que hoje grava em português, além de
milhares de modelos que nunca vão aparecer num anúncio brasileiro.

Fontes (ver docs/fontes_externas.md):
  - base_marcamodelo_intl.csv     — marca/modelo/faixa de ano (the-oldtimers)
  - vocabulario_geracao_trim.csv  — geração/trim/carroceria (classic.com)
  - aliases_intl.csv              — ponte PT-BR <-> EN entre as duas grafias
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Optional

from src.pipeline.normalizer import normalizar_texto

_DATA = Path(__file__).parent.parent.parent / "data"

BASE_INTL_CSV = _DATA / "base_marcamodelo_intl.csv"
VOCABULARIO_CSV = _DATA / "vocabulario_geracao_trim.csv"
ALIASES_INTL_CSV = _DATA / "aliases_intl.csv"


def chave_alfanumerica(texto: str) -> str:
    """
    Reduz um nome à sua forma só-alfanumérica ('Alfa-Romeo' -> 'ALFAROMEO').

    É a mesma ideia do `_canon_sem_separador` do loader, mas aplicada também
    à marca: é o que permite casar a grafia da fonte estrangeira com a do
    projeto sem manter uma tabela na mão.
    """
    return re.sub(r"[^A-Z0-9]", "", normalizar_texto(texto))


_marca_idx: Optional[dict[str, str]] = None


def _indice_marca() -> dict[str, str]:
    """
    forma-alfanumérica -> grafia de marca do projeto.

    Construído a partir do catálogo canônico e dos aliases de marca do
    normalizer. Resolve automaticamente as divergências de separador entre as
    fontes: 'Alfa-Romeo' -> 'ALFA ROMEO', 'Aston-Martin' -> 'ASTON MARTIN',
    'De-Tomaso' -> 'DE TOMASO', 'mercedes-benz' -> 'MERCEDES-BENZ'.
    """
    global _marca_idx
    if _marca_idx is not None:
        return _marca_idx

    from src.catalog.loader import CSV_PADRAO, _SUPLEMENTO
    from src.pipeline.normalizer import _ALIASES_MARCA

    idx: dict[str, str] = {}

    # O catálogo canônico é a autoridade de grafia.
    try:
        with open(CSV_PADRAO, encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f):
                marca = (linha.get("nome_marca") or "").strip()
                if marca:
                    idx.setdefault(chave_alfanumerica(marca), normalizar_texto(marca))
    except FileNotFoundError:
        pass

    # Suplemento preenche marcas que o CSV base não tem (REO, LAMBRETTA...).
    for marca, _modelo in _SUPLEMENTO:
        idx.setdefault(chave_alfanumerica(marca), marca)

    # Aliases do normalizer: o VALOR é a grafia canônica, a CHAVE é a variante.
    for variante, canonica in _ALIASES_MARCA.items():
        idx.setdefault(chave_alfanumerica(canonica), canonica)
        idx.setdefault(chave_alfanumerica(variante), canonica)

    _marca_idx = idx
    return idx


def marca_canonica(marca_bruta: str) -> str:
    """
    Traduz a grafia de marca de uma fonte externa para a grafia do projeto.

    Marca desconhecida do projeto volta apenas normalizada (maiúscula, sem
    acento) — é o caso da maioria das 218 marcas do the-oldtimers, que são
    europeias sem presença no mercado brasileiro (Wartburg, Trabant, Panhard).
    Isso é esperado: elas entram no CSV externo como referência, não como
    candidatas a virar marca do banco.

    Deliberadamente NÃO usa `sanear_marca_modelo`: aquela função infere a
    marca a partir do vocabulário de modelos BRASILEIRO, e numa fonte
    estrangeira isso troca a marca errado — 'Alpine A110' vira
    'SUNBEAM ALPINE A110' porque Alpine é um modelo Sunbeam no catálogo
    nacional (verificado 2026-08-04).
    """
    if not marca_bruta:
        return ""
    chave = chave_alfanumerica(marca_bruta)
    return _indice_marca().get(chave, normalizar_texto(marca_bruta))


def resetar_cache() -> None:
    """Reseta o índice de marca (útil para testes)."""
    global _marca_idx
    _marca_idx = None


def carregar_base_intl(
    caminho: Optional[Path] = None,
) -> dict[tuple[str, str], tuple[int, int]]:
    """
    Lê base_marcamodelo_intl.csv como (marca, modelo) -> (ano_min, ano_max).

    Ausência do arquivo degrada pra vazio: o CSV é gerado sob demanda por
    scripts/ingest_oldtimers.py e não é pré-requisito de nada.
    """
    fora: dict[tuple[str, str], tuple[int, int]] = {}
    try:
        with open(caminho or BASE_INTL_CSV, encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f):
                marca = (linha.get("marca") or "").strip()
                modelo = (linha.get("modelo") or "").strip()
                if not marca or not modelo:
                    continue
                try:
                    ano_min = int(linha["ano_min"])
                    ano_max = int(linha["ano_max"])
                except (KeyError, ValueError):
                    continue
                fora[(marca, modelo)] = (ano_min, ano_max)
    except FileNotFoundError:
        pass
    return fora


def carregar_aliases(caminho: Optional[Path] = None) -> dict[tuple[str, str], str]:
    """
    Lê aliases_intl.csv como (marca, modelo_ptbr) -> modelo_intl.

    Serve pra consultar as fontes estrangeiras usando a grafia que o banco
    guarda: ('BMW', 'SERIE 3') -> '3 SERIES'.
    """
    alias: dict[tuple[str, str], str] = {}
    try:
        with open(caminho or ALIASES_INTL_CSV, encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f):
                marca = (linha.get("marca") or "").strip()
                ptbr = (linha.get("modelo_ptbr") or "").strip()
                intl = (linha.get("modelo_intl") or "").strip()
                if marca and ptbr and intl:
                    alias[(marca, ptbr)] = intl
    except FileNotFoundError:
        pass
    return alias
