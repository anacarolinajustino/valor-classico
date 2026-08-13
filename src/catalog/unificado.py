"""
Catálogo unificado: as sete fontes de marca/modelo/versão vistas numa tabela
só, pra a curadoria produzir um catálogo definitivo.

POR QUE ISSO EXISTE
-------------------
O conhecimento sobre "que carro existe" está espalhado em sete lugares que
ninguém consegue comparar de cabeça: o que os anúncios mostram, o catálogo
da Webmotors (em dois arquivos), dois suplementos manuais (um em CSV, outro
embutido no código), o catálogo estrangeiro e o vocabulário de trim. Cada um
tem uma granularidade diferente e nenhum é completo.

São 20.109 trios (marca, modelo, versão) e 6.197 pares. Os números que
importam pra quem vai triar:

    13.472 trios têm UMA fonte só avalizando
    17.339 trios não têm anúncio nosso nenhum
     2.499 trios só existem nos anúncios, sem catálogo que os confirme

O QUE ESTE MÓDULO NÃO FAZ
-------------------------
Não toca nos anúncios. A curadoria grava num catálogo próprio
(`data/catalogo_definitivo.csv`) e a base coletada continua sendo o registro
do que foi encontrado - decisão da usuária em 2026-08-12. Aplicar as
correções retroativamente aos anúncios é trabalho de um script separado, com
dry-run e backup, como nas rodadas de saneamento anteriores.

COMO AS FONTES SE COMBINAM
--------------------------
Cada fonte contribui com o que tem, e nada é inventado:

    fonte                granularidade          anos
    anuncios             marca+modelo+versão    min/max observados
    webmotors            marca+modelo+versão    min/max dos ano_modelo
    webmotors_bruto      idem (snapshot antigo) idem
    internacional        marca+modelo+versão    ano_min/ano_max da fonte
    suplemento_manual    marca+modelo           ano_min/ano_max
    suplemento_codigo    marca+modelo           conjunto de anos
    vocab_trim           marca+modelo+trim      nenhum

A faixa sugerida é a união (menor mínimo, maior máximo), e as faixas de cada
fonte viajam junto: quando duas discordam, quem tria precisa ver as duas em
vez de um número já achatado.
"""
from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional

from src.pipeline.normalizer import normalizar_texto

logger = logging.getLogger(__name__)

DATA = Path(__file__).parent.parent.parent / "data"

# Onde a curadoria grava. Não é gerado por script nenhum: some se apagado, e
# a tela volta a mostrar tudo como pendente.
CATALOGO_DEFINITIVO_CSV = DATA / "catalogo_definitivo.csv"

# Rótulo de cada fonte na tela, e a ordem em que aparecem. A ordem é por
# confiabilidade decrescente pra o crachá mais forte vir primeiro na linha.
FONTES: dict[str, str] = {
    "anuncios": "Anúncios coletados",
    "webmotors": "Webmotors",
    "webmotors_bruto": "Webmotors (bruto)",
    "suplemento_manual": "Suplemento manual",
    "suplemento_codigo": "Suplemento do código",
    "internacional": "Catálogo estrangeiro",
    "vocab_trim": "Vocabulário de trim",
}

SITUACOES = ("pendente", "confirmado", "descartado")

COLUNAS_DEFINITIVO = [
    # A chave é o trio de ORIGEM: o índice é reconstruído das fontes a cada
    # carga, e a decisão se sobrepõe a ele por essa chave. Guardar só o valor
    # editado perderia o vínculo assim que alguém corrigisse o nome.
    "marca_origem", "modelo_origem", "versao_origem",
    "marca", "modelo", "versao", "ano_min", "ano_max",
    "situacao", "quando",
]

_indice_cache: Optional[dict[tuple[str, str, str], dict[str, Any]]] = None


# ── Leitura das fontes ───────────────────────────────────────────────────────

def _linhas_csv(nome: str) -> Iterable[dict[str, str]]:
    """Lê um CSV de data/. Arquivo ausente é ausência de fonte, não erro."""
    caminho = DATA / nome
    if not caminho.exists():
        logger.info("Fonte de catálogo ausente: %s", nome)
        return []
    with open(caminho, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _inteiro(valor: Any) -> Optional[int]:
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    # 0 é o "sem ano" do CSV da Webmotors, e ano de 4 dígitos é o único
    # formato que qualquer fonte usa.
    return n if 1000 <= n <= 2100 else None


def _registrar(
    indice: dict, marca: Any, modelo: Any, versao: Any, fonte: str,
    ano_min: Optional[int] = None, ano_max: Optional[int] = None,
    n_anuncios: int = 0,
) -> None:
    marca_n = normalizar_texto(str(marca or ""))
    modelo_n = normalizar_texto(str(modelo or ""))
    if not marca_n or not modelo_n:
        return
    versao_n = normalizar_texto(str(versao or ""))

    linha = indice.setdefault(
        (marca_n, modelo_n, versao_n),
        {"marca": marca_n, "modelo": modelo_n, "versao": versao_n,
         "fontes": {}, "n_anuncios": 0},
    )
    faixa = linha["fontes"].setdefault(fonte, {"ano_min": None, "ano_max": None})
    if ano_min is not None:
        faixa["ano_min"] = ano_min if faixa["ano_min"] is None else min(faixa["ano_min"], ano_min)
    if ano_max is not None:
        faixa["ano_max"] = ano_max if faixa["ano_max"] is None else max(faixa["ano_max"], ano_max)
    linha["n_anuncios"] += n_anuncios


def _do_banco(indice: dict) -> None:
    """Anúncios coletados: o que o mercado de fato mostrou."""
    from src.pipeline.persistence import _connect

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT marca, modelo, COALESCE(versao, '') AS versao,
                       MIN(ano) AS ano_min, MAX(ano) AS ano_max, COUNT(*) AS n
                FROM anuncios
                WHERE marca IS NOT NULL AND modelo IS NOT NULL
                GROUP BY 1, 2, 3
                """
            )
            for r in cur.fetchall():
                _registrar(indice, r["marca"], r["modelo"], r["versao"], "anuncios",
                           _inteiro(r["ano_min"]), _inteiro(r["ano_max"]), r["n"])


def _do_webmotors(indice: dict, arquivo: str, fonte: str) -> None:
    """Uma linha por (modelo, ano, versão) - agregamos em faixa aqui."""
    for l in _linhas_csv(arquivo):
        ano = _inteiro(l.get("ano_modelo"))
        _registrar(indice, l.get("nome_marca"), l.get("nome_modelo"),
                   l.get("nome_versao"), fonte, ano, ano)


def _do_internacional(indice: dict) -> None:
    """Versões vêm numa coluna só, separadas por '|'."""
    for l in _linhas_csv("base_marcamodelo_intl.csv"):
        a1, a2 = _inteiro(l.get("ano_min")), _inteiro(l.get("ano_max"))
        versoes = [v for v in (l.get("versoes") or "").split("|") if v.strip()]
        for v in versoes or [""]:
            _registrar(indice, l.get("marca"), l.get("modelo"), v,
                       "internacional", a1, a2)


def _do_suplemento_manual(indice: dict) -> None:
    """Só marca+modelo: entra como linha de versão vazia."""
    for l in _linhas_csv("suplemento_manual.csv"):
        _registrar(indice, l.get("marca"), l.get("modelo"), "",
                   "suplemento_manual", _inteiro(l.get("ano_min")),
                   _inteiro(l.get("ano_max")))


def _do_suplemento_codigo(indice: dict) -> None:
    """O dict embutido em loader.py, que ninguém edita sem mexer no código."""
    from src.catalog.loader import _SUPLEMENTO

    for (marca, modelo), anos in _SUPLEMENTO.items():
        if not anos:
            _registrar(indice, marca, modelo, "", "suplemento_codigo")
            continue
        _registrar(indice, marca, modelo, "", "suplemento_codigo",
                   min(anos), max(anos))


def _do_vocab_trim(indice: dict) -> None:
    """Trims sem ano nenhum - avalizam a existência da versão, não a faixa."""
    for l in _linhas_csv("vocabulario_geracao_trim.csv"):
        trims = [t for t in (l.get("trims") or "").split("|") if t.strip()]
        for t in trims or [""]:
            _registrar(indice, l.get("marca"), l.get("modelo"), t, "vocab_trim")


def construir_indice(recarregar: bool = False) -> dict[tuple[str, str, str], dict[str, Any]]:
    """
    O índice unificado, em cache no processo.

    Custa alguns segundos (lê ~40 mil linhas de CSV e agrega o banco), e as
    fontes só mudam quando alguém edita um arquivo ou roda uma coleta - por
    isso o cache. As DECISÕES não entram aqui: elas são relidas a cada
    listagem, pra a tela refletir a curadoria na hora.
    """
    global _indice_cache
    if _indice_cache is not None and not recarregar:
        return _indice_cache

    indice: dict[tuple[str, str, str], dict[str, Any]] = {}
    _do_banco(indice)
    _do_webmotors(indice, "base_marcamodelo.csv", "webmotors")
    _do_webmotors(indice, "base_dados_webmotors.csv", "webmotors_bruto")
    _do_internacional(indice)
    _do_suplemento_manual(indice)
    _do_suplemento_codigo(indice)
    _do_vocab_trim(indice)

    logger.info("Catálogo unificado: %d trios de %d fontes", len(indice), len(FONTES))
    _indice_cache = indice
    return indice


def invalidar_cache() -> None:
    """Depois de uma coleta ou de editar um CSV de fonte à mão."""
    global _indice_cache
    _indice_cache = None


# ── Decisões da curadoria ────────────────────────────────────────────────────

def carregar_decisoes() -> dict[tuple[str, str, str], dict[str, Any]]:
    """Decisões gravadas, indexadas pelo trio de ORIGEM."""
    if not CATALOGO_DEFINITIVO_CSV.exists():
        return {}
    decisoes: dict[tuple[str, str, str], dict[str, Any]] = {}
    with open(CATALOGO_DEFINITIVO_CSV, encoding="utf-8", newline="") as f:
        for l in csv.DictReader(f):
            chave = (l.get("marca_origem", ""), l.get("modelo_origem", ""),
                     l.get("versao_origem", ""))
            decisoes[chave] = {
                "marca": l.get("marca", ""),
                "modelo": l.get("modelo", ""),
                "versao": l.get("versao", ""),
                "ano_min": _inteiro(l.get("ano_min")),
                "ano_max": _inteiro(l.get("ano_max")),
                "situacao": l.get("situacao", "pendente"),
                "quando": l.get("quando", ""),
            }
    return decisoes


def _gravar_decisoes(decisoes: dict[tuple[str, str, str], dict[str, Any]]) -> None:
    """Reescreve o arquivo inteiro. São milhares de linhas, não milhões."""
    CATALOGO_DEFINITIVO_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(CATALOGO_DEFINITIVO_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_DEFINITIVO)
        w.writeheader()
        for (mo, mdo, vo), d in sorted(decisoes.items()):
            w.writerow({
                "marca_origem": mo, "modelo_origem": mdo, "versao_origem": vo,
                "marca": d["marca"], "modelo": d["modelo"], "versao": d["versao"],
                "ano_min": d["ano_min"] if d["ano_min"] is not None else "",
                "ano_max": d["ano_max"] if d["ano_max"] is not None else "",
                "situacao": d["situacao"], "quando": d["quando"],
            })


def decidir(
    marca_origem: str, modelo_origem: str, versao_origem: str,
    situacao: str,
    marca: Optional[str] = None, modelo: Optional[str] = None,
    versao: Optional[str] = None,
    ano_min: Optional[int] = None, ano_max: Optional[int] = None,
) -> dict[str, Any]:
    """
    Grava (ou refaz) a decisão sobre um trio.

    `situacao` "pendente" APAGA a decisão em vez de gravar uma linha inerte:
    voltar atrás tem que devolver a linha ao estado original, e uma linha
    "pendente" no arquivo seria indistinguível de curadoria feita.

    Os campos de texto em branco herdam a origem - editar só os anos é o caso
    mais comum, e obrigar a reenviar o nome convidaria a divergência.
    """
    if situacao not in SITUACOES:
        raise ValueError(f"Situação inválida: {situacao!r}. Use {SITUACOES}.")

    chave = (normalizar_texto(marca_origem), normalizar_texto(modelo_origem),
             normalizar_texto(versao_origem or ""))
    if not chave[0] or not chave[1]:
        raise ValueError("Marca e modelo de origem são obrigatórios.")

    if chave not in construir_indice():
        raise ValueError(f"Trio não existe no catálogo unificado: {chave}")

    decisoes = carregar_decisoes()

    if situacao == "pendente":
        decisoes.pop(chave, None)
        _gravar_decisoes(decisoes)
        return {"situacao": "pendente", "removida": True}

    if ano_min is not None and ano_max is not None and ano_min > ano_max:
        raise ValueError(f"Faixa invertida: {ano_min} > {ano_max}.")

    decisoes[chave] = {
        "marca": normalizar_texto(marca) if marca else chave[0],
        "modelo": normalizar_texto(modelo) if modelo else chave[1],
        "versao": normalizar_texto(versao) if versao is not None else chave[2],
        "ano_min": ano_min,
        "ano_max": ano_max,
        "situacao": situacao,
        "quando": date.today().isoformat(),
    }
    _gravar_decisoes(decisoes)
    return {"situacao": situacao, **decisoes[chave]}


# ── Montagem das linhas pra tela ─────────────────────────────────────────────

def _montar_linha(bruta: dict[str, Any], decisao: Optional[dict[str, Any]]) -> dict[str, Any]:
    faixas = bruta["fontes"]
    minimos = [f["ano_min"] for f in faixas.values() if f["ano_min"] is not None]
    maximos = [f["ano_max"] for f in faixas.values() if f["ano_max"] is not None]

    linha = {
        # A origem é a chave: é por ela que a decisão volta ao servidor.
        "marca_origem": bruta["marca"],
        "modelo_origem": bruta["modelo"],
        "versao_origem": bruta["versao"],
        # O que vale hoje - a curadoria sobrepõe a fonte.
        "marca": bruta["marca"],
        "modelo": bruta["modelo"],
        "versao": bruta["versao"],
        "ano_min": min(minimos) if minimos else None,
        "ano_max": max(maximos) if maximos else None,
        "n_anuncios": bruta["n_anuncios"],
        # Ordenadas por FONTES pra o crachá mais forte vir primeiro.
        "fontes": [f for f in FONTES if f in faixas],
        # A faixa de cada fonte viaja junto: quando duas discordam, quem tria
        # precisa ver as duas, não um número já achatado.
        "anos_por_fonte": {
            f: [faixas[f]["ano_min"], faixas[f]["ano_max"]]
            for f in FONTES if f in faixas
        },
        "situacao": "pendente",
        "editado": False,
        "quando": "",
    }

    if decisao:
        linha["situacao"] = decisao["situacao"]
        linha["quando"] = decisao["quando"]
        linha["marca"] = decisao["marca"] or linha["marca"]
        linha["modelo"] = decisao["modelo"] or linha["modelo"]
        linha["versao"] = decisao["versao"]
        if decisao["ano_min"] is not None:
            linha["ano_min"] = decisao["ano_min"]
        if decisao["ano_max"] is not None:
            linha["ano_max"] = decisao["ano_max"]
        linha["editado"] = (
            (linha["marca"], linha["modelo"], linha["versao"])
            != (bruta["marca"], bruta["modelo"], bruta["versao"])
            or decisao["ano_min"] is not None
            or decisao["ano_max"] is not None
        )
    return linha


# Ordem padrão: quem tem mais anúncio primeiro. Triar 20 mil linhas é
# inviável, e ordenar por relevância faz o esforço render - as combinações
# com anúncio são as que afetam o índice publicado.
ORDENS = {
    "relevancia": lambda l: (-l["n_anuncios"], l["marca"], l["modelo"], l["versao"]),
    "alfabetica": lambda l: (l["marca"], l["modelo"], l["versao"]),
    "fontes": lambda l: (len(l["fontes"]), -l["n_anuncios"]),
}


def listar(
    marca: Optional[str] = None,
    busca: Optional[str] = None,
    fonte: Optional[str] = None,
    situacao: Optional[str] = None,
    so_com_anuncios: bool = False,
    apenas_uma_fonte: bool = False,
    ordem: str = "relevancia",
    pagina: int = 1,
    por_pagina: int = 100,
) -> dict[str, Any]:
    """
    Uma fatia do catálogo unificado, filtrada e paginada.

    `apenas_uma_fonte` isola os 13 mil trios que uma fonte só avaliza - é
    onde mora tanto o achado legítimo quanto o lixo, e é o recorte que mais
    precisa de olho humano.
    """
    indice = construir_indice()
    decisoes = carregar_decisoes()

    busca_n = normalizar_texto(busca) if busca else None
    marca_n = normalizar_texto(marca) if marca else None

    linhas = []
    for chave, bruta in indice.items():
        if marca_n and bruta["marca"] != marca_n:
            continue
        if fonte and fonte not in bruta["fontes"]:
            continue
        if so_com_anuncios and not bruta["n_anuncios"]:
            continue
        if apenas_uma_fonte and len(bruta["fontes"]) != 1:
            continue
        if busca_n and busca_n not in f"{bruta['marca']} {bruta['modelo']} {bruta['versao']}":
            continue

        linha = _montar_linha(bruta, decisoes.get(chave))
        if situacao and linha["situacao"] != situacao:
            continue
        linhas.append(linha)

    linhas.sort(key=ORDENS.get(ordem, ORDENS["relevancia"]))

    total = len(linhas)
    por_pagina = max(1, min(int(por_pagina), 500))
    pagina = max(1, int(pagina))
    inicio = (pagina - 1) * por_pagina

    return {
        "linhas": linhas[inicio:inicio + por_pagina],
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "paginas": max(1, (total + por_pagina - 1) // por_pagina),
    }


def resumo() -> dict[str, Any]:
    """Contagens do topo da tela - o mapa de quanto falta triar."""
    indice = construir_indice()
    decisoes = carregar_decisoes()

    por_situacao = {s: 0 for s in SITUACOES}
    por_fonte = {f: 0 for f in FONTES}
    com_anuncios = uma_fonte = 0

    for chave, bruta in indice.items():
        d = decisoes.get(chave)
        por_situacao[d["situacao"] if d else "pendente"] += 1
        for f in bruta["fontes"]:
            por_fonte[f] += 1
        if bruta["n_anuncios"]:
            com_anuncios += 1
        if len(bruta["fontes"]) == 1:
            uma_fonte += 1

    return {
        "total": len(indice),
        "marcas": len({b["marca"] for b in indice.values()}),
        "pares": len({(b["marca"], b["modelo"]) for b in indice.values()}),
        "por_situacao": por_situacao,
        "por_fonte": por_fonte,
        "com_anuncios": com_anuncios,
        "uma_fonte": uma_fonte,
        "fontes_rotulos": FONTES,
    }


def marcas_disponiveis() -> list[dict[str, Any]]:
    """Pro dropdown de marca, com a contagem de trios de cada uma."""
    contagem: dict[str, int] = {}
    for bruta in construir_indice().values():
        contagem[bruta["marca"]] = contagem.get(bruta["marca"], 0) + 1
    return [{"marca": m, "qtd": n} for m, n in sorted(contagem.items())]


COLUNAS_EXPORT = ["marca", "modelo", "versao", "ano_min", "ano_max",
                  "n_anuncios", "fontes", "quando"]


def exportar_definitivo(
    situacao: str = "confirmado",
) -> tuple[list[str], list[dict[str, Any]]]:
    """
    O catálogo curado como CSV. Por padrão só o que foi CONFIRMADO: o
    arquivo é o resultado da curadoria, não o retrato do trabalho em
    andamento.

    `situacao` permite baixar o descartado (útil pra revisar o que se jogou
    fora) ou o pendente (a fila de trabalho). Devolve dicionários porque é
    o que `_csv_streaming` consome.
    """
    if situacao not in SITUACOES:
        raise ValueError(f"Situação inválida: {situacao!r}. Use {SITUACOES}.")

    indice = construir_indice()
    decisoes = carregar_decisoes()
    linhas: list[dict[str, Any]] = []
    for chave, bruta in indice.items():
        d = decisoes.get(chave)
        atual = d["situacao"] if d else "pendente"
        if atual != situacao:
            continue
        l = _montar_linha(bruta, d)
        linhas.append({
            "marca": l["marca"], "modelo": l["modelo"], "versao": l["versao"],
            "ano_min": l["ano_min"], "ano_max": l["ano_max"],
            "n_anuncios": l["n_anuncios"], "fontes": "|".join(l["fontes"]),
            "quando": l["quando"],
        })
    linhas.sort(key=lambda r: (r["marca"], r["modelo"], r["versao"]))
    return COLUNAS_EXPORT, linhas
