"""
Testes de regressão do conector Circuito de Leilões (Picelli/Supabase).

Cobre parsear_titulo() e parsear_lotes() com:
- Dicts mínimos inline (testes rápidos, sem dependência externa)
- Fixture real salva em tests/fixtures/circuitodeleiloes_sample.json
  (capturada da API pública em 2026-06-10; pulada se não existir)

Regra metodológica (spike sprint2-spike-circuitodeleiloes.md):
- Preço realizado = highest_bid_value com status "vendido".
- "condicional" (pendente de homologação) NÃO entra no sinal.
"""
import json

import pytest
from pathlib import Path

from src.connectors.circuitodeleiloes import (
    FONTE,
    parsear_lotes,
    parsear_titulo,
)
from src.pipeline.schema import validar

FIXTURE = Path(__file__).parent / "fixtures" / "circuitodeleiloes_sample.json"


@pytest.fixture(scope="module")
def lotes_reais():
    if not FIXTURE.exists():
        pytest.skip("Fixture circuitodeleiloes_sample.json não encontrada.")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _lote(**kwargs):
    """Lote mínimo válido no formato da view public_lots."""
    base = {
        "id": "abc-123",
        "slug": "ford-galaxie-500-1968",
        "title": "FORD/GALAXIE 500 - 1968/1968",
        "status": "vendido",
        "highest_bid_value": 70000.0,
        "bid_count": 12,
        "evaluation_value": 0.0,
        "updated_at": "2026-06-01T12:00:00+00:00",
    }
    base.update(kwargs)
    return base


# ── parsear_titulo ───────────────────────────────────────────────────────────

class TestParsearTitulo:
    def test_padrao_detran_basico(self):
        assert parsear_titulo("FORD/GALAXIE 500 - 1968/1968") == (
            "FORD", "GALAXIE 500", 1968,
        )

    def test_prefixo_imp_descartado(self):
        marca, modelo, ano = parsear_titulo("IMP/MERCEDES BENZ 190 E   - 1983/1983")
        assert marca == "MERCEDES BENZ"
        assert modelo == "190 E"
        assert ano == 1983

    def test_prefixo_i_descartado(self):
        assert parsear_titulo("I/FORD F150 STEP SIDE - 1985/1985") == (
            "FORD", "F150 STEP SIDE", 1985,
        )

    def test_segmento_duplicado_colapsado(self):
        marca, modelo, ano = parsear_titulo("GM/GM/OPALA COMODORO  - 1980/1980")
        assert marca == "GM"
        assert modelo == "OPALA COMODORO"
        assert ano == 1980

    def test_sem_ano(self):
        marca, modelo, ano = parsear_titulo("IMP/CHEVROLET SILVERADO Z71 DUALY")
        assert marca == "CHEVROLET"
        assert modelo == "SILVERADO Z71 DUALY"
        assert ano is None

    def test_sem_barra_usa_primeira_palavra(self):
        assert parsear_titulo("AUDI S6 2.2 TB - 1995/1995") == (
            "AUDI", "S6 2.2 TB", 1995,
        )

    def test_colchetes_com_barra_interna_nao_quebram_split(self):
        marca, modelo, ano = parsear_titulo(" RYLEY [MON/PROTOTIPO] - 1949/1949")
        assert marca == "RYLEY"
        assert ano == 1949

    def test_titulo_sem_veiculo_nao_explode(self):
        marca, modelo, ano = parsear_titulo("LOTE BENEFICENTE")
        assert ano is None


# ── parsear_lotes — filtros de status e preço ────────────────────────────────

class TestParsearLotesFiltros:
    def test_vendido_entra(self):
        anuncios = parsear_lotes([_lote()], "FORD", "GALAXIE", "2026-06-10")
        assert len(anuncios) == 1
        assert anuncios[0].preco == 70000.0

    def test_condicional_nao_entra(self):
        anuncios = parsear_lotes(
            [_lote(status="condicional")], "FORD", "GALAXIE", "2026-06-10"
        )
        assert anuncios == []

    @pytest.mark.parametrize("status", ["aberto", "retirado", "encerrado"])
    def test_outros_status_nao_entram(self, status):
        anuncios = parsear_lotes(
            [_lote(status=status)], "FORD", "GALAXIE", "2026-06-10"
        )
        assert anuncios == []

    def test_vendido_sem_lance_nao_entra(self):
        anuncios = parsear_lotes(
            [_lote(highest_bid_value=0.0)], "FORD", "GALAXIE", "2026-06-10"
        )
        assert anuncios == []

    def test_lote_duplicado_por_id_entra_uma_vez(self):
        anuncios = parsear_lotes([_lote(), _lote()], "FORD", "GALAXIE", "2026-06-10")
        assert len(anuncios) == 1


# ── parsear_lotes — matching marca/modelo ────────────────────────────────────

class TestParsearLotesMatching:
    def test_modelo_diferente_nao_entra(self):
        anuncios = parsear_lotes([_lote()], "FORD", "MUSTANG", "2026-06-10")
        assert anuncios == []

    def test_marca_diferente_nao_entra(self):
        anuncios = parsear_lotes([_lote()], "CHEVROLET", "GALAXIE", "2026-06-10")
        assert anuncios == []

    def test_alias_vw_para_volkswagen(self):
        lote = _lote(title="VW/FUSCA 1200 - 1964/1964", slug="vw-fusca-1200")
        anuncios = parsear_lotes([lote], "VOLKSWAGEN", "FUSCA", "2026-06-10")
        assert len(anuncios) == 1

    def test_alias_mercedes_benz_com_hifen(self):
        lote = _lote(title="IMP/MERCEDES BENZ 190 E - 1983/1983", slug="mb-190e")
        anuncios = parsear_lotes([lote], "MERCEDES-BENZ", "190", "2026-06-10")
        assert len(anuncios) == 1

    def test_matching_case_insensitive_e_sem_acento(self):
        anuncios = parsear_lotes([_lote()], "ford", "galáxie", "2026-06-10")
        assert len(anuncios) == 1


# ── parsear_lotes — contrato canônico ────────────────────────────────────────

class TestParsearLotesContrato:
    def test_anuncio_valido_no_contrato_canonico(self):
        anuncio = parsear_lotes([_lote()], "FORD", "GALAXIE", "2026-06-10")[0]
        assert validar(anuncio)
        assert anuncio.fonte == FONTE
        assert anuncio.data_coleta == "2026-06-10"

    def test_marca_modelo_canonicos_vem_da_consulta(self):
        anuncio = parsear_lotes([_lote()], "Ford", "Galaxie", "2026-06-10")[0]
        assert anuncio.marca == "FORD"
        assert anuncio.modelo == "GALAXIE"

    def test_ano_extraido_do_titulo(self):
        anuncio = parsear_lotes([_lote()], "FORD", "GALAXIE", "2026-06-10")[0]
        assert anuncio.ano == 1968

    def test_url_aponta_para_pagina_do_lote(self):
        anuncio = parsear_lotes([_lote()], "FORD", "GALAXIE", "2026-06-10")[0]
        assert anuncio.url == "https://www.picellileiloes.com.br/lote/ford-galaxie-500-1968"

    def test_titulo_preservado_sem_espacos_nas_pontas(self):
        lote = _lote(title="  FORD/GALAXIE 500 - 1968/1968  ")
        anuncio = parsear_lotes([lote], "FORD", "GALAXIE", "2026-06-10")[0]
        assert anuncio.titulo == "FORD/GALAXIE 500 - 1968/1968"


# ── Snapshot — fixture real da API ───────────────────────────────────────────

class TestSnapshotReal:
    def test_opala_so_vendido_entra(self, lotes_reais):
        """Fixture tem OPALA vendido (DIPLOMATA 72k) e condicional (COMODORO 66k)."""
        anuncios = parsear_lotes(lotes_reais, "GM", "OPALA", "2026-06-10")
        assert len(anuncios) == 1
        assert anuncios[0].preco == 72000.0
        assert anuncios[0].ano == 1988

    def test_f150_vendido(self, lotes_reais):
        anuncios = parsear_lotes(lotes_reais, "FORD", "F150", "2026-06-10")
        assert len(anuncios) == 1
        assert anuncios[0].preco == 305000.0

    def test_fusca_aberto_nao_gera_sinal(self, lotes_reais):
        """VW/FUSCA 1200 está 'aberto' (lance 38k não homologado) — fora do sinal."""
        anuncios = parsear_lotes(lotes_reais, "VOLKSWAGEN", "FUSCA 1200", "2026-06-10")
        assert anuncios == []

    def test_todos_resultados_validos_no_contrato(self, lotes_reais):
        for lote in lotes_reais:
            marca, modelo, _ = parsear_titulo(lote["title"])
            if not modelo:
                continue
            for anuncio in parsear_lotes(lotes_reais, marca, modelo, "2026-06-10"):
                assert validar(anuncio)
                assert anuncio.fonte == FONTE
