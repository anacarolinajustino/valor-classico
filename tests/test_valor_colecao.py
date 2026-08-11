"""
Testes da curva de valor de coleção.

Boa parte deles não checa números e sim PROPRIEDADES da curva — que o
prêmio encolhe conforme o carro encarece, que a banda cerca o valor, que a
projeção é monótona. São essas que sobrevivem à recalibração mensal: as
constantes mudam todo mês, o comportamento não pode mudar sem alguém
perceber.
"""
import math

import pytest

from src.pipeline.valor_colecao import (
    CALIBRACAO,
    FONTES_GENERALISTAS,
    MIN_AMOSTRA,
    Calibracao,
    estimar,
)


class TestEstimar:
    def test_projeta_acima_do_mercado_em_carro_popular(self):
        r = estimar(20_000, n_amostra=100)
        assert r is not None
        # Faixa larga de propósito: o teste vale depois de recalibrar.
        assert 30_000 < r["estimado"] < 45_000
        assert r["premio"] > 1

    def test_bate_com_a_formula_da_calibracao_vigente(self):
        r = estimar(20_000, n_amostra=100)
        esperado = math.exp(CALIBRACAO.a + CALIBRACAO.b * math.log(20_000))
        assert r["estimado"] == pytest.approx(esperado)
        assert r["premio"] == pytest.approx(esperado / 20_000)

    def test_banda_cerca_o_valor_e_e_simetrica_em_log(self):
        r = estimar(35_000, n_amostra=50)
        assert r["piso"] < r["estimado"] < r["teto"]
        # Simétrica no log, não no real: é onde o resíduo é normal.
        assert (r["estimado"] / r["piso"]) == pytest.approx(r["teto"] / r["estimado"])

    def test_o_insumo_viaja_junto(self):
        r = estimar(12_345, n_amostra=42)
        assert r["mediana_mercado"] == 12_345
        assert r["n_mercado"] == 42
        assert r["calibracao"]["data"] == CALIBRACAO.data
        assert r["calibracao"]["b"] == CALIBRACAO.b

    @pytest.mark.parametrize("mediana", [None, 0, -1])
    def test_sem_mediana_utilizavel_devolve_none(self, mediana):
        assert estimar(mediana, n_amostra=100) is None

    def test_amostra_curta_devolve_none(self):
        assert estimar(30_000, n_amostra=MIN_AMOSTRA - 1) is None
        assert estimar(30_000, n_amostra=MIN_AMOSTRA) is not None

    def test_amostra_zero_e_o_padrao(self):
        """Chamar sem n_amostra não pode inventar uma projeção."""
        assert estimar(30_000) is None


class TestPropriedadesDaCurva:
    """O que precisa continuar verdade depois de qualquer recalibração."""

    def test_premio_encolhe_conforme_o_carro_encarece(self):
        # É a descoberta central: b < 1. Se um dia a recalibração devolver
        # b >= 1, este teste cai e alguém precisa olhar por quê.
        premios = [estimar(m, 100)["premio"]
                   for m in (10_000, 30_000, 100_000, 300_000)]
        assert premios == sorted(premios, reverse=True)

    def test_projecao_e_monotona(self):
        valores = [estimar(m, 100)["estimado"]
                   for m in (10_000, 30_000, 100_000, 300_000)]
        assert valores == sorted(valores)

    def test_carro_caro_pode_projetar_abaixo_do_mercado(self):
        """Regime acima do ponto de cruzamento — legítimo, mas sinalizado."""
        cruzamento = math.exp(CALIBRACAO.a / (1 - CALIBRACAO.b))
        barato = estimar(cruzamento / 4, 100)
        caro = estimar(cruzamento * 4, 100)
        assert barato["abaixo_do_mercado"] is False
        assert caro["abaixo_do_mercado"] is True
        assert caro["estimado"] < caro["mediana_mercado"]

    def test_expoente_menor_que_um(self):
        assert 0 < CALIBRACAO.b < 1

    def test_fator_multiplicativo_confere(self):
        c = CALIBRACAO
        m = 50_000
        assert c.fator * m ** c.b == pytest.approx(
            math.exp(c.a + c.b * math.log(m))
        )


class TestCalibracaoInjetada:
    def test_aceita_outra_calibracao(self):
        """A calibração é parâmetro pra o script poder simular antes de colar."""
        alt = Calibracao(a=0.0, b=1.0, sigma=0.0, r2=1.0, n_modelos=2,
                         erro_loo=0.0, data="2026-01-01")
        r = estimar(50_000, n_amostra=10, calibracao=alt)
        assert r["estimado"] == pytest.approx(50_000)
        assert r["premio"] == pytest.approx(1.0)
        assert r["piso"] == pytest.approx(r["teto"])


class TestFontesGeneralistas:
    def test_os_quatro_marketplaces(self):
        assert FONTES_GENERALISTAS == {
            "olx", "mercadolivre", "webmotors", "icarros",
        }

    def test_loja_de_antigo_nao_e_generalista(self):
        # Fonte nova entra como especializada por omissão — é o que faz a
        # régua crescer sozinha quando um conector de loja é adicionado.
        for loja in ("pastorecc", "berekclassicos", "estacaoraridades", "xyz"):
            assert loja not in FONTES_GENERALISTAS
