"""
Testes de src/pipeline/persistence.py (AC-P01 a AC-P06).
Requer DATABASE_URL configurada; pulados automaticamente se ausente.
"""
from __future__ import annotations

import os

import psycopg2
import psycopg2.extras
import pytest

from src.pipeline.persistence import (
    ANO_CORTE_CLASSICO,
    CHART_MIN_DIAS,
    excluir_marca_modelo,
    get_dashboard_stats,
    init_db,
    listar_anuncios,
    upsert_anuncios,
    upsert_preco,
    log_search,
    get_historico,
    get_mais_pesquisados,
)
from src.pipeline.schema import Anuncio

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]


def _raw_conn():
    return psycopg2.connect(DATABASE_URL)


# ── Fixture: trunca tabelas antes de cada teste ───────────────────────────────

@pytest.fixture(autouse=True)
def limpar_tabelas():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL não configurada")
    init_db()
    conn = _raw_conn()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE historico_precos, search_log, anuncios RESTART IDENTITY CASCADE")
    conn.commit()
    conn.close()
    yield


# ── AC-P01: init_db cria tabelas sem erro ─────────────────────────────────────

class TestInitDb:
    def test_cria_tabelas(self):
        conn = _raw_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
            """)
            tabelas = {r[0] for r in cur.fetchall()}
        conn.close()
        assert "historico_precos" in tabelas
        assert "search_log" in tabelas

    def test_idempotente(self):
        init_db()  # segunda chamada não deve levantar exceção


# ── AC-P02: upsert_preco — dedup intraday ─────────────────────────────────────

class TestUpsertPreco:
    def test_insere_primeira_linha(self):
        upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 45000.0, 10, hoje="2026-05-30")
        conn = _raw_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM historico_precos")
            count = cur.fetchone()[0]
        conn.close()
        assert count == 1

    def test_segunda_busca_mesmo_dia_nao_duplica(self):
        upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 45000.0, 10, hoje="2026-05-30")
        upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 47000.0, 14, hoje="2026-05-30")
        conn = _raw_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT preco_medio, amostra FROM historico_precos")
            rows = cur.fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["preco_medio"] == 47000.0
        assert rows[0]["amostra"] == 14

    def test_dias_diferentes_geram_linhas_separadas(self):
        upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 45000.0, 10, hoje="2026-05-29")
        upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 47000.0, 12, hoje="2026-05-30")
        conn = _raw_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM historico_precos")
            count = cur.fetchone()[0]
        conn.close()
        assert count == 2

    def test_marca_modelo_uppercased(self):
        upsert_preco("volkswagen", "fusca", 1972, 45000.0, 10, hoje="2026-05-30")
        conn = _raw_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT marca, modelo FROM historico_precos")
            row = cur.fetchone()
        conn.close()
        assert row["marca"] == "VOLKSWAGEN"
        assert row["modelo"] == "FUSCA"


# ── AC-P03: get_historico — chart_ready False com menos de CHART_MIN_DIAS ─────

class TestGetHistoricoChartNotReady:
    def test_chart_not_ready_com_poucos_dias(self):
        for i in range(CHART_MIN_DIAS - 1):
            upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 45000.0 + i * 100, 10,
                         hoje=f"2026-05-{i + 1:02d}")
        resultado = get_historico("VOLKSWAGEN", "FUSCA")
        assert resultado["chart_ready"] is False

    def test_sem_dados_chart_not_ready(self):
        resultado = get_historico("VOLKSWAGEN", "FUSCA")
        assert resultado["chart_ready"] is False
        assert resultado["series"] == []


# ── AC-P04: get_historico — chart_ready True com >= CHART_MIN_DIAS ────────────

class TestGetHistoricoChartReady:
    def _inserir_n_dias(self, n: int):
        for i in range(n):
            upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 45000.0 + i * 200, 10,
                         hoje=f"2026-05-{i + 1:02d}")

    def test_chart_ready_com_exatamente_min_dias(self):
        self._inserir_n_dias(CHART_MIN_DIAS)
        resultado = get_historico("VOLKSWAGEN", "FUSCA")
        assert resultado["chart_ready"] is True

    def test_retorna_no_maximo_10_pontos(self):
        self._inserir_n_dias(15)
        resultado = get_historico("VOLKSWAGEN", "FUSCA")
        assert len(resultado["series"][0]["pontos"]) <= 10

    def test_estrutura_de_pontos(self):
        self._inserir_n_dias(CHART_MIN_DIAS)
        resultado = get_historico("VOLKSWAGEN", "FUSCA")
        ponto = resultado["series"][0]["pontos"][0]
        assert "data" in ponto
        assert "media" in ponto
        assert "amostra" in ponto

    def test_marca_modelo_uppercased_no_retorno(self):
        self._inserir_n_dias(CHART_MIN_DIAS)
        resultado = get_historico("volkswagen", "fusca")
        assert resultado["marca"] == "VOLKSWAGEN"
        assert resultado["modelo"] == "FUSCA"


# ── AC-P05: log_search registra entrada em search_log ────────────────────────

class TestLogSearch:
    def test_registra_busca(self):
        log_search("VOLKSWAGEN", "FUSCA")
        conn = _raw_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM search_log")
            count = cur.fetchone()[0]
        conn.close()
        assert count == 1

    def test_registra_multiplas_buscas(self):
        log_search("VOLKSWAGEN", "FUSCA")
        log_search("VOLKSWAGEN", "FUSCA")
        log_search("FIAT", "PALIO")
        conn = _raw_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM search_log")
            count = cur.fetchone()[0]
        conn.close()
        assert count == 3

    def test_marca_uppercased(self):
        log_search("volkswagen", "fusca")
        conn = _raw_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT marca, modelo FROM search_log")
            row = cur.fetchone()
        conn.close()
        assert row["marca"] == "VOLKSWAGEN"
        assert row["modelo"] == "FUSCA"


# ── AC-P07: upsert_anuncios aplica o corte de ano centralmente ────────────────

def _anuncio(url: str, ano, fonte: str = "teste", marca: str = "VOLKSWAGEN", modelo: str = "FUSCA",
             titulo: str | None = None, versao: str | None = None) -> Anuncio:
    return Anuncio(
        titulo=titulo if titulo is not None else f"Carro {ano}", preco=50000.0, marca=marca, modelo=modelo,
        ano=ano, versao=versao, url=url, fonte=fonte, data_coleta="2026-07-14",
    )


class TestUpsertAnunciosCorteAno:
    def _contar(self) -> int:
        conn = _raw_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM anuncios")
            count = cur.fetchone()[0]
        conn.close()
        return count

    def test_descarta_ano_acima_do_corte(self):
        resultado = upsert_anuncios([
            _anuncio("http://x/1", 1972),
            _anuncio("http://x/2", ANO_CORTE_CLASSICO + 1),
            _anuncio("http://x/3", 2024),
        ])
        assert resultado == {
            "novos": 1, "atualizados": 0, "descartados_ano": 2, "descartados_buggy": 0,
            "descartados_hot_rod": 0,
        }
        assert self._contar() == 1

    def test_ano_no_limite_entra(self):
        resultado = upsert_anuncios([_anuncio("http://x/1", ANO_CORTE_CLASSICO)])
        assert resultado["novos"] == 1
        assert resultado["descartados_ano"] == 0

    def test_ano_none_entra(self):
        resultado = upsert_anuncios([_anuncio("http://x/1", None)])
        assert resultado["novos"] == 1
        assert resultado["descartados_ano"] == 0

    def test_descarta_buggy_na_coleta(self):
        # Buggy é banido do projeto: descartado na coleta, nem entra no banco.
        resultado = upsert_anuncios([
            _anuncio("http://x/1", 1975, marca="VOLKSWAGEN", modelo="FUSCA"),
            _anuncio("http://x/2", 1970, marca="BUGGY", modelo="BUGGY"),
            _anuncio("http://x/3", 1972, marca="BRM", modelo="M-11"),
            _anuncio("http://x/4", 1974, marca="VOLKSWAGEN", modelo="GLASPACBUGGY"),
        ])
        assert resultado["novos"] == 1
        assert resultado["descartados_buggy"] == 3
        assert self._contar() == 1

    def test_descarta_hot_rod_na_coleta(self):
        # Hot rod é banido do projeto (como o buggy): descartado na coleta. É
        # detectado pelo título/versão/modelo — a marca/modelo é legítima (Ford).
        resultado = upsert_anuncios([
            _anuncio("http://x/1", 1975, marca="VOLKSWAGEN", modelo="FUSCA"),
            _anuncio("http://x/2", 1932, marca="FORD", modelo="ROADSTER", titulo="Ford 1932 Roadster Hotrod"),
            _anuncio("http://x/3", 1930, marca="FORD", modelo="TUDOR", titulo="Ford Tudor Hot Rod 1930"),
            _anuncio("http://x/4", 1934, marca="FORD", modelo="34", titulo="Ford 34", versao="HOT ROD"),
        ])
        assert resultado["novos"] == 1
        assert resultado["descartados_hot_rod"] == 3
        assert self._contar() == 1


class TestExcluirMarcaModelo:
    def _contar(self) -> int:
        conn = _raw_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM anuncios")
            n = cur.fetchone()[0]
        conn.close()
        return n

    def test_exclui_todos_do_par(self):
        upsert_anuncios([
            _anuncio("http://x/1", 1975, marca="VOLKSWAGEN", modelo="FUSCA"),
            _anuncio("http://x/2", 1972, marca="VOLKSWAGEN", modelo="T-CROSS"),
            _anuncio("http://x/3", 1972, marca="VOLKSWAGEN", modelo="T-CROSS"),
        ])
        res = excluir_marca_modelo("Volkswagen", "T-Cross")
        assert res["excluidos"] == 2
        assert self._contar() == 1  # o Fusca fica

    def test_casa_modelo_vazio_via_coalesce(self):
        upsert_anuncios([_anuncio("http://x/1", 1970, marca="FORD", modelo="")])
        assert excluir_marca_modelo("Ford", "")["excluidos"] == 1
        assert self._contar() == 0

    def test_marca_vazia_e_erro(self):
        with pytest.raises(ValueError):
            excluir_marca_modelo("", "T-Cross")


# ── AC-P08: get_dashboard_stats agrega os recortes do dashboard ───────────────

class TestGetDashboardStats:
    def _semear(self):
        upsert_anuncios([
            _anuncio("http://x/1", 1975, fonte="olx"),
            _anuncio("http://x/2", 1975, fonte="olx"),
            _anuncio("http://x/3", 1992, fonte="maxicar"),
            _anuncio("http://x/4", None, fonte="maxicar"),
        ])

    def test_kpis_gerais(self):
        self._semear()
        d = get_dashboard_stats()
        assert d["kpis"]["total"] == 4
        assert d["kpis"]["com_ano"] == 3
        assert d["kpis"]["fontes"] == 2
        assert d["kpis"]["preco_mediano"] == 50000.0

    def test_filtro_por_fonte(self):
        self._semear()
        d = get_dashboard_stats(fonte="olx")
        assert d["kpis"]["total"] == 2
        assert [f["fonte"] for f in d["por_fonte"]] == ["olx"]

    def test_por_decada_agrupa(self):
        self._semear()
        d = get_dashboard_stats()
        decadas = {x["decada"]: x["qtd"] for x in d["por_decada"]}
        assert decadas == {1970: 2, 1990: 1}

    def _semear_marcas(self):
        upsert_anuncios([
            _anuncio("http://x/1", 1975, fonte="olx", marca="VOLKSWAGEN", modelo="FUSCA"),
            _anuncio("http://x/2", 1968, fonte="olx", marca="VOLKSWAGEN", modelo="FUSCA"),
            _anuncio("http://x/3", 1980, fonte="olx", marca="VOLKSWAGEN", modelo="KOMBI"),
            _anuncio("http://x/4", 1975, fonte="maxicar", marca="CHEVROLET", modelo="OPALA"),
        ])

    def test_opcoes_marca_conta_sob_outros_filtros(self):
        self._semear_marcas()
        d = get_dashboard_stats()
        marcas = {x["marca"]: x["qtd"] for x in d["opcoes"]["marca"]}
        assert marcas == {"VOLKSWAGEN": 3, "CHEVROLET": 1}

    def test_opcoes_modelo_vazio_sem_marca(self):
        self._semear_marcas()
        d = get_dashboard_stats()
        assert d["opcoes"]["modelo"] == []

    def test_opcoes_modelo_em_cascata_da_marca(self):
        self._semear_marcas()
        d = get_dashboard_stats(marca="volkswagen")
        modelos = {x["modelo"]: x["qtd"] for x in d["opcoes"]["modelo"]}
        assert modelos == {"FUSCA": 2, "KOMBI": 1}

    def test_opcoes_ano_conta_sob_marca_e_modelo(self):
        self._semear_marcas()
        d = get_dashboard_stats(marca="volkswagen", modelo="fusca")
        anos = {x["ano"]: x["qtd"] for x in d["opcoes"]["ano"]}
        assert anos == {1975: 1, 1968: 1}


# ── listar_anuncios: marca/modelo/ano são dropdowns, filtro por igualdade ─────

class TestListarAnuncios:
    def _semear_modelos_parecidos(self):
        upsert_anuncios([
            _anuncio("http://x/1", 1975, fonte="olx", marca="VOLKSWAGEN", modelo="FUSCA 1300"),
            _anuncio("http://x/2", 1976, fonte="olx", marca="VOLKSWAGEN", modelo="FUSCA 1300"),
            _anuncio("http://x/3", 1978, fonte="olx", marca="VOLKSWAGEN", modelo="FUSCA 1300 STANDARD"),
            _anuncio("http://x/4", 1980, fonte="olx", marca="VOLKSWAGEN", modelo="FUSCA 1300L"),
        ])

    def test_modelo_filtra_por_igualdade_nao_por_substring(self):
        # marca/modelo vêm de um dropdown com valores exatos do catálogo
        # (ex.: link "ver anúncios" da tabela de modelos mais anunciados do
        # dashboard, que usa GROUP BY marca, modelo) — não pode trazer
        # "Fusca 1300 Standard"/"1300L" junto, senão a contagem não bate
        # com o card de origem.
        self._semear_modelos_parecidos()
        r = listar_anuncios(marca="VOLKSWAGEN", modelo="FUSCA 1300")
        assert r["total"] == 2
        assert all(row["modelo"] == "FUSCA 1300" for row in r["rows"])

    def test_opcoes_no_retorno_para_popular_os_dropdowns(self):
        self._semear_modelos_parecidos()
        r = listar_anuncios(marca="VOLKSWAGEN")
        modelos = {x["modelo"] for x in r["opcoes"]["modelo"]}
        assert modelos == {"FUSCA 1300", "FUSCA 1300 STANDARD", "FUSCA 1300L"}

    def test_opcoes_marca_nao_fica_presa_ao_modelo_do_link(self):
        # Link "ver anúncios" do dashboard chega com marca+modelo JÁ
        # setados juntos (não em cascata pela UI) — opções de marca não
        # podem ficar restritas ao modelo escolhido, senão qualquer marca
        # que não tem esse modelo específico some do dropdown (bug real:
        # trocar de VOLKSWAGEN pra CHEVROLET ficava impossível).
        upsert_anuncios([
            _anuncio("http://x/1", 1975, fonte="olx", marca="VOLKSWAGEN", modelo="FUSCA 1300"),
            _anuncio("http://x/2", 1975, fonte="olx", marca="CHEVROLET", modelo="OPALA"),
        ])
        r = listar_anuncios(marca="VOLKSWAGEN", modelo="FUSCA 1300")
        marcas = {x["marca"] for x in r["opcoes"]["marca"]}
        assert marcas == {"VOLKSWAGEN", "CHEVROLET"}


# ── AC-P06: get_mais_pesquisados retorna ranking ordenado por contagem DESC ───

class TestGetMaisPesquisados:
    def test_ranking_ordenado(self):
        for _ in range(5):
            log_search("VOLKSWAGEN", "FUSCA")
        for _ in range(2):
            log_search("FIAT", "PALIO")
        log_search("CHEVROLET", "OPALA")

        resultado = get_mais_pesquisados(limit=10)
        ranking = resultado["ranking"]
        assert ranking[0]["modelo"] == "FUSCA"
        assert ranking[0]["buscas"] == 5
        assert ranking[1]["modelo"] == "PALIO"
        assert ranking[1]["buscas"] == 2

    def test_limit_respeitado(self):
        for marca, modelo in [("VW", "A"), ("VW", "B"), ("VW", "C"), ("VW", "D"), ("VW", "E")]:
            log_search(marca, modelo)
        resultado = get_mais_pesquisados(limit=3)
        assert len(resultado["ranking"]) <= 3

    def test_retorna_vazio_sem_dados(self):
        resultado = get_mais_pesquisados()
        assert resultado["ranking"] == []
