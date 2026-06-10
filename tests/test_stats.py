"""
Testes do módulo de estatísticas (stats.py).
"""
from src.pipeline.schema import Anuncio
from src.pipeline.stats import calcular


def _anuncio(preco, data="2026-05-29", modelo="KOMBI"):
    return Anuncio(
        titulo=f"VW {modelo} {preco}",
        preco=preco,
        marca="VOLKSWAGEN",
        modelo=modelo,
        ano=1975,
        versao=None,
        url=f"https://maxicar.com.br/{preco}",
        fonte="maxicar",
        data_coleta=data,
    )


# ── Casos básicos ───────────────────────────────

def test_lista_vazia_retorna_zeros():
    resultado = calcular([])
    assert resultado["amostra"] == 0
    assert resultado["media"] == 0.0
    assert resultado["mediana"] == 0.0
    assert resultado["data_coleta_mais_recente"] == ""


def test_amostra_unico_elemento():
    resultado = calcular([_anuncio(50000.0)])
    assert resultado["amostra"] == 1
    assert resultado["media"] == 50000.0
    assert resultado["mediana"] == 50000.0
    assert resultado["minimo"] == 50000.0
    assert resultado["maximo"] == 50000.0


def test_media_calculada_corretamente():
    anuncios = [_anuncio(10000.0), _anuncio(20000.0), _anuncio(30000.0)]
    resultado = calcular(anuncios)
    assert resultado["media"] == 20000.0


def test_mediana_impar():
    anuncios = [_anuncio(10000.0), _anuncio(30000.0), _anuncio(20000.0)]
    resultado = calcular(anuncios)
    assert resultado["mediana"] == 20000.0


def test_mediana_par():
    anuncios = [_anuncio(10000.0), _anuncio(20000.0), _anuncio(30000.0), _anuncio(40000.0)]
    resultado = calcular(anuncios)
    assert resultado["mediana"] == 25000.0


def test_minimo_e_maximo():
    anuncios = [_anuncio(5000.0), _anuncio(50000.0), _anuncio(25000.0)]
    resultado = calcular(anuncios)
    assert resultado["minimo"] == 5000.0
    assert resultado["maximo"] == 50000.0


def test_ignora_anuncios_sem_preco():
    anuncios = [_anuncio(None), _anuncio(10000.0), _anuncio(None)]
    resultado = calcular(anuncios)
    assert resultado["amostra"] == 1
    assert resultado["media"] == 10000.0


def test_data_coleta_mais_recente():
    anuncios = [
        _anuncio(10000.0, data="2026-05-20"),
        _anuncio(20000.0, data="2026-05-29"),
        _anuncio(15000.0, data="2026-05-25"),
    ]
    resultado = calcular(anuncios)
    assert resultado["data_coleta_mais_recente"] == "2026-05-29"
