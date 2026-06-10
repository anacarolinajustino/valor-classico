"""
Testes de validação do contrato canônico (schema.py).
"""
import pytest
from src.pipeline.schema import Anuncio, validar, MATCH_CONFIDENCE_VALUES, MATCH_STRATEGY_VALUES


def _anuncio_valido(**kwargs) -> Anuncio:
    defaults = dict(
        titulo="VW Kombi 1975",
        preco=25000.0,
        marca="VOLKSWAGEN",
        modelo="KOMBI",
        ano=1975,
        versao=None,
        url="https://www.maxicar.com.br/classificados/vw-kombi-1975/",
        fonte="maxicar",
        data_coleta="2026-05-29",
    )
    defaults.update(kwargs)
    return Anuncio(**defaults)


# ── Criação ─────────────────────────────────────

def test_criar_anuncio_minimo():
    a = _anuncio_valido()
    assert a.titulo == "VW Kombi 1975"
    assert a.preco == 25000.0
    assert a.match_confidence == "unmatched"
    assert a.match_strategy == "none"


def test_criar_anuncio_todos_campos():
    a = _anuncio_valido(versao="Lotação", match_confidence="high", match_strategy="exact")
    assert a.versao == "Lotação"
    assert a.match_confidence == "high"
    assert a.match_strategy == "exact"


def test_match_confidence_invalido_levanta_erro():
    with pytest.raises(ValueError, match="match_confidence"):
        _anuncio_valido(match_confidence="very_high")


def test_match_strategy_invalido_levanta_erro():
    with pytest.raises(ValueError, match="match_strategy"):
        _anuncio_valido(match_strategy="aproximado")


def test_todos_valores_confidence_sao_validos():
    for val in MATCH_CONFIDENCE_VALUES:
        a = _anuncio_valido(match_confidence=val)
        assert a.match_confidence == val


def test_todos_valores_strategy_sao_validos():
    for val in MATCH_STRATEGY_VALUES:
        a = _anuncio_valido(match_strategy=val)
        assert a.match_strategy == val


# ── Validação ───────────────────────────────────

def test_validar_anuncio_valido():
    assert validar(_anuncio_valido()) is True


def test_validar_rejeita_preco_none():
    assert validar(_anuncio_valido(preco=None)) is False


def test_validar_rejeita_preco_zero():
    assert validar(_anuncio_valido(preco=0.0)) is False


def test_validar_rejeita_preco_negativo():
    assert validar(_anuncio_valido(preco=-100.0)) is False


def test_validar_rejeita_modelo_vazio():
    assert validar(_anuncio_valido(modelo="")) is False


def test_validar_rejeita_modelo_apenas_espacos():
    assert validar(_anuncio_valido(modelo="   ")) is False


def test_anuncio_com_ano_none_e_valido_se_tiver_preco_e_modelo():
    a = _anuncio_valido(ano=None)
    assert validar(a) is True
