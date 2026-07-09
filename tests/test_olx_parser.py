"""
Testes de snapshot do parser OLX (AC5).

Fixture: tests/fixtures/olx_sample.html — 4 cards reais de busca "fusca"
(2026-07-09), extraídos da listagem renderizada (`section.olx-adcard`).

A OLX removeu o <script id="__NEXT_DATA__"> do frontend (migrou para Next.js
App Router) — o parser agora lê os cards diretamente do DOM renderizado, e o
ano vem do título (não mais de um campo `regdate` estruturado).
"""
from pathlib import Path

import pytest

from src.connectors.olx import parsear_listagem
from src.pipeline.persistence import ANO_CORTE_CLASSICO
from src.pipeline.schema import validar

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "olx_sample.html"
DATA_COLETA = "2026-07-09"

# HTML mínimo com dois cards para testes unitários sem fixture externa.
_HTML_DOIS_CARDS = """
<!DOCTYPE html>
<html><body>
<section class="olx-adcard olx-adcard__vertical">
  <div class="olx-adcard__content">
    <div class="olx-adcard__topbody">
      <a class="olx-adcard__link" href="https://sp.olx.com.br/fusca-1970-111" title="Volkswagen Fusca 1970">
        <h2 class="olx-adcard__title">Volkswagen Fusca 1970</h2>
      </a>
    </div>
    <div class="olx-adcard__mediumbody">
      <h3 class="olx-adcard__price">R$ 36.900</h3>
    </div>
  </div>
</section>
<section class="olx-adcard olx-adcard__vertical">
  <div class="olx-adcard__content">
    <div class="olx-adcard__topbody">
      <a class="olx-adcard__link" href="https://sp.olx.com.br/maverick-1977-222" title="Ford Maverick 1977">
        <h2 class="olx-adcard__title">Ford Maverick 1977</h2>
      </a>
    </div>
    <div class="olx-adcard__mediumbody">
      <h3 class="olx-adcard__price">R$ 85.000</h3>
    </div>
  </div>
</section>
</body></html>
"""


@pytest.fixture(scope="module")
def html_snapshot():
    if not FIXTURE_PATH.exists():
        pytest.skip("Fixture olx_sample.html não encontrada.")
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def anuncios_snapshot(html_snapshot):
    return parsear_listagem(html_snapshot, data_coleta=DATA_COLETA)


@pytest.fixture(scope="module")
def anuncios_html_minimo():
    return parsear_listagem(_HTML_DOIS_CARDS, data_coleta=DATA_COLETA)


# ── Testes com HTML mínimo (rápidos, sem fixture externa) ─────────────────────

def test_html_minimo_retorna_dois_anuncios(anuncios_html_minimo):
    assert len(anuncios_html_minimo) == 2


def test_html_minimo_titulos(anuncios_html_minimo):
    titulos = [a.titulo for a in anuncios_html_minimo]
    assert "Volkswagen Fusca 1970" in titulos
    assert "Ford Maverick 1977" in titulos


def test_html_minimo_precos(anuncios_html_minimo):
    precos = {a.titulo: a.preco for a in anuncios_html_minimo}
    assert precos["Volkswagen Fusca 1970"] == 36900.0
    assert precos["Ford Maverick 1977"] == 85000.0


def test_html_minimo_anos(anuncios_html_minimo):
    anos = [a.ano for a in anuncios_html_minimo]
    assert 1970 in anos
    assert 1977 in anos


def test_html_minimo_fonte(anuncios_html_minimo):
    for a in anuncios_html_minimo:
        assert a.fonte == "olx"


def test_html_minimo_url_absoluta(anuncios_html_minimo):
    for a in anuncios_html_minimo:
        assert a.url.startswith("https://")


# ── Testes com snapshot real ────────────────────────────────────────────────

def test_snapshot_retorna_anuncios(anuncios_snapshot):
    assert len(anuncios_snapshot) >= 1, "Esperado ao menos 1 anúncio no snapshot"


def test_todos_anuncios_tem_titulo(anuncios_snapshot):
    for a in anuncios_snapshot:
        assert a.titulo, f"Anúncio sem título: {a}"


def test_todos_anuncios_tem_preco_positivo(anuncios_snapshot):
    for a in anuncios_snapshot:
        assert a.preco is not None and a.preco > 0, f"Preço inválido: {a}"


def test_todos_anuncios_tem_url(anuncios_snapshot):
    for a in anuncios_snapshot:
        assert a.url.startswith("https://"), f"URL inválida: {a.url}"


def test_todos_anuncios_tem_fonte_olx(anuncios_snapshot):
    for a in anuncios_snapshot:
        assert a.fonte == "olx", f"Fonte inesperada: {a.fonte}"


def test_todos_anuncios_tem_data_coleta(anuncios_snapshot):
    for a in anuncios_snapshot:
        assert a.data_coleta == DATA_COLETA


# ── Filtro de ruído (AC3) ────────────────────────────────────────────────────

def test_todos_anuncios_tem_ano_valido_corte(anuncios_snapshot):
    for a in anuncios_snapshot:
        assert a.ano is not None, f"Ano ausente: {a}"
        assert 1900 <= a.ano <= ANO_CORTE_CLASSICO, (
            f"Ano fora do corte: {a.ano} — {a.titulo}"
        )


def test_snapshot_descarta_anuncio_pos_corte(html_snapshot):
    """A fixture inclui 1 card de 2026 (fora do corte) — não deve aparecer na saída."""
    anuncios = parsear_listagem(html_snapshot, data_coleta=DATA_COLETA)
    assert not any(a.ano and a.ano > ANO_CORTE_CLASSICO for a in anuncios)


# ── Schema canônico (AC5) ────────────────────────────────────────────────────

def test_schema_valida_todos(anuncios_snapshot):
    for a in anuncios_snapshot:
        assert validar(a), f"Anúncio inválido após parse: {a}"


# ── Filtro de ruído: ano no título fora do corte deve ser descartado ────────

def test_filtro_descarta_ano_pos_corte():
    html = """
    <section class="olx-adcard">
      <div class="olx-adcard__content"><div class="olx-adcard__topbody">
        <a class="olx-adcard__link" href="https://sp.olx.com.br/gol-2010-1234567" title="Volkswagen Gol 2010">
          <h2 class="olx-adcard__title">Volkswagen Gol 2010</h2>
        </a>
      </div><div class="olx-adcard__mediumbody"><h3 class="olx-adcard__price">R$ 30.000</h3></div></div>
    </section>
    """
    assert parsear_listagem(html) == []


def test_filtro_aceita_ano_exatamente_no_corte():
    html = f"""
    <section class="olx-adcard">
      <div class="olx-adcard__content"><div class="olx-adcard__topbody">
        <a class="olx-adcard__link" href="https://sp.olx.com.br/fusca-2000-9999999" title="Volkswagen Fusca 2000">
          <h2 class="olx-adcard__title">Volkswagen Fusca {ANO_CORTE_CLASSICO}</h2>
        </a>
      </div><div class="olx-adcard__mediumbody"><h3 class="olx-adcard__price">R$ 20.000</h3></div></div>
    </section>
    """
    resultado = parsear_listagem(html)
    assert len(resultado) == 1
    assert resultado[0].ano == ANO_CORTE_CLASSICO
