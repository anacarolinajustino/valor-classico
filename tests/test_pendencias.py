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


# ── Versões a conferir (auditoria de versão 2026-08-05) ──────────────────

class TestVersoesPendentes:
    """
    A fila de versão só existe porque o catálogo da Webmotors é incompleto:
    70,8% dos anúncios com versão batiam com ele, e o grosso do resto é trim
    nacional real que ele não lista. Os testes cobrem a classificação, não a
    consulta.
    """

    LINHAS = [
        {"marca": "FORD", "modelo": "CORCEL II", "versao": "L", "n": 141},
        {"marca": "CHEVROLET", "modelo": "CORVETTE", "versao": "C1", "n": 6},
        {"marca": "FIAT", "modelo": "PREMIO", "versao": "CS", "n": 24},
        {"marca": "VOLKSWAGEN", "modelo": "GOL", "versao": "CL", "n": 99},
    ]

    def _montar(self, monkeypatch):
        import src.catalog.externo as externo
        import src.catalog.loader as loader
        import src.pipeline.persistence as persistence

        monkeypatch.setattr(loader, "carregar_catalogo", lambda *a, **k: {})
        monkeypatch.setattr(loader, "_indice_trim", lambda: {
            ("FORD", "CORCEL II"): {"GL", "LDO", "LUXO"},   # tem vocab, sem "L"
            ("CHEVROLET", "CORVETTE"): {"STINGRAY"},
            ("VOLKSWAGEN", "GOL"): {"CL", "GL"},            # "CL" é conhecida
            # FIAT PREMIO ausente de propósito: par sem vocabulário nenhum
        })
        monkeypatch.setattr(externo, "carregar_vocabulario", lambda *a, **k: {
            ("CHEVROLET", "CORVETTE"): {
                "geracoes": ["C1", "C2", "C3"], "trims": [], "carrocerias": []},
        })
        monkeypatch.setattr(externo, "evidencia_externa", lambda mk, md: None)

        class _Cur:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, *a, **k): pass
            def fetchall(self): return TestVersoesPendentes.LINHAS

        class _Conn:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def cursor(self): return _Cur()

        monkeypatch.setattr(persistence, "_connect", lambda: _Conn())

    def test_versao_conhecida_nao_entra_na_fila(self, monkeypatch):
        self._montar(monkeypatch)
        d = pendencias.listar_versoes_pendentes()
        assert ("VOLKSWAGEN", "GOL", "CL") not in {
            (v["marca"], v["modelo"], v["versao"]) for v in d["versoes"]
        }

    def test_trim_provavel(self, monkeypatch):
        self._montar(monkeypatch)
        d = pendencias.listar_versoes_pendentes()
        alvo = next(v for v in d["versoes"] if v["versao"] == "L")
        assert alvo["sugestao"] == "trim_provavel"
        # O vocabulário conhecido vai junto pra usuária comparar sem sair da tela.
        assert "GL" in alvo["vocabulario"]

    def test_geracao_identificada_pela_fonte_externa(self, monkeypatch):
        self._montar(monkeypatch)
        d = pendencias.listar_versoes_pendentes()
        alvo = next(v for v in d["versoes"] if v["versao"] == "C1")
        assert alvo["sugestao"] == "geracao"

    def test_par_sem_vocabulario(self, monkeypatch):
        self._montar(monkeypatch)
        d = pendencias.listar_versoes_pendentes()
        alvo = next(v for v in d["versoes"] if v["versao"] == "CS")
        assert alvo["sugestao"] == "sem_referencia"
        assert alvo["vocabulario"] == []

    def test_totais_e_contagem_de_anuncios(self, monkeypatch):
        self._montar(monkeypatch)
        d = pendencias.listar_versoes_pendentes()
        assert d["total"] == 3                      # GOL CL ficou de fora
        assert d["total_anuncios"] == 141 + 6 + 24
        assert d["totais"] == {"trim_provavel": 1, "geracao": 1, "sem_referencia": 1}


class TestSemVersao:
    """
    Aba diagnóstica: separa bug de extração ("o trim está no título e ficou
    de fora") de limite da fonte ("o título só tem spec"). A distinção é o
    ponto todo — sem ela os 14.213 anúncios sem versão são só um número.
    """

    LINHAS = [
        # trim GL está no título e a versão ficou vazia -> recuperável
        {"marca": "VOLKSWAGEN", "modelo": "GOL", "fonte": "mercadolivre",
         "titulo": "Volkswagen Gol 1.8 Mi Gl 8v Gasolina 2p Manual"},
        # só spec, nenhum trim -> a fonte não informa
        {"marca": "VOLKSWAGEN", "modelo": "GOL", "fonte": "webmotors",
         "titulo": "VOLKSWAGEN GOL 1.0 8V GASOLINA 2P MANUAL 1996"},
        # carroceria NÃO conta como trim perdido: vai pra obs por desenho
        {"marca": "VOLKSWAGEN", "modelo": "KOMBI", "fonte": "olx",
         "titulo": "Volkswagen Kombi 1.6 Pick-up Cs 8v Gasolina"},
        # par sem vocabulário no catálogo
        {"marca": "GURGEL", "modelo": "XEF", "fonte": "olx",
         "titulo": "Gurgel Xef 1980"},
    ]

    def _montar(self, monkeypatch, tmp_path):
        import src.catalog.loader as loader
        import src.pipeline.persistence as persistence

        monkeypatch.setattr(pendencias, "DISPENSADAS_CSV", tmp_path / "d.csv")
        monkeypatch.setattr(loader, "carregar_catalogo", lambda *a, **k: {})
        monkeypatch.setattr(loader, "_indice_trim", lambda: {
            ("VOLKSWAGEN", "GOL"): {"GL", "GLI", "PLUS"},
            ("VOLKSWAGEN", "KOMBI"): {"PICK-UP", "STD"},
        })

        class _Cur:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, *a, **k): pass
            def fetchall(self): return TestSemVersao.LINHAS

        class _Conn:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def cursor(self): return _Cur()

        monkeypatch.setattr(persistence, "_connect", lambda: _Conn())

    def test_classifica_as_quatro_causas(self, monkeypatch, tmp_path):
        self._montar(monkeypatch, tmp_path)
        d = pendencias.listar_sem_versao()
        assert d["totais"] == {
            "recuperavel": 1, "fonte_nao_diz": 2, "sem_vocabulario": 1,
        }

    def test_carroceria_nao_conta_como_trim_perdido(self, monkeypatch, tmp_path):
        """PICK-UP está no vocabulário mas vai pra `obs` — não é versão perdida."""
        self._montar(monkeypatch, tmp_path)
        d = pendencias.listar_sem_versao()
        kombi = next(g for g in d["grupos"] if g["modelo"] == "KOMBI")
        assert kombi["recuperavel"] == 0
        assert kombi["fonte_nao_diz"] == 1

    def test_amostra_so_do_recuperavel(self, monkeypatch, tmp_path):
        """A amostra é a prova de que o trim está no título; só ela importa."""
        self._montar(monkeypatch, tmp_path)
        d = pendencias.listar_sem_versao()
        gol = next(g for g in d["grupos"] if g["modelo"] == "GOL")
        assert len(gol["amostras"]) == 1
        assert gol["amostras"][0]["trim"] == "GL"
        assert "Gl" in gol["amostras"][0]["titulo"]

    def test_ordena_por_recuperavel(self, monkeypatch, tmp_path):
        """Mais recuperável primeiro: é onde um ajuste rende mais anúncios."""
        self._montar(monkeypatch, tmp_path)
        d = pendencias.listar_sem_versao()
        assert d["grupos"][0]["modelo"] == "GOL"

    def test_agrupa_por_par(self, monkeypatch, tmp_path):
        self._montar(monkeypatch, tmp_path)
        d = pendencias.listar_sem_versao()
        gol = next(g for g in d["grupos"] if g["modelo"] == "GOL")
        assert gol["qtd"] == 2
        assert gol["fontes"] == ["mercadolivre", "webmotors"]
        assert d["total_grupos"] == 3
        assert d["total_anuncios"] == 4
