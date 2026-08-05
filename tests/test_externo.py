"""
Testes do catálogo de referência externo (src/catalog/externo.py).

Cobre a reconciliação de marca, a busca de evidência e o efeito das decisões
de alias. Os CSVs de dados reais são usados só quando existem; a lógica de
busca é testada contra fixtures em tmp_path, pra não depender de coleta.
"""
import csv

import pytest

from src.catalog import externo


@pytest.fixture(autouse=True)
def limpar_cache():
    externo.resetar_cache()
    yield
    externo.resetar_cache()


@pytest.fixture()
def fontes(tmp_path, monkeypatch):
    """Aponta os CSVs do módulo pra fixtures controladas."""
    base = tmp_path / "base_intl.csv"
    with open(base, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["marca", "modelo", "ano_min", "ano_max", "anos_distintos", "versoes", "fonte"])
        w.writerow(["LAND ROVER", "RANGE ROVER", 1970, 1996, 27, "", "the-oldtimers.com"])
        w.writerow(["FORD", "GALAXIE", 1959, 1974, 16, "500", "the-oldtimers.com"])
        w.writerow(["TRIUMPH", "TR7", 1975, 1981, 7, "", "the-oldtimers.com"])

    vocab = tmp_path / "vocab.csv"
    with open(vocab, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["marca", "modelo", "geracoes", "trims", "carrocerias", "n_urls", "fonte"])
        w.writerow(["BMW", "3 SERIES", "E30|E36", "M3", "COUPE", 12, "classic.com"])

    aliases = tmp_path / "aliases.csv"
    with open(aliases, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["marca", "modelo_ptbr", "modelo_intl", "regra", "fonte", "n_anuncios", "similaridade"])
        w.writerow(["BMW", "SERIE 3", "3 SERIES", "serie_n", "classic.com", 10, 0.667])
        w.writerow(["TRIUMPH", "TR 7", "TR7", "espacamento", "the-oldtimers.com", 1, 0.9])

    decisoes = tmp_path / "decisoes.csv"

    monkeypatch.setattr(externo, "BASE_INTL_CSV", base)
    monkeypatch.setattr(externo, "VOCABULARIO_CSV", vocab)
    monkeypatch.setattr(externo, "ALIASES_INTL_CSV", aliases)
    monkeypatch.setattr(externo, "ALIASES_DECISOES_CSV", decisoes)
    externo.resetar_cache()
    return tmp_path


# ── Reconciliação de marca ──────────────────────

def test_marca_canonica_resolve_separador():
    """A fonte grafa com hífen; o catálogo do projeto, com espaço."""
    assert externo.marca_canonica("Alfa-Romeo") == "ALFA ROMEO"
    assert externo.marca_canonica("Aston-Martin") == "ASTON MARTIN"
    assert externo.marca_canonica("De-Tomaso") == "DE TOMASO"


def test_marca_canonica_preserva_hifen_do_catalogo():
    """MERCEDES-BENZ é hifenizada NO catálogo — não virar espaço."""
    assert externo.marca_canonica("mercedes-benz") == "MERCEDES-BENZ"


def test_marca_canonica_desconhecida_volta_normalizada():
    """Marca europeia sem presença no Brasil: só normaliza, não inventa."""
    assert externo.marca_canonica("Wartburg") == "WARTBURG"


def test_marca_canonica_nao_reatribui_marca_estrangeira():
    """
    Regressão: `sanear_marca_modelo` transformava 'Alpine' em 'SUNBEAM'
    (Alpine é modelo Sunbeam no catálogo brasileiro). A reconciliação por
    forma alfanumérica não pode fazer isso.
    """
    assert externo.marca_canonica("Alpine") == "ALPINE"


def test_chave_alfanumerica():
    assert externo.chave_alfanumerica("Alfa-Romeo") == "ALFAROMEO"
    assert externo.chave_alfanumerica("D-20") == "D20"


# ── Busca de evidência ──────────────────────────

def test_evidencia_literal(fontes):
    ev = externo.evidencia_externa("TRIUMPH", "TR7")
    assert ev["estrategia"] == "literal"
    assert (ev["ano_min"], ev["ano_max"]) == (1975, 1981)
    assert ev["suspeita"] == ""


def test_evidencia_prefixo_trim_no_banco(fontes):
    """'GALAXIE 500' -> 'GALAXIE': o banco tem o trim junto. Legítimo."""
    ev = externo.evidencia_externa("FORD", "GALAXIE 500")
    assert ev["modelo_fonte"] == "GALAXIE"
    assert ev["estrategia"] == "prefixo"
    assert ev["suspeita"] == ""


def test_evidencia_prefixo_detecta_modelo_truncado(fontes):
    """'RANGE' -> 'RANGE ROVER': a fonte tem o nome MAIS longo. Bug no banco."""
    ev = externo.evidencia_externa("LAND ROVER", "RANGE")
    assert ev["modelo_fonte"] == "RANGE ROVER"
    assert ev["suspeita"] == "modelo_truncado"


def test_evidencia_por_alias(fontes):
    """O banco grafa em português; a fonte, em inglês."""
    ev = externo.evidencia_externa("BMW", "SERIE 3")
    assert ev["modelo_fonte"] == "3 SERIES"
    assert ev["estrategia"] == "alias"
    assert ev["fonte"] == "classic.com"
    # classic.com não tem ano: a taxonomia dele é só de nomes.
    assert ev["ano_min"] is None


def test_evidencia_marca_desconhecida_volta_none(fontes):
    """Carro nacional: nenhuma fonte conhece, e isso é o esperado."""
    assert externo.evidencia_externa("GURGEL", "XEF") is None


def test_evidencia_modelo_desconhecido_volta_none(fontes):
    assert externo.evidencia_externa("FORD", "PREMIO") is None


def test_prefixo_curto_nao_conta_como_evidencia(fontes):
    """Prefixo de 1-2 letras casaria com quase tudo — não é evidência."""
    assert externo.evidencia_externa("FORD", "GA") is None


# ── Decisões de alias ───────────────────────────

def test_alias_rejeitado_sai_da_busca(fontes):
    assert externo.evidencia_externa("BMW", "SERIE 3") is not None

    externo.registrar_decisao_alias("BMW", "SERIE 3", "rejeitado")

    assert ("BMW", "SERIE 3") not in externo.carregar_aliases()
    assert externo.evidencia_externa("BMW", "SERIE 3") is None


def test_alias_aprovado_continua_valendo(fontes):
    externo.registrar_decisao_alias("BMW", "SERIE 3", "aprovado")
    assert externo.evidencia_externa("BMW", "SERIE 3") is not None


def test_ultima_decisao_vence(fontes):
    """O arquivo é append-only: rejeitar e depois aprovar deve valer aprovado."""
    externo.registrar_decisao_alias("BMW", "SERIE 3", "rejeitado")
    externo.registrar_decisao_alias("BMW", "SERIE 3", "aprovado")
    assert externo.carregar_decisoes_alias()[("BMW", "SERIE 3")] == "aprovado"
    assert externo.evidencia_externa("BMW", "SERIE 3") is not None


def test_decisao_invalida_rejeitada(fontes):
    with pytest.raises(ValueError):
        externo.registrar_decisao_alias("BMW", "SERIE 3", "talvez")


def test_listar_aliases_traz_decisao(fontes):
    externo.registrar_decisao_alias("BMW", "SERIE 3", "rejeitado")
    por_par = {(a["marca"], a["modelo_ptbr"]): a for a in externo.listar_aliases()}
    assert por_par[("BMW", "SERIE 3")]["decisao"] == "rejeitado"
    assert por_par[("TRIUMPH", "TR 7")]["decisao"] == ""


# ── Arquivo ausente degrada pra vazio ───────────

def test_csv_ausente_nao_quebra(tmp_path, monkeypatch):
    monkeypatch.setattr(externo, "BASE_INTL_CSV", tmp_path / "nao_existe.csv")
    monkeypatch.setattr(externo, "VOCABULARIO_CSV", tmp_path / "nao_existe2.csv")
    monkeypatch.setattr(externo, "ALIASES_INTL_CSV", tmp_path / "nao_existe3.csv")
    monkeypatch.setattr(externo, "ALIASES_DECISOES_CSV", tmp_path / "nao_existe4.csv")
    externo.resetar_cache()

    assert externo.carregar_base_intl() == {}
    assert externo.carregar_vocabulario() == {}
    assert externo.listar_aliases() == []
    assert externo.evidencia_externa("FORD", "GALAXIE") is None
