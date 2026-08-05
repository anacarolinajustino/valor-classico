"""
Testes da fila de pendências (src/pipeline/pendencias.py).

A base de pares vem de `listar_anuncios_a_verificar`, que consulta o banco —
aqui ela é substituída por uma fixture, porque o que se testa é a camada de
classificação e dispensa, não a consulta.
"""
import csv

import pytest

from src.pipeline import pendencias


PARES_FALSOS = {
    "pares": [
        {"marca": "LAND ROVER", "modelo": "RANGE", "qtd": 5},
        {"marca": "TRIUMPH", "modelo": "TR7", "qtd": 3},
        {"marca": "GURGEL", "modelo": "XEF", "qtd": 7},
    ],
    "marcas_catalogo": ["FORD", "GURGEL"],
    "modelos_catalogo": {"FORD": ["GALAXIE"]},
    "total_pares": 3,
    "total_anuncios": 15,
}

EVIDENCIAS = {
    ("LAND ROVER", "RANGE"): {
        "modelo_fonte": "RANGE ROVER", "estrategia": "prefixo",
        "fonte": "the-oldtimers.com", "ano_min": 1970, "ano_max": 1996,
        "suspeita": "modelo_truncado",
    },
    ("TRIUMPH", "TR7"): {
        "modelo_fonte": "TR7", "estrategia": "literal",
        "fonte": "the-oldtimers.com", "ano_min": 1975, "ano_max": 1981,
        "suspeita": "",
    },
}


@pytest.fixture()
def fila(tmp_path, monkeypatch):
    """Fila isolada: pares falsos e arquivo de dispensas em tmp_path."""
    monkeypatch.setattr(pendencias, "DISPENSADAS_CSV", tmp_path / "dispensadas.csv")
    monkeypatch.setattr(
        pendencias, "evidencia_externa",
        lambda marca, modelo: EVIDENCIAS.get((marca, modelo)),
    )
    import src.pipeline.persistence as persistence
    monkeypatch.setattr(
        persistence, "listar_anuncios_a_verificar", lambda: PARES_FALSOS
    )
    return tmp_path


# ── Classificação ───────────────────────────────

def test_classifica_pelos_tres_tipos(fila):
    d = pendencias.listar_pendencias()
    por_par = {(p["marca"], p["modelo"]): p for p in d["pares"]}

    assert por_par[("LAND ROVER", "RANGE")]["tipo"] == pendencias.TIPO_CORRIGIR
    assert por_par[("TRIUMPH", "TR7")]["tipo"] == pendencias.TIPO_CONFIRMADO
    assert por_par[("GURGEL", "XEF")]["tipo"] == pendencias.TIPO_SEM_EVIDENCIA


def test_totais_por_tipo(fila):
    d = pendencias.listar_pendencias()
    assert d["totais"] == {
        pendencias.TIPO_CORRIGIR: 1,
        pendencias.TIPO_CONFIRMADO: 1,
        pendencias.TIPO_SEM_EVIDENCIA: 1,
    }
    assert d["total_pares"] == 3
    assert d["total_anuncios"] == 15


def test_sugestao_so_para_nome_truncado(fila):
    """
    A sugestão pré-preenche o campo de correção. Só faz sentido quando a
    fonte tem o nome completo que falta — num par confirmado, sugerir o
    próprio nome seria ruído.
    """
    por_par = {(p["marca"], p["modelo"]): p for p in pendencias.listar_pendencias()["pares"]}
    assert por_par[("LAND ROVER", "RANGE")]["sugestao"] == "RANGE ROVER"
    assert por_par[("TRIUMPH", "TR7")]["sugestao"] == ""
    assert por_par[("GURGEL", "XEF")]["sugestao"] == ""


def test_ordem_prioriza_acao_clara(fila):
    """Corrigir primeiro, sem_evidencia por último (exige pesquisa manual)."""
    tipos = [p["tipo"] for p in pendencias.listar_pendencias()["pares"]]
    assert tipos == [
        pendencias.TIPO_CORRIGIR,
        pendencias.TIPO_CONFIRMADO,
        pendencias.TIPO_SEM_EVIDENCIA,
    ]


def test_evidencia_vem_junto(fila):
    p = next(p for p in pendencias.listar_pendencias()["pares"] if p["marca"] == "TRIUMPH")
    assert p["evidencia"]["ano_min"] == 1975
    assert p["evidencia"]["fonte"] == "the-oldtimers.com"


# ── Dispensa ────────────────────────────────────

def test_dispensar_tira_da_fila(fila):
    pendencias.dispensar("GURGEL", "XEF", motivo="carro nacional, esta certo")

    d = pendencias.listar_pendencias()
    assert ("GURGEL", "XEF") not in {(p["marca"], p["modelo"]) for p in d["pares"]}
    assert d["total_pares"] == 2
    assert d["total_dispensadas"] == 1


def test_dispensadas_aparecem_quando_pedido(fila):
    pendencias.dispensar("GURGEL", "XEF")

    d = pendencias.listar_pendencias(incluir_dispensadas=True)
    alvo = next(p for p in d["pares"] if p["marca"] == "GURGEL")
    assert alvo["dispensada"] is True
    assert d["total_pares"] == 3


def test_restaurar_devolve_para_fila(fila):
    pendencias.dispensar("GURGEL", "XEF")
    pendencias.restaurar("GURGEL", "XEF")

    d = pendencias.listar_pendencias()
    assert ("GURGEL", "XEF") in {(p["marca"], p["modelo"]) for p in d["pares"]}
    assert d["total_dispensadas"] == 0


def test_dispensa_independe_do_tipo(fila, monkeypatch):
    """
    A chave de dispensa é (marca, modelo), sem o tipo: se uma fonte nova
    reclassificar o par, a decisão "já olhei, deixa como está" continua valendo.
    """
    pendencias.dispensar("GURGEL", "XEF")
    monkeypatch.setattr(
        pendencias, "evidencia_externa",
        lambda marca, modelo: EVIDENCIAS.get((marca, modelo)) or {
            "modelo_fonte": "XEF", "estrategia": "literal", "fonte": "nova.com",
            "ano_min": 1980, "ano_max": 1990, "suspeita": "",
        },
    )
    d = pendencias.listar_pendencias()
    assert ("GURGEL", "XEF") not in {(p["marca"], p["modelo"]) for p in d["pares"]}


def test_dispensar_sem_marca_falha(fila):
    with pytest.raises(ValueError):
        pendencias.dispensar("", "XEF")


def test_arquivo_de_dispensa_e_append_only(fila):
    """Guarda o histórico: dispensar, restaurar e dispensar de novo = 3 linhas."""
    pendencias.dispensar("GURGEL", "XEF")
    pendencias.restaurar("GURGEL", "XEF")
    pendencias.dispensar("GURGEL", "XEF")

    with open(pendencias.DISPENSADAS_CSV, encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    assert len(linhas) == 3
    assert [l["acao"] for l in linhas] == ["dispensar", "restaurar", "dispensar"]
    assert pendencias.carregar_dispensadas() == {("GURGEL", "XEF")}


def test_dispensadas_sem_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(pendencias, "DISPENSADAS_CSV", tmp_path / "nao_existe.csv")
    assert pendencias.carregar_dispensadas() == set()


# ── Aliases pendentes ───────────────────────────

def test_so_fuzzy_entra_na_fila(monkeypatch):
    """Traduções de regra fixa não são palpite — não precisam de conferência."""
    monkeypatch.setattr(
        "src.catalog.externo.listar_aliases",
        lambda: [
            {"marca": "BMW", "modelo_ptbr": "SERIE 3", "modelo_intl": "3 SERIES",
             "regra": "serie_n", "fonte": "classic.com", "n_anuncios": 10,
             "similaridade": 0.667, "decisao": ""},
            {"marca": "FORD", "modelo_ptbr": "CRISTLINE", "modelo_intl": "CRESTLINE",
             "regra": "fuzzy", "fonte": "the-oldtimers.com", "n_anuncios": 1,
             "similaridade": 0.889, "decisao": ""},
        ],
    )
    d = pendencias.listar_aliases_pendentes()
    assert [a["modelo_ptbr"] for a in d["aliases"]] == ["CRISTLINE"]
    assert d["total_pendentes"] == 1
    assert d["total_deterministicos"] == 1


def test_alias_ja_decidido_sai_da_fila(monkeypatch):
    monkeypatch.setattr(
        "src.catalog.externo.listar_aliases",
        lambda: [
            {"marca": "FORD", "modelo_ptbr": "CRISTLINE", "modelo_intl": "CRESTLINE",
             "regra": "fuzzy", "fonte": "x", "n_anuncios": 1,
             "similaridade": 0.889, "decisao": "aprovado"},
        ],
    )
    assert pendencias.listar_aliases_pendentes()["aliases"] == []
    assert pendencias.listar_aliases_pendentes(incluir_decididos=True)["aliases"]
