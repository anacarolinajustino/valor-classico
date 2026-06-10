"""
Testes de src/pipeline/persistence.py (AC-P01 a AC-P06).
Usa banco SQLite em memória para isolamento total.
"""
from __future__ import annotations

import pytest
from pathlib import Path
from src.pipeline.persistence import (
    CHART_MIN_DIAS,
    init_db,
    upsert_preco,
    log_search,
    get_historico,
    get_mais_pesquisados,
)


# ── Fixture: banco em memória (arquivo temporário) ────────────────────────────

@pytest.fixture()
def db(tmp_path: Path) -> Path:
    """Retorna caminho para um DB temporário já inicializado."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path


# ── AC-P01: init_db cria tabelas sem erro ─────────────────────────────────────

class TestInitDb:
    def test_cria_tabelas_em_db_vazio(self, db: Path):
        import sqlite3
        conn = sqlite3.connect(str(db))
        tabelas = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "historico_precos" in tabelas
        assert "search_log" in tabelas

    def test_idempotente(self, db: Path):
        """Chamar init_db duas vezes não levanta exceção."""
        init_db(db)  # segunda chamada deve ser silenciosa


# ── AC-P02: upsert_preco — dedup intraday ─────────────────────────────────────

class TestUpsertPreco:
    def test_insere_primeira_linha(self, db: Path):
        import sqlite3
        upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 45000.0, 10, db_path=db, hoje="2026-05-30")
        conn = sqlite3.connect(str(db))
        count = conn.execute("SELECT COUNT(*) FROM historico_precos").fetchone()[0]
        conn.close()
        assert count == 1

    def test_segunda_busca_mesmo_dia_nao_duplica(self, db: Path):
        import sqlite3
        upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 45000.0, 10, db_path=db, hoje="2026-05-30")
        upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 47000.0, 14, db_path=db, hoje="2026-05-30")
        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT preco_medio, amostra FROM historico_precos").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == 47000.0  # valor mais recente
        assert rows[0][1] == 14

    def test_dias_diferentes_geram_linhas_separadas(self, db: Path):
        import sqlite3
        upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 45000.0, 10, db_path=db, hoje="2026-05-29")
        upsert_preco("VOLKSWAGEN", "FUSCA", 1972, 47000.0, 12, db_path=db, hoje="2026-05-30")
        conn = sqlite3.connect(str(db))
        count = conn.execute("SELECT COUNT(*) FROM historico_precos").fetchone()[0]
        conn.close()
        assert count == 2

    def test_marca_modelo_uppercased(self, db: Path):
        import sqlite3
        upsert_preco("volkswagen", "fusca", 1972, 45000.0, 10, db_path=db, hoje="2026-05-30")
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT marca, modelo FROM historico_precos").fetchone()
        conn.close()
        assert row[0] == "VOLKSWAGEN"
        assert row[1] == "FUSCA"


# ── AC-P03: get_historico — chart_ready False com menos de CHART_MIN_DIAS ─────

class TestGetHistoricoChartNotReady:
    def test_chart_not_ready_com_poucos_dias(self, db: Path):
        for i in range(CHART_MIN_DIAS - 1):
            upsert_preco(
                "VOLKSWAGEN", "FUSCA", 1972, 45000.0 + i * 100, 10,
                db_path=db, hoje=f"2026-05-{i + 1:02d}"
            )
        resultado = get_historico("VOLKSWAGEN", "FUSCA", db_path=db)
        assert resultado["chart_ready"] is False

    def test_sem_dados_chart_not_ready(self, db: Path):
        resultado = get_historico("VOLKSWAGEN", "FUSCA", db_path=db)
        assert resultado["chart_ready"] is False
        assert resultado["series"] == []


# ── AC-P04: get_historico — chart_ready True com >= CHART_MIN_DIAS ────────────

class TestGetHistoricoChartReady:
    def _inserir_n_dias(self, db: Path, n: int):
        for i in range(n):
            upsert_preco(
                "VOLKSWAGEN", "FUSCA", 1972, 45000.0 + i * 200, 10,
                db_path=db, hoje=f"2026-05-{i + 1:02d}"
            )

    def test_chart_ready_com_exatamente_min_dias(self, db: Path):
        self._inserir_n_dias(db, CHART_MIN_DIAS)
        resultado = get_historico("VOLKSWAGEN", "FUSCA", db_path=db)
        assert resultado["chart_ready"] is True

    def test_retorna_no_maximo_10_pontos(self, db: Path):
        self._inserir_n_dias(db, 15)
        resultado = get_historico("VOLKSWAGEN", "FUSCA", db_path=db)
        serie = resultado["series"][0]
        assert len(serie["pontos"]) <= 10

    def test_estrutura_de_pontos(self, db: Path):
        self._inserir_n_dias(db, CHART_MIN_DIAS)
        resultado = get_historico("VOLKSWAGEN", "FUSCA", db_path=db)
        ponto = resultado["series"][0]["pontos"][0]
        assert "data" in ponto
        assert "media" in ponto
        assert "amostra" in ponto

    def test_marca_modelo_uppercased_no_retorno(self, db: Path):
        self._inserir_n_dias(db, CHART_MIN_DIAS)
        resultado = get_historico("volkswagen", "fusca", db_path=db)
        assert resultado["marca"] == "VOLKSWAGEN"
        assert resultado["modelo"] == "FUSCA"


# ── AC-P05: log_search registra entrada em search_log ────────────────────────

class TestLogSearch:
    def test_registra_busca(self, db: Path):
        import sqlite3
        log_search("VOLKSWAGEN", "FUSCA", db_path=db)
        conn = sqlite3.connect(str(db))
        count = conn.execute("SELECT COUNT(*) FROM search_log").fetchone()[0]
        conn.close()
        assert count == 1

    def test_registra_multiplas_buscas(self, db: Path):
        import sqlite3
        log_search("VOLKSWAGEN", "FUSCA", db_path=db)
        log_search("VOLKSWAGEN", "FUSCA", db_path=db)
        log_search("FIAT", "PALIO", db_path=db)
        conn = sqlite3.connect(str(db))
        count = conn.execute("SELECT COUNT(*) FROM search_log").fetchone()[0]
        conn.close()
        assert count == 3

    def test_marca_uppercased(self, db: Path):
        import sqlite3
        log_search("volkswagen", "fusca", db_path=db)
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT marca, modelo FROM search_log").fetchone()
        conn.close()
        assert row[0] == "VOLKSWAGEN"
        assert row[1] == "FUSCA"


# ── AC-P06: get_mais_pesquisados retorna ranking ordenado por contagem DESC ───

class TestGetMaisPesquisados:
    def test_ranking_ordenado(self, db: Path):
        for _ in range(5):
            log_search("VOLKSWAGEN", "FUSCA", db_path=db)
        for _ in range(2):
            log_search("FIAT", "PALIO", db_path=db)
        log_search("CHEVROLET", "OPALA", db_path=db)

        resultado = get_mais_pesquisados(limit=10, db_path=db)
        ranking = resultado["ranking"]

        assert ranking[0]["modelo"] == "FUSCA"
        assert ranking[0]["buscas"] == 5
        assert ranking[1]["modelo"] == "PALIO"
        assert ranking[1]["buscas"] == 2

    def test_limit_respeitado(self, db: Path):
        for marca, modelo in [("VW", "A"), ("VW", "B"), ("VW", "C"), ("VW", "D"), ("VW", "E")]:
            log_search(marca, modelo, db_path=db)

        resultado = get_mais_pesquisados(limit=3, db_path=db)
        assert len(resultado["ranking"]) <= 3

    def test_retorna_vazio_sem_dados(self, db: Path):
        resultado = get_mais_pesquisados(db_path=db)
        assert resultado["ranking"] == []
