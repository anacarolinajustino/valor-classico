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
    COLUNAS_EXPORT_ANUNCIOS,
    COLUNAS_EXPORT_RESUMO,
    exportar_anuncios,
    exportar_resumo,
    excluir_marca_modelo,
    get_dashboard_stats,
    get_media_modelo,
    init_db,
    listar_anuncios,
    listar_anuncios_do_par,
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


# ── get_media_modelo: estatísticas de preço de um par (calculadora de média) ──

class TestGetMediaModelo:
    def _anuncio_preco(self, url, preco, ano=1975, fonte="olx",
                       marca="VOLKSWAGEN", modelo="FUSCA", versao=None):
        return Anuncio(
            titulo=f"Carro {ano}", preco=preco, marca=marca, modelo=modelo,
            ano=ano, versao=versao, url=url, fonte=fonte, data_coleta="2026-07-14",
        )

    def _semear(self):
        upsert_anuncios([
            self._anuncio_preco("http://x/1", 30000.0, ano=1970, fonte="olx"),
            self._anuncio_preco("http://x/2", 50000.0, ano=1975, fonte="olx"),
            self._anuncio_preco("http://x/3", 70000.0, ano=1975, fonte="maxicar"),
            # Sem preço (sob consulta): conta no total, fora das médias.
            self._anuncio_preco("http://x/4", None, ano=1980, fonte="maxicar"),
            # Outro modelo, não deve entrar na conta do FUSCA.
            self._anuncio_preco("http://x/5", 999999.0, modelo="KOMBI"),
        ])

    def test_media_e_faixa(self):
        self._semear()
        d = get_media_modelo("volkswagen", "fusca")
        assert d["total"] == 4          # inclui o sem preço
        assert d["com_preco"] == 3
        assert d["preco_medio"] == 50000.0   # (30k+50k+70k)/3
        assert d["preco_mediano"] == 50000.0
        assert d["preco_min"] == 30000.0
        assert d["preco_max"] == 70000.0
        assert d["ano_min"] == 1970
        assert d["ano_max"] == 1980

    def test_por_ano_e_por_fonte(self):
        self._semear()
        d = get_media_modelo("volkswagen", "fusca")
        por_ano = {r["ano"]: (r["qtd"], r["preco_medio"]) for r in d["por_ano"]}
        assert por_ano[1975] == (2, 60000.0)   # (50k+70k)/2
        assert por_ano[1980] == (1, None)      # só o sem preço
        por_fonte = {r["fonte"]: r["qtd"] for r in d["por_fonte"]}
        assert por_fonte == {"olx": 2, "maxicar": 2}

    def test_modelo_inexistente_zera(self):
        self._semear()
        d = get_media_modelo("volkswagen", "brasilia")
        assert d["total"] == 0
        assert d["com_preco"] == 0
        assert d["preco_medio"] is None
        assert d["por_ano"] == []

    # ── recorte por versão (é nela que mora a diferença de preço) ──────────

    def _semear_versoes(self):
        upsert_anuncios([
            self._anuncio_preco("http://v/1", 100000.0, versao="SS"),
            self._anuncio_preco("http://v/2", 140000.0, versao="SS", ano=1976),
            self._anuncio_preco("http://v/3", 40000.0, versao="DE LUXO"),
            # Sem versão: balde próprio, não some da conta.
            self._anuncio_preco("http://v/4", 60000.0),
        ])

    def test_por_versao_quebra_o_par_inteiro(self):
        self._semear_versoes()
        d = get_media_modelo("volkswagen", "fusca")
        por_versao = {r["versao"]: (r["qtd"], r["preco_medio"]) for r in d["por_versao"]}
        assert por_versao["SS"] == (2, 120000.0)      # (100k+140k)/2
        assert por_versao["DE LUXO"] == (1, 40000.0)
        assert por_versao[""] == (1, 60000.0)         # sem versão informada
        assert d["versao"] is None

    def test_versao_recorta_media_e_quebras(self):
        self._semear_versoes()
        d = get_media_modelo("volkswagen", "fusca", "ss")
        assert d["versao"] == "SS"
        assert d["total"] == 2
        assert d["preco_medio"] == 120000.0
        assert {r["ano"] for r in d["por_ano"]} == {1975, 1976}
        # por_versao ignora o recorte: é o mapa que monta o seletor de versão.
        assert len(d["por_versao"]) == 3

    def test_versao_vazia_recorta_os_sem_versao(self):
        self._semear_versoes()
        d = get_media_modelo("volkswagen", "fusca", "")
        assert d["total"] == 1
        assert d["preco_medio"] == 60000.0


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

    # ── versão: dropdown em cascata do modelo (atalho da calculadora) ──────

    def _semear_versoes(self):
        upsert_anuncios([
            _anuncio("http://v/1", 1975, marca="CHEVROLET", modelo="OPALA", versao="SS"),
            _anuncio("http://v/2", 1976, marca="CHEVROLET", modelo="OPALA", versao="SS"),
            _anuncio("http://v/3", 1977, marca="CHEVROLET", modelo="OPALA", versao="COMODORO"),
            _anuncio("http://v/4", 1978, marca="CHEVROLET", modelo="OPALA"),
        ])

    def test_versao_filtra_por_igualdade(self):
        self._semear_versoes()
        r = listar_anuncios(marca="CHEVROLET", modelo="OPALA", versao="SS")
        assert r["total"] == 2
        assert all(row["versao"] == "SS" for row in r["rows"])

    def test_versao_vazia_traz_os_sem_versao(self):
        # "" é um recorte legítimo (o balde "sem versão informada"), diferente
        # de None, que é "todas as versões" — a rota traduz o sentinela.
        self._semear_versoes()
        assert listar_anuncios(marca="CHEVROLET", modelo="OPALA", versao="")["total"] == 1
        assert listar_anuncios(marca="CHEVROLET", modelo="OPALA")["total"] == 4

    def test_opcoes_versao_so_com_modelo_escolhido(self):
        self._semear_versoes()
        sem_modelo = listar_anuncios(marca="CHEVROLET")
        assert sem_modelo["opcoes"]["versao"] == []

        com_modelo = listar_anuncios(marca="CHEVROLET", modelo="OPALA")
        versoes = {x["versao"]: x["qtd"] for x in com_modelo["opcoes"]["versao"]}
        assert versoes == {"SS": 2, "COMODORO": 1, "": 1}


# ── listar_anuncios_do_par: detalhe de um grupo (quarentena e calculadora) ────

class TestListarAnunciosDoPar:
    def _semear(self):
        upsert_anuncios([
            _anuncio("http://p/1", 1975, fonte="olx", marca="CHEVROLET", modelo="OPALA", versao="SS"),
            _anuncio("http://p/2", 1976, fonte="maxicar", marca="CHEVROLET", modelo="OPALA", versao="SS"),
            _anuncio("http://p/3", 1975, fonte="olx", marca="CHEVROLET", modelo="OPALA", versao="COMODORO"),
            _anuncio("http://p/4", 1975, fonte="olx", marca="CHEVROLET", modelo="OPALA"),
        ])

    def test_par_inteiro_sem_recorte(self):
        self._semear()
        assert len(listar_anuncios_do_par("chevrolet", "opala")) == 4

    def test_recortes_de_versao_ano_e_fonte(self):
        self._semear()
        assert len(listar_anuncios_do_par("chevrolet", "opala", versao="ss")) == 2
        assert len(listar_anuncios_do_par("chevrolet", "opala", versao="")) == 1   # sem versão
        assert len(listar_anuncios_do_par("chevrolet", "opala", ano=1975)) == 3
        assert len(listar_anuncios_do_par("chevrolet", "opala", fonte="maxicar")) == 1
        # Recortes combinam (linha "por ano" com uma versão já selecionada).
        assert len(listar_anuncios_do_par("chevrolet", "opala", versao="SS", ano=1975)) == 1


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


# ── Exportação CSV (snapshot pra série histórica) ─────────────────────────────

class TestExportacao:
    def _semear(self):
        upsert_anuncios([
            _anuncio("http://x/1", 1985, marca="VOLKSWAGEN", modelo="GOL",
                     versao="GERACAO I CL"),
            _anuncio("http://x/2", 1985, marca="VOLKSWAGEN", modelo="GOL",
                     versao="GERACAO I CL"),
            _anuncio("http://x/3", 1990, marca="CHEVROLET", modelo="OPALA",
                     versao="COMODORO"),
        ])

    def test_anuncios_saem_com_a_data_do_snapshot(self):
        # `data_extracao` em toda linha é o que permite empilhar os arquivos
        # de vários dias e formar a série histórica.
        self._semear()
        linhas = list(exportar_anuncios("2026-08-04"))
        assert len(linhas) == 3
        assert {l["data_extracao"] for l in linhas} == {"2026-08-04"}
        assert set(COLUNAS_EXPORT_ANUNCIOS) <= set(linhas[0])

    def test_anuncios_trazem_os_eixos_da_versao_separados(self):
        self._semear()
        gol = [l for l in exportar_anuncios("2026-08-04") if l["modelo"] == "GOL"][0]
        assert (gol["versao"], gol["geracao"]) == ("CL", "I")

    def test_resumo_agrupa_por_recorte_e_conta(self):
        # Uma linha por (marca, modelo, versão, geração, ano) — o formato que
        # empilha direto numa série de preço médio.
        self._semear()
        linhas = list(exportar_resumo("2026-08-04"))
        assert set(COLUNAS_EXPORT_RESUMO) <= set(linhas[0])
        gol = [l for l in linhas if l["modelo"] == "GOL"]
        assert len(gol) == 1
        assert gol[0]["anuncios"] == 2
        assert gol[0]["com_preco"] == 2
        assert float(gol[0]["preco_medio"]) == 50000.0
        assert gol[0]["data_extracao"] == "2026-08-04"

    def test_resumo_nao_conta_sem_preco_nas_estatisticas(self):
        # Anúncio "sob consulta" entra na contagem, não na média — mesma
        # regra da calculadora, pra que os dois números batam.
        a = _anuncio("http://x/9", 1985, marca="FIAT", modelo="UNO")
        a.preco = None
        upsert_anuncios([a, _anuncio("http://x/10", 1985, marca="FIAT", modelo="UNO")])
        uno = [l for l in exportar_resumo() if l["modelo"] == "UNO"][0]
        assert uno["anuncios"] == 2
        assert uno["com_preco"] == 1

    def test_base_vazia_nao_quebra(self):
        assert list(exportar_anuncios()) == []
        assert list(exportar_resumo()) == []


class TestRotaExportar:
    def test_csv_sai_no_padrao_brasileiro(self, client):
        # Separador ";", vírgula decimal e BOM — é o que o Excel em português
        # abre com duplo clique sem embaralhar colunas nem acento.
        upsert_anuncios([_anuncio("http://x/1", 1985, marca="VOLKSWAGEN", modelo="GOL")])
        resp = client.get("/admin/api/exportar?tipo=resumo")
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        assert "attachment" in resp.headers["Content-Disposition"]
        assert ".csv" in resp.headers["Content-Disposition"]
        corpo = resp.get_data()
        assert corpo.startswith("﻿".encode("utf-8"))
        texto = corpo.decode("utf-8-sig")
        assert texto.splitlines()[0].startswith("data_extracao;marca;modelo")
        assert "50000,00" in texto

    def test_tipo_invalido_da_400(self, client):
        resp = client.get("/admin/api/exportar?tipo=xpto")
        assert resp.status_code == 400

    def test_tipo_padrao_e_anuncios(self, client):
        upsert_anuncios([_anuncio("http://x/1", 1985)])
        resp = client.get("/admin/api/exportar")
        cabecalho = resp.get_data().decode("utf-8-sig").splitlines()[0]
        assert cabecalho.startswith("data_extracao;fonte;marca")
