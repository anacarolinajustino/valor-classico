"""
Testes de regressão do parser do Maxicar usando snapshot HTML real.

O snapshot foi coletado em 2026-05-29 com busca por 'kombi'.
"""
import pytest
from pathlib import Path
from unittest.mock import patch
from src.connectors.maxicar import parsear_listagem_html, buscar
from src.pipeline.schema import validar

# ── HTML mínimo com dois produtos: Del Rey e Pampa (mesmo buscar "del rey") ──

_HTML_DEL_REY_E_PAMPA = """
<!DOCTYPE html>
<html><body>
<ul class="products columns-4">
  <li class="product">
    <a href="https://www.maxicar.com.br/classificados/ford-del-rey-1600-1982/"
       class="woocommerce-LoopProduct-link woocommerce-loop-product__link">
    </a>
    <h2 class="woocommerce-loop-product__title">Ford Del Rey 1600 1982</h2>
    <span class="price">
      <span class="woocommerce-Price-amount amount">
        <bdi><span class="woocommerce-Price-currencySymbol">R$</span>&nbsp;45.000,00</bdi>
      </span>
    </span>
  </li>
  <li class="product">
    <a href="https://www.maxicar.com.br/classificados/ford-pampa-l-1989/"
       class="woocommerce-LoopProduct-link woocommerce-loop-product__link">
    </a>
    <h2 class="woocommerce-loop-product__title">Ford Pampa L 1989</h2>
    <span class="price">
      <span class="woocommerce-Price-amount amount">
        <bdi><span class="woocommerce-Price-currencySymbol">R$</span>&nbsp;38.000,00</bdi>
      </span>
    </span>
  </li>
</ul>
</body></html>
"""

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "maxicar_sample.html"


@pytest.fixture(scope="module")
def html_snapshot():
    if not FIXTURE_PATH.exists():
        pytest.skip("Fixture maxicar_sample.html não encontrada.")
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def anuncios_parsed(html_snapshot):
    return parsear_listagem_html(html_snapshot, data_coleta="2026-05-29")


# ── Testes de estrutura ──────────────────────────

def test_snapshot_retorna_anuncios(anuncios_parsed):
    assert len(anuncios_parsed) >= 1, "Esperado ao menos 1 anúncio no snapshot de kombi"


def test_todos_anuncios_tem_titulo(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.titulo, f"Anúncio sem título: {a}"


def test_todos_anuncios_tem_preco_positivo(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.preco is not None and a.preco > 0, f"Anúncio com preço inválido: {a}"


def test_todos_anuncios_tem_url(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.url.startswith("https://"), f"URL inválida: {a.url}"


def test_todos_anuncios_tem_fonte_maxicar(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.fonte == "maxicar"


def test_todos_anuncios_tem_data_coleta(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.data_coleta == "2026-05-29"


def test_todos_anuncios_passam_na_validacao(anuncios_parsed):
    for a in anuncios_parsed:
        assert validar(a), f"Anúncio inválido após parse: {a}"


def test_kombi_presente_em_titulo(anuncios_parsed):
    titulos = [a.titulo.lower() for a in anuncios_parsed]
    assert any("kombi" in t for t in titulos), "Esperado pelo menos um anúncio com 'kombi' no título"


def test_anuncios_tem_marca_inferida(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.marca, f"Marca não inferida para: {a.titulo}"


def test_anuncios_tem_modelo_inferido(anuncios_parsed):
    for a in anuncios_parsed:
        assert a.modelo, f"Modelo não inferido para: {a.titulo}"


# ── Regressão: buscar("FORD", "DEL REY") não deve retornar PAMPA ────────────

def _fake_requisitar(sessao, url):
    """Substitui _requisitar retornando HTML sintético com Del Rey e Pampa."""
    return _HTML_DEL_REY_E_PAMPA, url


def test_buscar_del_rey_nao_retorna_pampa():
    """Regressão — o filtro de modelo deve excluir Pampa ao buscar Del Rey."""
    with patch("src.connectors.maxicar._requisitar", side_effect=_fake_requisitar):
        resultados = buscar("FORD", "DEL REY", paginas=1)

    modelos = [a.modelo.upper() for a in resultados]
    assert not any("PAMPA" in m for m in modelos), (
        f"PAMPA não deveria aparecer na busca por DEL REY. Modelos retornados: {modelos}"
    )


def test_buscar_del_rey_retorna_del_rey():
    """Regressão — o Del Rey deve estar nos resultados quando buscado."""
    with patch("src.connectors.maxicar._requisitar", side_effect=_fake_requisitar):
        resultados = buscar("FORD", "DEL REY", paginas=1)

    modelos = [a.modelo.upper() for a in resultados]
    assert any("DEL REY" in m for m in modelos), (
        f"DEL REY deveria aparecer nos resultados. Modelos retornados: {modelos}"
    )
