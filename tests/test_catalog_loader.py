"""
Testes do carregador de catálogo (catalog/loader.py).

Usa o CSV canônico em data/base_marcamodelo.csv para validar carregamento e matching.
"""
import pytest
from pathlib import Path

from src.catalog.loader import carregar_catalogo, match_anuncio, resetar_cache
from src.pipeline.schema import Anuncio

CSV_PATH = Path(__file__).parent.parent / "data" / "base_marcamodelo.csv"


def _anuncio(marca, modelo, ano=None):
    return Anuncio(
        titulo=f"{marca} {modelo}",
        preco=10000.0,
        marca=marca,
        modelo=modelo,
        ano=ano,
        versao=None,
        url=f"https://maxicar.com.br/{marca}-{modelo}",
        fonte="maxicar",
        data_coleta="2026-05-29",
    )


@pytest.fixture(autouse=True)
def limpar_cache():
    """Garante que o cache é limpo antes de cada teste."""
    resetar_cache()
    yield
    resetar_cache()


# ── Carregamento ────────────────────────────────

@pytest.mark.skipif(not CSV_PATH.exists(), reason="CSV do catálogo não disponível")
def test_catalogo_carrega_com_sucesso():
    catalogo = carregar_catalogo(CSV_PATH)
    assert len(catalogo) > 0


@pytest.mark.skipif(not CSV_PATH.exists(), reason="CSV do catálogo não disponível")
def test_catalogo_contem_volkswagen_kombi():
    catalogo = carregar_catalogo(CSV_PATH)
    chaves = [(m, mo) for (m, mo) in catalogo.keys() if "VOLKSWAGEN" in m and "KOMBI" in mo]
    assert len(chaves) > 0, "VOLKSWAGEN KOMBI deve estar no catálogo"


@pytest.mark.skipif(not CSV_PATH.exists(), reason="CSV do catálogo não disponível")
def test_catalogo_idempotente():
    """Carregar duas vezes retorna o mesmo objeto."""
    c1 = carregar_catalogo(CSV_PATH)
    c2 = carregar_catalogo(CSV_PATH)
    assert c1 is c2


def test_catalogo_csv_nao_encontrado_retorna_vazio(tmp_path):
    caminho_inexistente = tmp_path / "nao_existe.csv"
    catalogo = carregar_catalogo(caminho_inexistente)
    # Sem CSV, apenas o suplemento manual é carregado (Idea, Logan, 207, CR-V, SW4)
    from src.catalog.loader import _SUPLEMENTO
    assert catalogo.keys() == _SUPLEMENTO.keys()


# ── Matching ────────────────────────────────────

@pytest.mark.skipif(not CSV_PATH.exists(), reason="CSV do catálogo não disponível")
def test_match_exato_volkswagen_kombi():
    anuncio = _anuncio("VOLKSWAGEN", "KOMBI")
    resultado = match_anuncio(anuncio, CSV_PATH)
    assert resultado.match_confidence in {"high", "medium"}
    assert resultado.match_strategy in {"normalized_exact", "fuzzy"}


@pytest.mark.skipif(not CSV_PATH.exists(), reason="CSV do catálogo não disponível")
def test_match_inexistente_retorna_unmatched():
    anuncio = _anuncio("MARCAXYZ", "MODELOXYZ")
    resultado = match_anuncio(anuncio, CSV_PATH)
    assert resultado.match_confidence == "unmatched"
    assert resultado.match_strategy == "none"


@pytest.mark.skipif(not CSV_PATH.exists(), reason="CSV do catálogo não disponível")
def test_match_nao_altera_outros_campos():
    anuncio = _anuncio("VOLKSWAGEN", "KOMBI")
    resultado = match_anuncio(anuncio, CSV_PATH)
    assert resultado.titulo == anuncio.titulo
    assert resultado.preco == anuncio.preco
    assert resultado.marca == anuncio.marca
    assert resultado.modelo == anuncio.modelo
