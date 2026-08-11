# Valor de coleção

Como o índice sai da mediana do mercado aberto e chega no preço de um
exemplar em estado de coleção.

O racional do método está no cabeçalho de `src/pipeline/valor_colecao.py` e
não se repete aqui. Este documento guarda **a evidência que sustenta a
escolha**, as hipóteses que foram testadas e descartadas, e o procedimento
de recalibração mensal.

## O problema

A mediana do recorte responde "quanto vale um Fusca anunciado". O índice
precisa responder "quanto vale um Fusca de coleção". Um especialista do ramo
cotou dez modelos, e a diferença é sistemática:

| modelo | nossa mediana | especialista |
|---|---|---|
| Fusca | 33.000 | 35–45 mil |
| Gol | 20.000 | 35 mil |
| Kombi | 35.000 | 50–60 mil |
| Opala | 70.000 | 80–120 mil |
| Escort | 18.900 | 30–35 mil |

O mercado aberto mistura carro de coleção com carro velho rodando, e o
estado de conservação não está em campo nenhum.

## O que foi testado e descartado

**Separar as duas populações por aglomerado.** Em escala log a distribuição
de cada modelo é unimodal — Fusca tem um pico único em ~35 mil. Uma mistura
de duas gaussianas ajustada por EM só fatia a log-normal em pedaços
sobrepostos (na Kombi devolveu 32 mil / 128 mil com peso 10%, ou seja, a
cauda). Carro de coleção é o ombro direito de uma curva contínua, não um
pico próprio.

**Ler o estado de conservação no título.** Não existe: os títulos são ficha
técnica do marketplace, 41 caracteres em média
("VOLKSWAGEN FUSCA 1.6 8V GASOLINA 2P MANUAL"). Só 0,4% mencionam "placa
preta" — e quando mencionam valem 1,70x, então o sinal é real, só que
rarísimo demais para filtrar. Se um dia coletarmos o corpo do anúncio, este
é o caminho a retomar.

**Um percentil fixo.** O percentil do mercado aberto que equivale ao preço
de loja especializada varia de 10% (Galaxie) a 94% (Corcel II). Não há
número único.

**Um multiplicador fixo.** Perde feio na validação (42% de erro contra 20%
da curva) porque o prêmio não é constante — ver abaixo.

**Usar direto a mediana da loja especializada** onde ela existe. Pior que a
curva: na Kombi a loja pede 112.500 contra os 55 mil do especialista
(sobrepreço de boutique), enquanto a curva devolve 53.700. A curva
regulariza o ruído de amostras de 8 a 150 anúncios.

## A régua

A base tem duas famílias de fonte, e a divisão é o que substitui a
informação que falta:

| | anúncios | mediana |
|---|---|---|
| marketplace generalista (OLX, ML, Webmotors, iCarros) | 31.593 | 32.900 |
| loja especializada em antigo (as outras ~30 fontes) | 1.754 | 79.900 |

Loja de carro antigo só anuncia carro apresentável. Em 36 modelos com
amostra dos dois lados, ajusta-se
`log(coleção) = a + b · log(mercado)`.

## Por que o expoente é o resultado, não um detalhe

`b = 0,693`, e o teste rejeita `b = 1` com `t = -6,12`. O prêmio de coleção
**encolhe conforme o carro encarece**:

| modelo | mediana do mercado | loja especializada | razão |
|---|---|---|---|
| Ford Galaxie | 140.000 | 89.900 | 0,64x |
| Porsche 911 | 880.000 | 745.000 | 0,85x |
| VW Fusca | 32.900 | 45.000 | 1,37x |
| Ford Escort | 18.000 | 43.700 | 2,43x |
| VW Kombi | 34.990 | 112.500 | 3,22x |

Ninguém anuncia 911 detonado, então em carro caro a mediana do mercado
aberto já é preço de coleção. Em carro popular o mercado está entupido de
carro de trabalho e só a fatia de cima é coleção.

## Validação

Leave-one-out: cada modelo previsto por uma curva reajustada **sem** ele.

| método | erro típico |
|---|---|
| a curva | **20%** |
| prêmio fixo (b = 1) | 42% |
| nenhuma correção | 56% |

Contra os dez números do especialista, mediana 1,05x e 9 de 10 dentro de
±33%.

## Limitações conhecidas

- **É preço de anúncio, não de transação.** Todo o mercado brasileiro de
  antigo pede acima do que fecha.
- **Erro típico de 20%.** É índice, não é laudo. Por isso a tela mostra a
  banda de um desvio junto do número.
- **Acima de R$ 154 mil a curva projeta abaixo do mercado** (o ponto de
  cruzamento, `exp(a / (1 - b))`). Legítimo em Galaxie e Maverick, mas é o
  regime de pior resíduo — no 911 a curva erra 1,45x pra baixo. Vale pra 12%
  das combinações modelo+ano, e essas vêm marcadas com `abaixo_do_mercado`.
- **Corsa, Palio e Uno são caso à parte.** O especialista fala da versão
  rara; nossa base tem o carro comum. A curva acerta o número por outro
  caminho, não porque entendeu o modelo.
- **A régua é fina em carro caro.** Poucos modelos acima de 150 mil têm
  amostra dos dois lados (Corvette 21, 911 11).

## Recalibração mensal

Depois de cada coleta:

```
python scripts/calibrar_valor_colecao.py
```

O script não escreve em lugar nenhum — imprime o bloco `Calibracao(...)`
pronto pra colar em `src/pipeline/valor_colecao.py`, mais os diagnósticos.
As constantes moram no código de propósito: um índice publicado não pode ter
o parâmetro mudando sozinho embaixo dele.

O que olhar antes de colar:

1. **`t` do teste `b = 1`.** Se deixar de rejeitar, a curva parou de ganhar
   de um multiplicador simples e o expoente virou complexidade sem retorno.
2. **O aviso de salto em `b`.** O script alerta quando `b` anda mais de 3
   erros padrão. Isso é notícia sobre a base — fonte nova entrando, fonte
   morrendo —, não manutenção de rotina.
3. **Os maiores resíduos.** Modelo que foge muito da curva costuma ter
   amostra suja de um dos lados.

Depois de colar, `pytest tests/test_valor_colecao.py`. Os testes de
propriedade (prêmio encolhe, projeção monótona, `0 < b < 1`) são o que
sobrevive à troca de constantes; se algum cair, o comportamento mudou e não
só o número.
