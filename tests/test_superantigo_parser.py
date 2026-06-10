"""
Testes de regressão do parser do Super Antigo usando snapshot HTML real.

O snapshot foi coletado em 2026-05-30 com busca por VW Fusca (Playwright).
"""
import pytest
from pathlib import Path
from src.connectors.superantigo import parsear_listagem_html
from src.pipeline.schema import validar

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "superantigo_sample.html"

# ── HTML mínimo com dois veículos para testes unitários sem fixture ────────────
_HTML_DOIS_VEICULOS = """
<!DOCTYPE html>
<html><body>
<div class="bg-white rounded-lg overflow-hidden shadow-md">
  <div class="relative">
    <a href="/veiculos/carro/volkswagen/fusca/fusca-1600-1975-1975-100">
      <img alt="Fusca 1975" />
    </a>
  </div>
  <div class="p-4 min-h-[14rem] h-auto flex flex-col">
    <div class="mb-2">
      <h3 class="font-bold">Volkswagen Fusca - FUSCA 1.600 - 1975</h3>
    </div>
    <p>1975 • 50.000 km • Gasolina</p>
    <p>São Paulo - SP</p>
    <p>R$ 45.000</p>
  </div>
</div>
<div class="bg-white rounded-lg overflow-hidden shadow-md">
  <div class="relative">
    <a href="/veiculos/carro/ford/maverick/maverick-1977-1977-200">
      <img alt="Maverick 1977" />
    </a>
  </div>
  <div class="p-4 min-h-[14rem] h-auto flex flex-col">
    <div class="mb-2">
      <h3 class="font-bold">Ford Maverick - MAVERICK V8 1977</h3>
    </div>
    <p>1977 • 80.000 km • Gasolina</p>
    <p>Rio de Janeiro - RJ</p>
    <p>R$ 85.000</p>
  </div>
</div>
</body></html>
"""


@pytest.fixture(scope="module")
def html_snapshot():
    if not FIXTURE_PATH.exists():
        pytest.skip("Fixture superantigo_sample.html não encontrada.")
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def anuncios_snapshot(html_snapshot):
    return parsear_listagem_html(html_snapshot, data_coleta="2026-05-30")


@pytest.fixture(scope="module")
def anuncios_html_minimo():
    return parsear_listagem_html(_HTML_DOIS_VEICULOS, data_coleta="2026-05-30")


# ── Testes com HTML mínimo (rápidos, sem fixture externa) ─────────────────────

def test_html_minimo_retorna_dois_anuncios(anuncios_html_minimo):
    assert len(anuncios_html_minimo) == 2


def test_html_minimo_titulos(anuncios_html_minimo):
    titulos = [a.titulo for a in anuncios_html_minimo]
    assert "Volkswagen Fusca - FUSCA 1.600 - 1975" in titulos
    assert "Ford Maverick - MAVERICK V8 1977" in titulos


def test_html_minimo_precos(anuncios_html_minimo):
    precos = {a.titulo[:10]: a.preco for a in anuncios_html_minimo}
    assert any(p == 45000.0 for p in precos.values())
    assert any(p == 85000.0 for p in precos.values())


def test_html_minimo_anos(anuncios_html_minimo):
    anos = [a.ano for a in anuncios_html_minimo]
    assert 1975 in anos
    assert 1977 in anos


def test_html_minimo_marcas(anuncios_html_minimo):
    marcas = [a.marca for a in anuncios_html_minimo]
    assert "VOLKSWAGEN" in marcas
    assert "FORD" in marcas


def test_html_minimo_fonte(anuncios_html_minimo):
    for a in anuncios_html_minimo:
        assert a.fonte == "superantigo"


def test_html_minimo_url_absoluta(anuncios_html_minimo):
    for a in anuncios_html_minimo:
        assert a.url.startswith("https://www.superantigo.com.br")


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
        assert a.url.startswith("https://www.superantigo.com.br"), f"URL inválida: {a.url}"


def test_todos_anuncios_tem_fonte_superantigo(anuncios_snapshot):
    for a in anuncios_snapshot:
        assert a.fonte == "superantigo", f"Fonte inesperada: {a.fonte}"


def test_todos_anuncios_tem_ano_valido(anuncios_snapshot):
    for a in anuncios_snapshot:
        if a.ano is not None:
            assert 1900 <= a.ano <= 1999, f"Ano fora do intervalo esperado: {a.ano}"


def test_schema_valida_todos(anuncios_snapshot):
    invalidos = [a for a in anuncios_snapshot if not validar(a)]
    assert not invalidos, f"Anúncios inválidos pelo schema: {invalidos}"
