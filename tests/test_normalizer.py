"""
Testes do normalizer (preço e texto).
"""
import pytest
from src.pipeline.normalizer import (
    normalizar_preco,
    normalizar_texto,
    remover_acentos,
    inferir_marca_modelo_ano,
)


# ── normalizar_preco ────────────────────────────

class TestNormalizarPreco:
    def test_formato_brasileiro_completo(self):
        assert normalizar_preco("R$180.000,00") == 180000.0

    def test_formato_sem_simbolo(self):
        assert normalizar_preco("180.000,00") == 180000.0

    def test_formato_inteiro_sem_centavos(self):
        assert normalizar_preco("25000") == 25000.0

    def test_formato_com_espaco(self):
        assert normalizar_preco("R$ 35.000,00") == 35000.0

    def test_string_vazia_retorna_none(self):
        assert normalizar_preco("") is None

    def test_string_consulte_retorna_none(self):
        assert normalizar_preco("Consulte") is None

    def test_valor_zero_retorna_none(self):
        assert normalizar_preco("0") is None

    def test_somente_simbolo_retorna_none(self):
        assert normalizar_preco("R$") is None

    def test_preco_pequeno(self):
        assert normalizar_preco("1.500,00") == 1500.0

    def test_preco_sem_centavos_virgula(self):
        assert normalizar_preco("50.000") == 50000.0


# ── remover_acentos ─────────────────────────────

class TestRemoverAcentos:
    def test_vogais_acentuadas(self):
        assert remover_acentos("ação") == "acao"

    def test_cedilha(self):
        assert remover_acentos("Volkswagen") == "Volkswagen"

    def test_texto_sem_acento_inalterado(self):
        assert remover_acentos("KOMBI") == "KOMBI"

    def test_string_vazia(self):
        assert remover_acentos("") == ""


# ── normalizar_texto ────────────────────────────

class TestNormalizarTexto:
    def test_converte_para_maiusculo(self):
        assert normalizar_texto("volkswagen") == "VOLKSWAGEN"

    def test_remove_acentos_e_maiuscula(self):
        assert normalizar_texto("ção") == "CAO"

    def test_colapsa_espacos(self):
        assert normalizar_texto("VW  Kombi  ") == "VW KOMBI"

    def test_string_vazia(self):
        assert normalizar_texto("") == ""


# ── inferir_marca_modelo_ano ────────────────────

class TestInferirMarcaModeloAno:
    def test_kombi(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Volkswagen Kombi 1975")
        assert marca == "VOLKSWAGEN"
        assert modelo == "KOMBI"
        assert ano == 1975

    def test_fusca_com_versao_na_titulo(self):
        marca, modelo, ano = inferir_marca_modelo_ano("VW Fusca 1200 1962")
        assert marca == "VOLKSWAGEN"  # alias VW resolvido pro nome oficial
        assert "FUSCA" in modelo
        assert ano == 1962

    def test_alias_gm(self):
        marca, modelo, ano = inferir_marca_modelo_ano("GM Chevette Luxo 1.4 1985")
        assert marca == "CHEVROLET"
        assert "CHEVETTE" in modelo
        assert ano == 1985

    def test_alias_mercedes_benz_dois_tokens(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Mercedes Benz 280 SL 1970")
        assert marca == "MERCEDES-BENZ"
        assert "280" in modelo
        assert ano == 1970

    def test_marca_composta_land_rover(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Land Rover Defender 110 1998")
        assert marca == "LAND ROVER"
        assert "DEFENDER" in modelo
        assert ano == 1998

    def test_marca_composta_mp_lafer(self):
        marca, modelo, ano = inferir_marca_modelo_ano("MP Lafer 1976")
        assert marca == "MP LAFER"
        assert ano == 1976

    def test_titulo_comeca_pelo_modelo(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Fusca 1600 1985")
        assert marca == "VOLKSWAGEN"
        assert modelo == "FUSCA 1600"
        assert ano == 1985

    def test_modelo_ambiguo_nao_infere_marca(self):
        # CARAVAN existe em mais de uma marca no catálogo — mantém comportamento antigo
        marca, modelo, ano = inferir_marca_modelo_ano("Caravan Comodoro 1985")
        assert marca == "CARAVAN"

    def test_sem_ano(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Ford Mustang")
        assert marca == "FORD"
        assert modelo == "MUSTANG"
        assert ano is None

    def test_titulo_vazio(self):
        marca, modelo, ano = inferir_marca_modelo_ano("")
        assert marca == ""
        assert modelo == ""
        assert ano is None

    def test_chevrolet_biscayne(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Chevrolet Biscayne Sedan 1963")
        assert marca == "CHEVROLET"
        assert "BISCAYNE" in modelo
        assert ano == 1963
