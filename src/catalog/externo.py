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

# Decisões da usuária sobre os aliases, em arquivo SEPARADO de propósito:
# aliases_intl.csv é regenerado inteiro por scripts/gerar_aliases_intl.py, e
# uma coluna de status lá dentro seria apagada na próxima rodada.
ALIASES_DECISOES_CSV = _DATA / "aliases_decisoes.csv"


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
    """Reseta os índices em memória (útil para testes)."""
    global _marca_idx, _busca_idx
    _marca_idx = None
    _busca_idx = None


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


def carregar_vocabulario(
    caminho: Optional[Path] = None,
) -> dict[tuple[str, str], dict[str, list[str]]]:
    """
    Lê vocabulario_geracao_trim.csv como
    (marca, modelo) -> {geracoes, trims, carrocerias} (listas).
    """
    vocab: dict[tuple[str, str], dict[str, list[str]]] = {}
    try:
        with open(caminho or VOCABULARIO_CSV, encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f):
                marca = (linha.get("marca") or "").strip()
                modelo = (linha.get("modelo") or "").strip()
                if not marca or not modelo:
                    continue
                vocab[(marca, modelo)] = {
                    campo: [p for p in (linha.get(campo) or "").split("|") if p]
                    for campo in ("geracoes", "trims", "carrocerias")
                }
    except FileNotFoundError:
        pass
    return vocab


def carregar_decisoes_alias(
    caminho: Optional[Path] = None,
) -> dict[tuple[str, str], str]:
    """(marca, modelo_ptbr) -> 'aprovado' | 'rejeitado'."""
    decisoes: dict[tuple[str, str], str] = {}
    try:
        with open(caminho or ALIASES_DECISOES_CSV, encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f):
                marca = (linha.get("marca") or "").strip()
                ptbr = (linha.get("modelo_ptbr") or "").strip()
                decisao = (linha.get("decisao") or "").strip().lower()
                if marca and ptbr and decisao in ("aprovado", "rejeitado"):
                    decisoes[(marca, ptbr)] = decisao  # última linha vence
    except FileNotFoundError:
        pass
    return decisoes


def listar_aliases(caminho: Optional[Path] = None) -> list[dict]:
    """Todas as linhas de aliases_intl.csv, com a decisão da usuária anexada."""
    decisoes = carregar_decisoes_alias()
    linhas: list[dict] = []
    try:
        with open(caminho or ALIASES_INTL_CSV, encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f):
                marca = (linha.get("marca") or "").strip()
                ptbr = (linha.get("modelo_ptbr") or "").strip()
                intl = (linha.get("modelo_intl") or "").strip()
                if not (marca and ptbr and intl):
                    continue
                linhas.append(
                    {
                        "marca": marca,
                        "modelo_ptbr": ptbr,
                        "modelo_intl": intl,
                        "regra": (linha.get("regra") or "").strip(),
                        "fonte": (linha.get("fonte") or "").strip(),
                        "n_anuncios": int(linha.get("n_anuncios") or 0),
                        "similaridade": float(linha.get("similaridade") or 0),
                        "decisao": decisoes.get((marca, ptbr), ""),
                    }
                )
    except FileNotFoundError:
        pass
    return linhas


def carregar_aliases(caminho: Optional[Path] = None) -> dict[tuple[str, str], str]:
    """
    Lê aliases_intl.csv como (marca, modelo_ptbr) -> modelo_intl, JÁ SEM os
    aliases que a usuária rejeitou.

    Serve pra consultar as fontes estrangeiras usando a grafia que o banco
    guarda: ('BMW', 'SERIE 3') -> '3 SERIES'. Um alias rejeitado é um alias
    errado — deixá-lo aqui faria a busca externa devolver evidência de um
    carro que não é aquele.
    """
    decisoes = carregar_decisoes_alias()
    alias: dict[tuple[str, str], str] = {}
    try:
        with open(caminho or ALIASES_INTL_CSV, encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f):
                marca = (linha.get("marca") or "").strip()
                ptbr = (linha.get("modelo_ptbr") or "").strip()
                intl = (linha.get("modelo_intl") or "").strip()
                if marca and ptbr and intl:
                    if decisoes.get((marca, ptbr)) == "rejeitado":
                        continue
                    alias[(marca, ptbr)] = intl
    except FileNotFoundError:
        pass
    return alias


def registrar_decisao_alias(marca: str, modelo_ptbr: str, decisao: str) -> None:
    """Anexa a decisão da usuária sobre um alias e invalida o cache de busca."""
    from datetime import datetime

    if decisao not in ("aprovado", "rejeitado"):
        raise ValueError("Decisão deve ser 'aprovado' ou 'rejeitado'.")

    novo = not ALIASES_DECISOES_CSV.exists()
    ALIASES_DECISOES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(ALIASES_DECISOES_CSV, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if novo:
            w.writerow(["marca", "modelo_ptbr", "decisao", "quando"])
        w.writerow([marca, modelo_ptbr, decisao,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")])

    resetar_cache()


# ── Busca de evidência externa ───────────────────────────────────────────────
#
# Usada tanto pelo script de auditoria (scripts/auditar_cobertura_externa.py)
# quanto pelo painel de pendências (src/pipeline/pendencias.py). Mora aqui pra
# as duas terem exatamente a mesma regra — se divergissem, a auditoria diria
# uma coisa e a tela outra sobre o mesmo par.

# Prefixo com menos de 3 caracteres casa quase tudo ('C' casaria com toda a
# linha C da Mercedes), então não conta como evidência.
MIN_PREFIXO = 3

_busca_idx: Optional[tuple[dict, dict, dict, dict]] = None


def _indices_busca() -> tuple[dict, dict, dict, dict]:
    """(base_intl, modelos_oldtimers_por_marca, modelos_classic_por_marca, aliases)."""
    global _busca_idx
    if _busca_idx is not None:
        return _busca_idx

    base_intl = carregar_base_intl()
    oldtimers: dict[str, set[str]] = {}
    for marca, modelo in base_intl:
        oldtimers.setdefault(marca, set()).add(modelo)

    classic: dict[str, set[str]] = {}
    for marca, modelo in carregar_vocabulario():
        classic.setdefault(marca, set()).add(modelo)

    _busca_idx = (base_intl, oldtimers, classic, carregar_aliases())
    return _busca_idx


def _casa_prefixo(modelo: str, candidatos: set[str]) -> Optional[str]:
    """
    Modelo do banco e da fonte compartilham o nome-base.
    'GALAXIE 500' casa com 'GALAXIE'; 'DEFENDER' casa com 'DEFENDER 110'.
    """
    if len(modelo) < MIN_PREFIXO:
        return None
    for c in sorted(candidatos):
        if len(c) < MIN_PREFIXO:
            continue
        if modelo.startswith(c + " ") or c.startswith(modelo + " "):
            return c
    return None


def _suspeita(modelo: str, alvo: str) -> str:
    """
    Marca o caso em que o modelo do BANCO parece truncado, não alternativo.

    Casar por prefixo é faca de dois gumes. 'GALAXIE 500' -> 'GALAXIE' é
    legítimo (o banco tem o trim junto, a fonte não). Mas 'MODEL' -> 'MODEL T',
    'RANGE' -> 'RANGE ROVER' e 'MARK' -> 'MARK 7' são o contrário: o banco
    perdeu metade do nome numa extração ruim, e a fonte está completando o que
    faltou. Promover esses pares pro catálogo cimentaria o bug — o certo é
    corrigir o modelo no banco.

    Sinal usado: o nome da FONTE é mais longo e começa com o do banco.
    """
    if alvo.startswith(modelo + " "):
        return "modelo_truncado"
    if len(modelo) <= 2:
        return "modelo_curto"
    return ""


def evidencia_externa(marca: str, modelo: str) -> Optional[dict]:
    """
    Procura (marca, modelo) nas fontes externas. Devolve None se nenhuma
    conhece o par — o que, pra carro nacional, é o resultado ESPERADO e não
    um sinal de que o par está errado.

    Três estratégias, em ordem decrescente de confiança:
      1. literal  — o par existe igual na fonte
      2. alias    — existe sob o nome em inglês (via aliases_intl.csv)
      3. prefixo  — compartilham o nome-base ('GALAXIE 500' <-> 'GALAXIE')

    Retorna {modelo_fonte, estrategia, fonte, ano_min, ano_max, suspeita}.
    `ano_min`/`ano_max` são None quando só o classic.com conhece o par (a
    taxonomia dele não tem ano) e são a faixa de produção MUNDIAL quando vêm
    do the-oldtimers — costuma ser mais larga que a brasileira.
    """
    base_intl, oldtimers, classic, aliases = _indices_busca()
    if not marca or not modelo:
        return None

    cand_old = oldtimers.get(marca, set())
    cand_classic = classic.get(marca, set())
    if not cand_old and not cand_classic:
        return None

    alvo = estrategia = fonte = None

    if modelo in cand_old:
        alvo, estrategia, fonte = modelo, "literal", "the-oldtimers.com"
    elif modelo in cand_classic:
        alvo, estrategia, fonte = modelo, "literal", "classic.com"
    elif (marca, modelo) in aliases:
        traduzido = aliases[(marca, modelo)]
        if traduzido in cand_old:
            alvo, estrategia, fonte = traduzido, "alias", "the-oldtimers.com"
        elif traduzido in cand_classic:
            alvo, estrategia, fonte = traduzido, "alias", "classic.com"

    if not alvo:
        achado = _casa_prefixo(modelo, cand_old)
        if achado:
            alvo, estrategia, fonte = achado, "prefixo", "the-oldtimers.com"
        else:
            achado = _casa_prefixo(modelo, cand_classic)
            if achado:
                alvo, estrategia, fonte = achado, "prefixo", "classic.com"

    if not alvo:
        return None

    faixa = base_intl.get((marca, alvo))
    return {
        "modelo_fonte": alvo,
        "estrategia": estrategia,
        "fonte": fonte,
        "ano_min": faixa[0] if faixa else None,
        "ano_max": faixa[1] if faixa else None,
        "suspeita": _suspeita(modelo, alvo),
    }
