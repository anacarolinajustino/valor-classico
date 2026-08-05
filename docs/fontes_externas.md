# Fontes externas de marca/modelo/versão/ano

Referência para quem for mexer em `src/catalog/externo.py`, `scripts/ingest_oldtimers.py`,
`scripts/ingest_classic_com.py`, `scripts/gerar_aliases_intl.py` ou
`scripts/auditar_cobertura_externa.py`. Documenta a avaliação de quatro bases estrangeiras de
carro clássico feita em 2026-08-04 e o que foi aproveitado de cada uma.

## 1. Por que buscar fonte externa

O catálogo canônico (`data/base_marcamodelo.csv`, 26.030 linhas) vem da Webmotors e cobre bem o
mercado brasileiro. O que ele não cobre é o importado clássico: medido em 2026-08-04, dos 1.018
pares (marca, modelo) do banco, **314 não existem no catálogo** — nem no CSV base, nem no
`_SUPLEMENTO` do loader, nem no suplemento manual do painel. São 371 anúncios.

Esses 314 se dividem em três grupos, e só um deles é resolvível por fonte estrangeira:

1. **Importado legítimo ausente do catálogo** — Ferrari Mondial, Porsche 912, Oldsmobile 442,
   Triumph TR7. É o alvo.
2. **Carro nacional** — Fiat Prêmio, DKW Vemaguet, CBT Javali, Engesa 4x4, Asia Motors Topic.
   Nenhuma fonte estrangeira tem, e nunca vai ter (ver seção 6).
3. **Lixo de extração** — `FORD COUPE`, `FORD MAO`, `CHEVROLET IMP`, `FIAT I`. Não é lacuna de
   catálogo, é bug de parsing do título.

## 2. As quatro fontes avaliadas

| Fonte | Veredito | Motivo |
|---|---|---|
| the-oldtimers.com | **Usada** | 23.174 registros, endpoint JSON aberto, robots.txt liberado |
| classic.com | **Usada (só sitemaps)** | taxonomia marca/modelo/geração/trim na URL; conteúdo é React |
| classiccardatabase.com | **Não usada** | termos proíbem uso comercial; há canal de licenciamento |
| vindata.com/classic | **Descartada** | exige VIN por veículo, que o banco não tem |

### the-oldtimers.com

WordPress com wpDataTables. A tabela é server-side e o endpoint devolve a base inteira numa
requisição só:

```
POST /wp-admin/admin-ajax.php?action=get_wdtable&table_id=1
     draw=1&start=0&length=30000&wdtNonce=<nonce>
```

O nonce sai do HTML de `/database/` (input `wdtNonceFrontendServerSide_1`). **Sem o nonce o
endpoint devolve HTTP 200 com corpo vazio** — não é erro de rede, é essa a pegadinha.

Cada linha vem como `[marca, variante, ano, modelo, foto_html, id, ordem]`. Repare que **modelo é
a coluna 3, não a 1** — a coluna 1 é a variante/trim. Granularidade de um registro por
modelo-ano, então a faixa de produção sai por agregação.

Licença: o site não publica termos sobre reuso de dados. `robots.txt` tem `Disallow:` vazio.

### classic.com

O valor está na estrutura da URL, não no conteúdo:

```
/m/bmw/3-series/e30/m3/coupe/
   marca / modelo / geração / trim / carroceria
```

Os 3 sitemaps (`sitemap-market.xml`, `?p=2`, `?p=3`) entregam 11.191 URLs dessa taxonomia sem
renderizar nada. As páginas em si são React — o HTML cru vem com `<h1>` vazio e ~2,6 MB — então
extrair especificação exigiria browser, e não vale.

**Dois obstáculos técnicos, ambos resolvidos:**

- *Cloudflare com fingerprint TLS.* Com o MESMO User-Agent e a mesma URL, `requests` toma 403
  (`cf-mitigated: challenge`) em 100% das tentativas e `curl` responde 200 em 100%. Playwright
  com stealth e proxy residencial DataImpulse **também** toma 403, e o challenge nunca resolve
  (testado com 32s de espera). A solução é `curl` via subprocess — nativo do Windows 10+ em
  `System32`, sem dependência nova. Subir pra browser não adianta e sairia mais caro.
- *UA de crawler passa, UA de navegador não.* O sitemap existe pra ser lido por robô e o
  Cloudflare trata assim. Não é preciso fingir navegador.

Licença: `robots.txt` permite `/m/` (bloqueia `/chart-data/`, `/garage/`, `/partners/`,
`/tracker/`, `/sell/list-your-car/`). Os termos não puderam ser lidos —
`/about/terms-conditions/` devolve HTTP 500 em 2026-08-04 — o que é mais uma razão pra ficar nos
sitemaps em vez de raspar conteúdo.

### classiccardatabase.com — não usada

Conteúdo forte (33.000 modelos americanos 1910-1975, com números de produção, cores e preço
originais) e trivial de raspar. Mas os termos de uso são explícitos:

> "to use the Site solely for internal, personal, **non-commercial** purposes"
> "You may not (a) copy, print (except for the...) ... that is offered for **commercial
> distribution** of any kind"

Como o Valor Clássico é produto, raspar seria violação direta. Eles vendem acesso
(`info@classiccardatabase.com`) — é o caminho legítimo se um dia a especificação técnica
americana virar prioridade.

### vindata.com/classic — descartada

Relatório de histórico veicular por VIN (NMVTIS, sinistro, hodômetro, recall). Duas coisas o
eliminam: depende de VIN por veículo, e a tabela `anuncios` não tem chassi nem placa (anúncio de
OLX/ML não publica isso); e é dado americano pago por consulta, que não cobriria carro
brasileiro. O link no site do classiccardatabase é afiliado (`?a-aid=ccdb`), não fonte
independente.

## 3. Os artefatos gerados

Todos em `data/`, todos **isolados do catálogo canônico**: nada aqui é lido por
`carregar_catalogo()`, nenhum conector importa daqui, o pipeline não sabe que existem. São
material de consulta e auditoria. Quem promove um par pro catálogo de verdade é a usuária, pelo
suplemento manual do painel.

| Arquivo | Linhas | Gerado por |
|---|---|---|
| `base_marcamodelo_intl.csv` | 2.797 pares | `ingest_oldtimers.py` |
| `vocabulario_geracao_trim.csv` | 3.303 pares | `ingest_classic_com.py` |
| `aliases_intl.csv` | 39 aliases | `gerar_aliases_intl.py` |
| `candidatos_suplemento_intl.csv` | 44 candidatos | `auditar_cobertura_externa.py --candidatos` |

**Por que isolado:** as fontes cobrem Europa e EUA e desconhecem o carro nacional. Misturá-las no
catálogo canônico traria grafia em inglês (`C-Class`, `3 Series`) pro pipeline que grava em
português, além de milhares de modelos que nunca vão aparecer num anúncio brasileiro.

### Cuidado ao normalizar fonte estrangeira

`sanear_marca_modelo()` **não serve** aqui, apesar da regra geral de sempre passar campo
estruturado por ela. Aquela função infere marca a partir do vocabulário de modelos BRASILEIRO, e
numa fonte estrangeira isso troca a marca errado:

- `Alpine A110` vira `SUNBEAM ALPINE A110` — porque Alpine é um modelo Sunbeam no catálogo nacional
- `Citroen 2CV` vira `CITROEN 2 CV` — quebra um nome que o `_SUPLEMENTO` grafa colado

O que `externo.py` faz em vez disso é reconciliar **só a marca**, casando pela forma
alfanumérica contra o catálogo (`chave_alfanumerica`). Isso resolve `Alfa-Romeo` -> `ALFA ROMEO`,
`Aston-Martin` -> `ASTON MARTIN` e `De-Tomaso` -> `DE TOMASO` sem tabela na mão e sem risco de
reatribuir marca. O modelo passa só por `normalizar_texto`.

### Confiabilidade de cada coluna do vocabulário

A hierarquia do classic.com **não é posicionalmente rígida** — medido sobre as 11.191 URLs, o
nível 3 é geração na maioria dos casos mas às vezes é carroceria, e os níveis 4 a 7 misturam trim
com carroceria. Por isso a classificação é por vocabulário, não por posição. Em ordem de
confiança:

1. `carrocerias` — vocabulário fechado e pequeno, praticamente sem erro.
2. `geracoes` — códigos com letra são inequívocos (`E30`, `W124`, `R129`, `C1`-`C8`, `FJ40`,
   `1ST GEN`, `G BODY`). **Falso positivo conhecido:** `M3`/`M5`/`M6`/`L7` da BMW entram aqui,
   pois casam com o padrão letra+dígito, mas são trim.
3. `trims` — o mais ruidoso. Pega código de motor da Corvette (`327350`) junto com trim de
   verdade (`CARRERA 4S`, `BOSS 302`).

Código de geração puramente numérico (`993`, `991`, `997`) só conta como geração no nível 3 —
fora dali um número é quase sempre trim. Mesmo assim é ambíguo: a BMW usa o número como trim no
nível 3 também.

## 4. Cobertura medida

`python scripts/auditar_cobertura_externa.py`

```
Pares órfãos do catálogo canônico: 314 (371 anúncios)
Cobertos pelas fontes externas:    78 (25%) — 101 anúncios
  por estratégia: literal=52, prefixo=17, alias=9
  com faixa de ano utilizável:     44 (14 marcados como suspeita)
```

As três estratégias, em ordem decrescente de confiança: **literal** (o par existe igual),
**alias** (existe sob o nome em inglês, via `aliases_intl.csv`), **prefixo** (`GALAXIE 500` <->
`GALAXIE`).

### Efeito colateral útil: caçar modelo truncado

Casar por prefixo é faca de dois gumes, e a auditoria marca isso na coluna `suspeita`.
`GALAXIE 500` -> `GALAXIE` é legítimo (o banco tem o trim junto). Mas quando a fonte tem o nome
MAIS LONGO, é o banco que perdeu metade do nome numa extração ruim:

| Banco | Fonte tem | Diagnóstico |
|---|---|---|
| `LAND ROVER RANGE` | `RANGE ROVER` | truncado |
| `CHRYSLER NEW` | `NEW YORKER` | truncado |
| `PONTIAC TRANS` | `TRANS AM` | truncado |
| `MITSUBISHI SPACE` | `SPACE RUNNER` | truncado |
| `FORD MODEL` | `MODEL T` | truncado |
| `LINCOLN MARK` | `MARK 7` | truncado |

Esses **não** devem ir pro suplemento — cimentariam o bug. O certo é corrigir o modelo no banco.
A fonte externa aqui não está preenchendo lacuna de catálogo, está funcionando como detector de
bug de parsing.

## 5. Onde isso aparece no painel

`/admin/pendencias` — "Pendências de verificação". É a fila única de decisões manuais, e
substituiu a seção "Anúncios a verificar" que ficava escondida dentro da página de anúncios.

A diferença não é só de lugar. Antes a quarentena era uma lista chapada de pares órfãos e a
usuária tinha que pesquisar cada um pra saber se era carro de verdade, nome truncado ou lixo de
parsing. Agora **a evidência externa classifica a pendência**, e cada aba tem uma ação distinta:

| Aba | O que é | Ação sugerida |
|---|---|---|
| Nome incompleto | a fonte tem o nome MAIS longo | corrigir no banco (sugestão pré-preenchida) |
| Confirmados pela fonte | a fonte confirma o par, muitas vezes com faixa de ano | "Ao catálogo" |
| Sem evidência | nenhuma fonte conhece | triagem manual — é onde cai o carro nacional |
| Aliases a conferir | palpites `fuzzy` de tradução | "É o mesmo carro" / "São diferentes" |

Na aba de nome incompleto o botão "Ao catálogo" é **omitido de propósito**: cadastrar `RANGE`
cimentaria o erro em vez de corrigi-lo.

Estado que a tela grava, ambos append-only (a última linha vence, e o histórico fica):

- `data/pendencias_dispensadas.csv` — pares que a usuária analisou e decidiu deixar como estão.
  A chave é (marca, modelo) **sem** o tipo: se uma fonte nova reclassificar o par, a decisão
  continua valendo.
- `data/aliases_decisoes.csv` — separado de `aliases_intl.csv` porque aquele é regenerado
  inteiro pelo script, e uma coluna de status lá dentro seria apagada na próxima rodada. Um
  alias **rejeitado sai de `carregar_aliases()`** e deixa de produzir evidência.

O cruzamento em si mora em `externo.evidencia_externa()` — a mesma função que
`scripts/auditar_cobertura_externa.py` usa, pra auditoria e tela nunca divergirem sobre o mesmo
par.

## 6. O teto: 75% da lacuna é carro nacional

Os 236 pares sem cobertura não são falha das duas fontes, são limite estrutural delas. Testadas
marca a marca, **nenhuma** das marcas nacionais existe em nenhuma das duas:

Gurgel, Envemo, Santa Matilde, Miura, Adamo, Chamonix, Engesa, FNM, DKW-Vemag, MP Lafer, Bianco,
JPX, CBT, Farus, Hofstetter, Dacon, Troller, Agrale, Willys (só "Willys Overland").

Fiat Prêmio, DKW Vemaguet, DKW Belcar, CBT Javali e Asia Motors Topic vão continuar órfãos por
esse caminho. Para eles, o suplemento manual curado à mão continua sendo a única via — não
adianta procurar outra base estrangeira.

## 7. Reprodução

```bash
python scripts/ingest_oldtimers.py --limite 300 --dry-run   # smoke test
python scripts/ingest_oldtimers.py                          # 2.797 pares

python scripts/ingest_classic_com.py --limite 1 --dry-run   # smoke test
python scripts/ingest_classic_com.py                        # 3.303 pares

python scripts/gerar_aliases_intl.py --dry-run
python scripts/gerar_aliases_intl.py                        # 39 aliases

python scripts/auditar_cobertura_externa.py --candidatos data/candidatos_suplemento_intl.csv
```

Os dois ingests são idempotentes e reescrevem o CSV inteiro. `gerar_aliases_intl.py` e
`auditar_cobertura_externa.py` leem o banco, então precisam do `DATABASE_URL` no `.env`.
