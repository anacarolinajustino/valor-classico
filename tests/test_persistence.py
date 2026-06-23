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
    CHART_MIN_DIAS,
    init_db,
    upsert_preco,
    log_search,
    get_historico,
    get_mais_pesquisados,
)

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
