"""
Valor de coleção: converte a mediana do mercado aberto no preço que um
carro do mesmo modelo em estado de coleção alcança.

POR QUE ISSO EXISTE
-------------------
A mediana do recorte responde "quanto vale um Fusca anunciado", mas o
índice quer responder "quanto vale um Fusca de coleção" — e os dois números
são bem diferentes, porque o mercado aberto mistura carro de coleção com
carro velho rodando. Um especialista do ramo cotou Fusca em R$ 35–45 mil
quando nossa mediana dizia R$ 33 mil, Gol em R$ 35 mil contra nossos R$ 20
mil, Kombi em R$ 50–60 mil contra R$ 35 mil.

O estado de conservação NÃO está no dado: os títulos são ficha técnica do
marketplace ("VOLKSWAGEN FUSCA 1.6 8V GASOLINA 2P MANUAL", 41 caracteres em
média) e só 0,4% mencionam algo como "placa preta". Também não dá pra
separar os dois mercados por aglomerado — em escala log a distribuição de
cada modelo é unimodal, o carro de coleção é o ombro direito de uma curva
contínua, não um pico próprio (testado com mistura de duas gaussianas: o EM
só fatiou uma log-normal única em pedaços sobrepostos).

O QUE SUBSTITUI A INFORMAÇÃO QUE FALTA
--------------------------------------
A própria base tem duas famílias de fonte:

  marketplace generalista (OLX, ML, Webmotors, iCarros)  31.593  R$ 32.900
  loja especializada em antigo (as outras ~30 fontes)     1.754  R$ 79.900

Loja de carro antigo só anuncia carro apresentável, então a mediana dela é
uma medida direta do preço de coleção — só que existe pra poucos modelos.
A calibração usa as especializadas como RÉGUA e não como filtro: nos 36
modelos que têm amostra dos dois lados, ajusta

    log(preço de coleção) = a + b · log(mediana do mercado aberto)

e depois aplica essa curva em qualquer recorte, inclusive nos modelos sem
loja especializada nenhuma.

POR QUE UMA LEI DE POTÊNCIA, E NÃO UM PERCENTIL OU UM MULTIPLICADOR
-------------------------------------------------------------------
O expoente deu 0,693, e o teste rejeita b = 1 com folga (t = -6,12). Isso
quer dizer que o prêmio de coleção ENCOLHE conforme o carro encarece, o que
bate com o mercado real: em Porsche 911, Corvette, Galaxie e Maverick a
loja especializada cobra MENOS que a mediana do marketplace (0,64x–0,87x),
porque ninguém anuncia 911 detonado e a mediana do mercado aberto já é
preço de coleção. Em Gol, Escort, Kombi e Uno ela cobra 2,4x–3,2x, porque o
mercado aberto está entupido de carro de trabalho.

Por isso não serve um percentil fixo (o percentil equivalente varia de 10%
no Galaxie a 94% no Corcel II) nem um multiplicador único. Validação
leave-one-out, cada modelo previsto por uma curva reajustada SEM ele:

    a curva            erra tipicamente  20%
    prêmio fixo (b=1)                    42%
    nenhuma correção                     56%

Contra os dez números do especialista: mediana 1,05x, 9 de 10 dentro de
±33%. E a curva é melhor que usar direto a mediana da loja especializada
mesmo quando ela existe — pra Kombi a loja pede R$ 112.500 contra os R$ 55
mil do especialista (sobrepreço de boutique), e a curva devolve R$ 53.700.

O PONTO DE CRUZAMENTO
---------------------
Como b < 1, existe um preço acima do qual a curva projeta ABAIXO da mediana
do mercado: R$ 154 mil na calibração atual (exp(a / (1 - b))). Isso não é
defeito — em Galaxie, Maverick e Corvette a loja especializada cobra mesmo
menos que a mediana do marketplace. Mas é o regime onde os resíduos são
piores (no 911 a curva erra 1,45x pra baixo) e onde a régua é mais fina:
poucos modelos caros têm amostra dos dois lados. Vale pra 12% das
combinações modelo+ano da base, e o retorno marca essas com
`abaixo_do_mercado` pra tela poder avisar em vez de exibir um número
contraintuitivo sem explicação.

O QUE ISSO NÃO É
----------------
Preço de ANÚNCIO, não de transação — todo o mercado brasileiro de antigo
pede acima do que fecha. E erro típico de 20%: é índice, não é laudo. Por
isso `estimar()` devolve também a banda de um desvio, e quem exibe deve
mostrar a banda junto.
"""
from __future__ import annotations

import math
from typing import Any, NamedTuple

# Marketplaces que anunciam qualquer carro. O resto das fontes são lojas e
# leiloeiros de carro antigo, que só listam veículo apresentável — é essa
# divisão que serve de régua (ver o cabeçalho). Fonte nova entra como
# especializada por omissão, que é o certo: todo conector que entrou depois
# do núcleo é de loja de antigo.
FONTES_GENERALISTAS = frozenset({"olx", "mercadolivre", "webmotors", "icarros"})


class Calibracao(NamedTuple):
    """Constantes da curva + a procedência delas, que viaja junto no JSON."""

    a: float            # intercepto em log
    b: float            # expoente (b < 1 => prêmio encolhe com o preço)
    sigma: float        # desvio residual em log, vira a banda de confiança
    r2: float
    n_modelos: int      # modelos com amostra dos dois lados no ajuste
    erro_loo: float     # erro absoluto mediano em log, leave-one-out
    data: str           # quando foi calibrada

    @property
    def fator(self) -> float:
        """Forma multiplicativa: colecao = fator * mercado ** b."""
        return math.exp(self.a)


# Calibração vigente. Recalcular a cada coleta mensal com
# `scripts/calibrar_valor_colecao.py`, que imprime este bloco pronto pra
# colar — as constantes moram no código de propósito, pra ficarem sob
# revisão e não mudarem sozinhas embaixo de um índice publicado.
CALIBRACAO = Calibracao(
    a=3.668,
    b=0.693,
    sigma=0.286,
    r2=0.848,
    n_modelos=36,
    erro_loo=0.181,
    data="2026-08-10",
)

# Abaixo disso a mediana do mercado não sustenta nem a si mesma, quanto mais
# uma projeção em cima dela.
MIN_AMOSTRA = 5


def estimar(
    mediana_mercado: float | None,
    n_amostra: int = 0,
    calibracao: Calibracao = CALIBRACAO,
) -> dict[str, Any] | None:
    """
    Projeta o valor de coleção a partir da mediana do mercado ABERTO.

    `mediana_mercado` tem que vir só das fontes generalistas — é sobre elas
    que a curva foi ajustada. Passar a mediana da base inteira infla o
    resultado, porque as lojas especializadas já estão no preço de coleção e
    seriam corrigidas duas vezes.

    Devolve None quando não há amostra pra sustentar a conta. `piso` e
    `teto` são a banda de um desvio residual (~68%), e existem porque um
    número redondo sozinho esconde que o erro típico é de 20%.
    """
    if mediana_mercado is None or mediana_mercado <= 0 or n_amostra < MIN_AMOSTRA:
        return None

    log_estimado = calibracao.a + calibracao.b * math.log(float(mediana_mercado))
    estimado = math.exp(log_estimado)
    return {
        "estimado": estimado,
        "piso": math.exp(log_estimado - calibracao.sigma),
        "teto": math.exp(log_estimado + calibracao.sigma),
        # O insumo viaja junto pra tela poder mostrar "de X para Y" — sem
        # ele o número aparece do nada e não dá pra conferir.
        "mediana_mercado": float(mediana_mercado),
        "n_mercado": n_amostra,
        "premio": estimado / float(mediana_mercado),
        # Regime acima do ponto de cruzamento (ver cabeçalho): legítimo, mas
        # é onde a curva erra mais e onde o número surpreende quem lê.
        "abaixo_do_mercado": estimado < float(mediana_mercado),
        "calibracao": {
            "b": calibracao.b,
            "r2": calibracao.r2,
            "n_modelos": calibracao.n_modelos,
            "erro_tipico": math.exp(calibracao.erro_loo) - 1,
            "data": calibracao.data,
        },
    }
