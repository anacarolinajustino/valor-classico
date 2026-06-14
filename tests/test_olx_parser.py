"""
Testes de snapshot do parser OLX (AC5).

Fixture: tests/fixtures/olx_sample.json — 5 anúncios reais de busca "fusca" (2026-06-14).
Todos os 5 anúncios têm ano <= 2000, portanto nenhum deve ser descartado pelo filtro de corte.

O parser recebe HTML (com <script id="__NEXT_DATA__">). O teste envolve o JSON
da fixture no HTML mínimo que o browser real retornaria.
"""
import json
from pathlib import Path

import pytest

from src.connectors.olx import parsear_listagem
from src.pipeline.persistence import ANO_CORTE_CLASSICO
from src.pipeline.schema import validar

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "olx_sample.json"
DATA_COLETA = "2026-06-14"


@pytest.fixture(scope="module")
def anuncios_parsed():
    if not FIXTURE_PATH.exists():
        pytest.skip("Fixture olx_sample.json não encontrada.")
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    # Envolve o JSON da fixture no HTML mínimo que Playwright retornaria
    html = (
        '<html><head></head><body>'
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(raw)}</script>'
        '</body></html>'
    )
    return parsear_listagem(html, data_coleta=DATA_COLETA)


# ── Estrutura ────────────────────────────────────────────────────────────────

def test_snapshot_retorna_anuncios(anuncios_parsed):
    assert len(anuncios_parsed) >= 1, "Esperado ao menos 1 anúncio no snapshot"


def test_todos_anuncios_tem_titulo(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.titulo, f"Anúncio sem título: {a}"


def test_todos_anuncios_tem_preco_positivo(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.preco is not None and a.preco > 0, f"Preço inválido: {a}"


def test_todos_anuncios_tem_url(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.url.startswith("https://"), f"URL inválida: {a.url}"


def test_todos_anuncios_tem_fonte_olx(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.fonte == "olx", f"Fonte inesperada: {a.fonte}"


def test_todos_anuncios_tem_data_coleta(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.data_coleta == DATA_COLETA


# ── Filtro de ruído (AC3) ────────────────────────────────────────────────────

def test_todos_anuncios_tem_ano_valido_corte(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.ano is not None, f"Ano ausente: {a}"
        assert 1900 <= a.ano <= ANO_CORTE_CLASSICO, (
            f"Ano fora do corte: {a.ano} — {a.titulo}"
        )


# ── Schema canônico (AC5) ────────────────────────────────────────────────────

def test_schema_valida_todos(anuncios_parsed):
    for a in anuncios_parsed:
        assert validar(a), f"Anúncio inválido após parse: {a}"


# ── Filtro de ruído: anúncio pós-2000 deve ser descartado ───────────────────

def test_filtro_descarta_ano_pos_corte():
    """Anúncio com regdate > ANO_CORTE_CLASSICO não deve aparecer na saída."""
    ad_pos_corte = {
        "subject": "Volkswagen Gol 2010",
        "priceValue": "R$ 30.000",
        "url": "https://sp.olx.com.br/gol-2010-1234567",
        "properties": [
            {"name": "vehicle_brand", "value": "Volkswagen"},
            {"name": "regdate", "value": "2010"},
        ],
    }
    payload = {"props": {"pageProps": {"ads": [ad_pos_corte]}}}
    html = (
        '<html><body>'
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        '</body></html>'
    )
    resultado = parsear_listagem(html)
    assert resultado == [], f"Anúncio de 2010 não deveria passar no filtro: {resultado}"


def test_filtro_aceita_ano_exatamente_no_corte():
    """Anúncio com regdate == ANO_CORTE_CLASSICO (2000) deve ser aceito."""
    ad_corte = {
        "subject": "Volkswagen Fusca 2000",
        "priceValue": "R$ 20.000",
        "url": "https://sp.olx.com.br/fusca-2000-9999999",
        "properties": [
            {"name": "vehicle_brand", "value": "Volkswagen"},
            {"name": "regdate", "value": str(ANO_CORTE_CLASSICO)},
        ],
    }
    payload = {"props": {"pageProps": {"ads": [ad_corte]}}}
    html = (
        '<html><body>'
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        '</body></html>'
    )
    resultado = parsear_listagem(html)
    assert len(resultado) == 1
    assert resultado[0].ano == ANO_CORTE_CLASSICO
