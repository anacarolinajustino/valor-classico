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
    # Sem o CSV base sobram as duas fontes suplementares: o _SUPLEMENTO
    # hardcoded e o suplemento manual (data/suplemento_manual.csv), que a
    # usuária alimenta pelo painel — este teste checava só o primeiro e
    # passou a falhar quando o segundo ganhou linhas de verdade.
    from src.catalog.loader import _SUPLEMENTO, _carregar_suplemento_manual
    esperado = _SUPLEMENTO.keys() | _carregar_suplemento_manual().keys()
    assert catalogo.keys() == esperado


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


# ── Vocabulário de trim: spec que só o vizinho denuncia ───────────────────
#
# Os filtros de spec do índice olham um token por vez. Três formas de lixo
# passavam por eles e viravam "trim" — daí `_trims_na_cauda` pescar `6`, `I` e
# `DE` de volta pro campo versão (auditoria 2026-08-07).

class TestTrimDeVerdade:

    def _vale(self, frase: str, i: int) -> bool:
        from src.catalog.loader import _e_trim_de_verdade
        return _e_trim_de_verdade(frase.split(), i)

    def test_numero_antes_de_cilindros_e_motor(self):
        assert self._vale("2.8 6 CILINDROS GASOLINA", 1) is False

    def test_numero_que_nao_precede_cilindros_e_trim(self):
        """'CARRERA 4' e 'MACH 1' são nome de versão — o vizinho é quem separa."""
        assert self._vale("3.6 CARRERA 4 COUPE", 2) is True
        assert self._vale("4.9 MACH 1 V8", 2) is True

    def test_i_depois_de_cilindrada_e_injecao(self):
        assert self._vale("1.3 I SEDAN 16V", 1) is False

    def test_i_sem_cilindrada_antes_nao_e_barrado(self):
        """A regra é posicional: fora desse contexto o token não é palpite nosso."""
        assert self._vale("I SEDAN", 0) is True

    def test_conectivo_nunca_vale_sozinho(self):
        """
        'TETO DE LONA', 'SUPER DE LUXE': o DE é cola, não trim. Entre dois
        trims ele volta — mas isso é papel de `_trims_na_cauda`, não do
        vocabulário, que lista só o que vale por si.
        """
        assert self._vale("CUSTOM DE LUXE", 1) is False
        assert self._vale("CUSTOM DE LUXE", 0) is True
        assert self._vale("CUSTOM DE LUXE", 2) is True

    def test_e_solto_nao_vale(self):
        """'2.0 E' da Audi é injeção; e 'SL/E' vira 'SLE' antes de chegar aqui."""
        assert self._vale("2.0 E 8V", 1) is False


@pytest.mark.skipif(not CSV_PATH.exists(), reason="CSV do catálogo não disponível")
def test_indice_trim_sem_lixo_conhecido():
    """No catálogo real: o lixo saiu e o trim legítimo ficou."""
    from src.catalog.loader import _indice_trim

    idx = _indice_trim()
    assert "6" not in idx.get(("WILLYS", "JEEP"), set())
    assert "I" not in idx.get(("VOLKSWAGEN", "GOL"), set())
    assert "DE" not in idx.get(("CHEVROLET", "D20"), set())
    assert {"CUSTOM", "LUXE"} <= idx.get(("CHEVROLET", "D20"), set())
    assert {"CARRERA", "4"} <= idx.get(("PORSCHE", "911"), set())
