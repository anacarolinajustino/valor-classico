# Pipeline de Marca/Modelo — Documentação Técnica

Referência para quem for mexer em `src/pipeline/normalizer.py`, `src/catalog/loader.py` ou nos
scripts de auditoria/reprocessamento de marca e modelo. Documenta o estado do sistema em
2026-07-21, depois de ~5 rodadas de auditoria de marca (2026-07-15 a 2026-07-17) e da rodada de
validação de existência (2026-07-21).

## 1. Por que esse sistema existe

Os anúncios chegam de 31 fontes diferentes (`src/connectors/`), cada uma com seu jeito de
descrever marca/modelo: título livre não estruturado (a maioria), ficha técnica estruturada mas
preenchida à mão pelo anunciante (Mercado Livre), ou categorias/dropdowns da própria plataforma
(OLX). Nenhuma fonte garante que "marca" e "modelo" sejam realmente marca e modelo — o mesmo carro
aparece como `"Vw Fusca 1300"`, `"Fusca 1.3"`, `"Volkswagem Fusca"`, `"Chevrolet Opala"` (marca e
modelo colados num campo só) ou `"GM/Chevrolet C14"` (marca duplicada). Sem normalização, o
dashboard de "marca/modelo mais barato" e os filtros em cascata do painel ficam inúteis —
fragmentados em dezenas de grafias do mesmo carro.

O pipeline resolve dois problemas distintos, nessa ordem:

1. **Consistência interna** — duas grafias diferentes do mesmo carro devem virar o mesmo
   marca/modelo (`normalizer.py`, rodadas 1-4 do histórico, seção 4).
2. **Existência real** — marca/modelo consistentes ainda podem ser um carro que não existe
   (typo não detectado, palavra genérica que virou "modelo" por engano). Validado cruzando contra
   um catálogo real de veículos (`catalog/loader.py` + scripts de auditoria, seção 6).

## 2. Fluxo de dados

```
Conector (título livre OU ficha técnica estruturada)
        │
        ▼
inferir_marca_modelo_ano(titulo)          OU        sanear_marca_modelo(marca_bruta, modelo_bruto)
   [título livre: OLX, Superantigo...]                [campo estruturado: Mercado Livre]
        │                                                        │
        └────────────────────────┬───────────────────────────────┘
                                  ▼
                     _separar_marca(tokens)   ← núcleo compartilhado
                                  │
                                  ▼
                     sanear_modelo(marca, modelo_bruto)
                        (corta cauda de spec, mantém nome+trim)
                                  │
                                  ▼
                        Anuncio(marca=..., modelo=..., ano=...)
                                  │
                                  ▼
                   PostgreSQL (`anuncios`, via persistence.py)
```

Os dois pontos de entrada (`inferir_marca_modelo_ano` para título livre,
`sanear_marca_modelo`/`separar_marca_modelo_versao_obs` para campo estruturado) convergem na mesma
função core, `_separar_marca` — qualquer correção feita lá (novo alias, nova marca composta, novo
eco) vale para as duas fontes automaticamente.

## 3. Módulos

| Módulo | Responsabilidade |
|---|---|
| `src/pipeline/schema.py` | Contrato canônico `Anuncio` (dataclass) + `validar()` — todo anúncio persistido passa por aqui. |
| `src/pipeline/normalizer.py` | Todo o trabalho de marca/modelo/preço/texto. ~1200 linhas, é o arquivo central deste documento. |
| `src/catalog/loader.py` | Carrega `data/base_marcamodelo.csv` em memória (dict `(marca, modelo) -> anos`) + suplemento manual + matching fuzzy (`match_anuncio`, usado por auditorias e por testes de confiança). |
| `src/pipeline/persistence.py` | Acesso ao PostgreSQL (`anuncios`, `historico_precos`, `search_log`). |
| `scripts/auditar_existencia_marca_modelo.py` | Relatório (dry-run) de pares marca/modelo sem referência no catálogo. |
| `scripts/corrigir_existencia_marca_modelo.py` | Aplica correções retroativas de existência (backup automático + `--apply`). |
| `scripts/reprocessar_saneamento_marca.py`, `reprocessar_saneamento_modelo.py` | Reprocessamento retroativo genérico (sanear o que já está salvo, não re-inferir do título). |

## 4. O catálogo de referência

`data/base_marcamodelo.csv` (26.201 linhas) é um dump real de marca/modelo/ano/versão — a mesma
fonte que qualquer tabela FIPE-like usaria. Cobre carros clássicos e raros (ENVEMO, WILLYS
OVERLAND, DE SOTO, BUGRE) além do catálogo moderno. `carregar_catalogo()` em `loader.py` lê esse
CSV uma vez (cache em memória, `resetar_cache()` só para teste) e monta:

```python
_catalogo: dict[tuple[str, str], set[int]]        # (MARCA, MODELO) -> {anos em que existiu}
_versoes:  dict[tuple[str, str, int], list[str]]  # (MARCA, MODELO, ano) -> versões canônicas
```

**Suplemento manual** (`_SUPLEMENTO` no mesmo arquivo): carros reais confirmados por título +
conhecimento histórico (ou pesquisa, quando necessário) mas ausentes do CSV — seja porque são raros
demais para o scrape original ter capturado (Simca Tufão, CBT Javali, Jeep Renegade), seja porque
a grafia da marca no banco é uma forma deliberadamente diferente do CSV (`"ASIA MOTORS"` no banco
vs. `"ASIA"` no CSV — ver `_MARCA_SUFIXO_ABSORVE`, seção 5). Cada entrada é
`(MARCA, MODELO): set(range(ano_inicio, ano_fim))`, com comentário explicando a fonte da
confirmação. **Nunca edita o CSV base** — tudo que não vem do scrape original entra aqui.

`match_anuncio()` faz o matching de um `Anuncio` contra esse catálogo: exato primeiro
(`(marca_norm, modelo_norm) in catalogo`), senão fuzzy por `difflib.SequenceMatcher` (marca ≥0.80,
depois modelo dentro dos modelos daquela marca ≥0.80), senão `unmatched`. Preenche
`match_confidence`/`match_strategy` no próprio `Anuncio`.

## 5. Pipeline de normalização (passo a passo)

### 5.1 Achar a marca (`_separar_marca` → `_separar_marca_core`)

Ordem de precedência, sobre os tokens já normalizados (maiúsculo, sem acento) do título ou do
campo "Marca":

1. **Prefixo de catálogo**, testando 3, depois 2, depois 1 token — cobre marcas compostas
   ("LAND ROVER", "MP LAFER"). Antes de aceitar o prefixo, checa `_MARCA_CANONICA`: se o prefixo
   inteiro bate lá, consome os tokens todos e devolve a forma canônica (não deixa a 2ª palavra
   sobrar). Ex.: `"WILLYS OVERLAND"` → `"WILLYS"` (consome as 2 palavras); `"DKW VEMAG"` → `"DKW"`.
2. **Alias** (`_ALIASES_MARCA`) — typos (`CHREVOLET`, `HOONDA`, `PORCHE`...) e abreviações (`VW`,
   `GM`→ nada, ver nota) apontando pra grafia canônica.
3. **Modelo exclusivo de uma marca** (`_MODELO_ABREVIACAO`/vocabulário do catálogo) — título começa
   direto pelo modelo ("Fusca 1600 1975" sem dizer "Volkswagen").
4. **Modelo ambíguo com marca dominante no clássico BR** (`_MODELO_AMBIGUO_MARCA`) — números que
   são modelo em mais de uma marca do catálogo geral, mas só uma leitura faz sentido no universo de
   carro clássico brasileiro (`"147"` → sempre FIAT, nunca Alfa Romeo 147 dos anos 2000).
5. **Fallback**: 1º token vira marca — a menos que seja uma palavra comum de português
   (`_PALAVRAS_NAO_MARCA`: adjetivo, conectivo, termo de venda), caso em que vira a sentinela
   `MARCA_NAO_IDENTIFICADA` em vez de inventar uma marca-lixo.

Depois de achar a marca, `_separar_marca` ainda:

- Descarta sufixo corporativo solto (`_SUFIXO_CORPORATIVO = {"MOTORS", "MOTOR"}`) — "Kia Motors
  Besta" → modelo não começa com "Motors". Absorve incondicionalmente pra "ASIA MOTORS" quando a
  marca é "ASIA" (`_MARCA_SUFIXO_ABSORVE`), porque a usuária decidiu que esse é o nome comercial
  completo, com ou sem "Motors" explícito no título.
- Descarta **eco da marca** (`_MODELO_ECO_MARCA`) e hífen solto logo depois da marca —
  `"Chevrolet - GM Blazer"` (GM é eco, não modelo), `"Mercedes Bens C180"` (Bens é eco/typo de
  Benz). Adicionado 2026-07-21; tabela é por marca porque a palavra descartável depende de qual
  marca já foi identificada.

`_resolver_willys_composto` (só no caminho de título, tem acesso ao `ano`) trata o caso especial
Ford/Willys: Ford comprou a Willys-Overland do Brasil em jan/1967, e o catálogo tem "Rural"
cadastrado nas duas marcas — resolve por ano (`< 1967` → WILLYS, senão FORD). "Aero Willys" é
sempre WILLYS (só existe assim no catálogo). CJ-5/CJ6 no título mantém marca JEEP.

### 5.2 Limpar o modelo (`sanear_modelo`)

Depois de identificar a marca, o resto dos tokens é o modelo cru — ainda com cauda de
especificação técnica que o anunciante colou no título ("Fusca 1300 Gasolina 2P Manual").
`sanear_modelo(marca, modelo_bruto)`:

1. Remove tokens da marca que vazaram pro modelo (repetição do ML: campo "Modelo" = "Fiat Palio").
2. Ancora o nome do modelo no catálogo (`_localizar_modelo`/`_achar_ancora_modelo`) — usa o maior
   prefixo de modelo conhecido pra aquela marca, protegendo números que são parte do nome
   ("Defender 110", "C 1504", "147") em vez de confundir com cilindrada solta.
3. Corta a cauda de spec a partir daí (`_indice_corte_spec`) — vocabulário reconhecido por
   dicionário (combustível, câmbio, injeção, portas) ou por forma de token (regex: `8V`, `V8`,
   `2P`, `50CV`, `1600` solto = cilindrada/ano).
4. `_limpar_tokens`: apara pontuação solta, dedup preservando ordem.

Mantém **nome + trim/versão juntos** num string só (decisão de 2026-07-17: `"Vectra GSI"`, não só
`"Vectra"` — trim pesa no preço). `separar_modelo_versao_obs` é a variante mais granular (usada
pelos conectores sem ficha técnica): devolve modelo, versão (GLX/SS/trim) e obs
(carroceria/tração: "Cabine Estendida", "4x4", "Sedan") em três campos, pra não poluir nem o
dropdown de versão nem descartar informação real do carro.

### Decomposição da versão (`decompor_versao`, 2026-08-04)

`separar_modelo_versao_obs` tira a versão de dentro do modelo; `decompor_versao` é o passo
seguinte, que separa a **própria versão** nos eixos que ela vinha misturando. O estudo da
variação achou 2.593 versões distintas pra 1.018 pares marca/modelo, com 2.287 dos 3.293 grupos
(marca, modelo, versão) tendo 1 ou 2 anúncios — inúteis pra média. A causa não era grafia: no Gol
conviviam trim (`CL`), geração (`GERACAO I`), série especial (`ROLLING STONES`), motorização
(`1.6 8V GASOLINA 2P MANUAL`) e modificação (`TURBO`) no mesmo campo, e cada combinação criava um
grupo novo.

| Eixo | Campo | Exemplo |
|---|---|---|
| trim/acabamento | `versao` | `CL`, `COMODORO`, `XR3` |
| geração | `geracao` | `I`, `II`, `III` (de "Geração I", "G.III", "G3", "quadrado") |
| motorização | `motor` | `1.6 8V GASOLINA` (cc vira litros: `1600` → `1.6`) |
| carroceria/tração | `obs` | `SW`, `HATCH`, `CABINE ESTENDIDA`, `4X4` |
| cor, câmbio, portas, venda | (descartado) | como já era |

Roda em `upsert_anuncios`, não nos conectores — pelo mesmo motivo do corte de ano e do descarte de
buggy/hot rod: vale pra toda fonte e não depende de o conector lembrar. A Webmotors provou a
necessidade: gravava `Version.Value` cru e era a única fonte da base com acento (1.418) e barra
(101) no campo.

**Idempotência** é requisito, não detalhe: o reprocessamento roda em cima do que já está gravado, e
os quatro campos precisam ser realimentados (`decompor_versao(marca, modelo, *resultado)` devolve o
mesmo resultado). Duas armadilhas achadas comparando duas passadas seguidas, ambas cobertas por
teste: (1) sem receber `geracao`/`motor` de volta, a função os devolvia vazios e o UPDATE apagava a
coluna; (2) carroceria que só é reconhecível depois de canonizada (`"Furg."`→FURGAO,
`"conv."`→CONVERSIVEL) ficava na versão na 1ª rodada e migrava pra obs só na 2ª. Os valores
prévios de `motor` e `geracao` são **revalidados** pelas regras atuais (o motor pelos seus próprios
tokens, a geração contra o título) em vez de aceitos como estão — assim uma regra nova alcança o
que já está no banco, mesmo sem o dado bruto original.

Duas peças de apoio:

- **Vocabulário de trim do catálogo** (`canonizar_trim`, em `catalog/loader.py`): tira a spec da
  coluna `nome_versao` do CSV base e indexa o trim que sobra por (marca, modelo). Casa exato ou
  por prefixo único, o que resolve os truncamentos das fontes (`VILL`→VILLAGE, `COMOD`→COMODORO,
  `DIPLOM`→DIPLOMATA) sem tabela na mão. O que ele não conhece é preservado e cai na quarentena.
- **Sentinela `VERSAO_AGREGADA`**: em parte da OLX (e no Socarrão, que copia a taxonomia dela), o
  "título" não é do anúncio — é o rótulo da linha inteira, enumerando todas as versões
  (`"Chevrolet Chevette L / SL / Sl/e / DL / SE 1.6 1987"`). A versão real não existe nesses
  anúncios, então é marcada em vez de fingir que `"L SL"` é um trim. O detector
  (`_e_enumeracao_versoes`) exige dois trims **do catálogo**, diferentes entre si, em lados opostos
  da mesma barra — o que separa a enumeração da barra usada como "com" (`"C/ reboque"`), da
  abreviação da mesma versão (`"Diplomata/diplom."`), de marca/modelo (`"Vw/fusca"`) e da
  cilindrada (`"4.1/2.5"`). Nomenclatura de uma versão só que usa barra (`SL/E`, `R/T`) vira um
  token antes disso (`_VERSAO_SINONIMO_FRASE`).

Duas etapas finais do saneamento do modelo, da 2ª passada da auditoria (2026-07-21), tratam a
fragmentação por grafia:

- **Descolar modelo grudado** (`_descolar_modelo_conhecido`, dentro de `_tokenizar_modelo`):
  separa um nome de modelo do catálogo grudado ao resto do token — `"Fusca1300"` vira
  `"Fusca 1300"`, `"EscortXr3"` vira `"Escort Xr3"`. Guardas: o token inteiro não pode ser ele
  próprio um modelo (`"Golf"` não vira `"Gol F"`), o prefixo precisa ter 4+ letras, e prefixos
  puramente numéricos são excluídos (o modelo VW `"1600"` colidiria com a cilindrada `"1600S"`).

- **Canonizar grafia** (`canonizar_modelo` em `catalog/loader.py`): unifica as variações de
  hífen/espaço do mesmo modelo numa só grafia — a do catálogo. `"D-20"` vira `"D20"`, `"C-180"`
  vira `"C 180"`, `"F1"` vira `"F-1"`. A autoridade de grafia é o CSV base (a forma mais frequente
  lá); o suplemento só preenche o que o CSV não tem. Sem isso, `"D-20"`, `"D 20"` e `"D20"` eram
  três grupos distintos do mesmo carro. O CSV é internamente inconsistente (grafa `"C 180"` com
  espaço mas `"D20"` sem) — segue-se a grafia exata do CSV por modelo; o objetivo é o banco ser
  consistente com o catálogo, não impor uma regra global de hífen.

### 5.3 Sentinelas e grupos preservados

- **`MARCA_NAO_IDENTIFICADA`** — nenhuma marca real reconhecível no título (24 anúncios, 0,08% do
  banco). O modelo guarda o título inteiro, pra revisão manual não perder informação.
- **`"BUGGY"`** — kit car brasileiro sem fabricante único identificável no título (decisão
  deliberada 2026-07-15: melhor um grupo genérico honesto do que adivinhar qual dos ~10
  fabricantes de buggy é). Ambas as sentinelas estão em `_MARCAS_PRESERVADAS` — `sanear_marca_modelo`
  nunca tenta reinterpretá-las.

## 6. Validação de existência (auditoria 2026-07-21)

Consistência interna não garante que o carro exista — "Willys"/"Overland" separados em
marca/modelo são grafias internamente consistentes, mas nenhuma delas sozinha é um modelo real.
`scripts/auditar_existencia_marca_modelo.py` cruza cada par `(marca, modelo)` distinto do banco
contra `carregar_catalogo()` (CSV + suplemento):

- **Match exato** ou **fuzzy** (mesmo algoritmo de `match_anuncio`) → validado, nenhuma ação.
- **Sem match** → precisa de revisão manual: ler o título original de amostra (impresso no
  relatório) pra decidir se é (a) carro real que só falta no suplemento, (b) bug de
  extração/eco/marca composta a corrigir na origem, ou (c) informação genuinamente insuficiente no
  título (mantido em branco, não force um valor).

`scripts/corrigir_existencia_marca_modelo.py` aplica as correções decididas: `BULK_FIXES` (todo
anúncio com o par velho vira o par novo) e `ROW_FIXES`/funções por-linha (`gerar_fixes_ford_willys`)
para os casos em que o mesmo par errado esconde carros diferentes por linha. Sempre dry-run por
padrão, `--apply` faz backup (`fazer_backup()`) antes de gravar.

**Resultado da rodada 2026-07-21:** de 1105 pares distintos, 545 exatos + 144 fuzzy já validados
sem ação; dos 416 sem match, corrigidos os ~40 grupos com 3+ anúncios (432 linhas), 24 pares novos
no suplemento, ~358 pares residuais (todos 1-2 anúncios, muitos de título de revenda citando vários
carros) documentados para rodada seguinte.

## 7. Como estender

| Situação | Onde mexer |
|---|---|
| Novo typo de marca (`"Chevorlet"`) | `_ALIASES_MARCA` |
| Marca composta com 2ª palavra que deve ser descartada (não é modelo) | `_MARCA_CANONICA` |
| Palavra solta que ecoa a marca já identificada (não é modelo) | `_MODELO_ECO_MARCA` |
| Modelo que só existe pra 1 marca no clássico BR mas é ambíguo no catálogo geral | `_MODELO_AMBIGUO_MARCA` |
| Carro real confirmado mas ausente do CSV | `_SUPLEMENTO` em `catalog/loader.py`, **nunca** editar o CSV |
| Grafia nova de spec/carroceria/venda que está vazando pro modelo | `_SPEC_*`, `_MODELO_OBSERVACAO` ou `_CARROCERIA_TRACAO` (qual, depende se deve virar obs ou ser descartada) |
| Grafia hífen/espaço fragmentando o mesmo modelo (`"D-20"` vs `"D20"`) | Já resolvido na raiz por `canonizar_modelo` — a grafia canônica vem do CSV base; ajustar lá se ficar ruim |
| Modelo do catálogo grudado ao resto (`"Fusca1300"`) | Já resolvido por `_descolar_modelo_conhecido` — só cobre prefixo alfabético 4+ letras |
| Typo de Willys no modelo | Já resolvido por `_GRAFIAS_WILLYS` no `_resolver_willys_composto` |
| Dado já salvo errado (não é bug de código, é histórico) | Script de reprocessamento novo, dry-run → resumo → `--apply` com backup (`scripts/reprocessar_grafia_e_modelo.py` é o modelo mais completo: Fase A grafia + Fase B título com guarda de catálogo + overrides por id) |

Ao mudar `normalizer.py`, rodar `pytest tests/test_normalizer.py` (regra geral do projeto: toda
correção de padrão vem com teste de regressão, não só o dado corrigido) e o restante da suíte
(`pytest tests/`, 333 testes em ~30s) antes de reprocessar o banco.

## 8. Linha do tempo (referência rápida)

| Quando | O quê |
|---|---|
| 2026-07-15 (3 rodadas no mesmo dia) | Marca-lixo virando marca real (ano solto, cilindrada), 92 marcas fora do catálogo geral (motos/tratores — cobertura, não bug), sentinela `MARCA_NAO_IDENTIFICADA` |
| 2026-07-17 | Achada a causa raiz real: ficha técnica do ML gravava campo "Marca" cru. Criado `sanear_marca_modelo`, aplicado retroativo — marcas distintas 256→118 |
| 2026-07-17 | `sanear_modelo` (corta spec do modelo, mantém trim) |
| 2026-07-20 | `separar_modelo_versao_obs` (versão e obs em campos próprios); correções pontuais (Toyota Bandeirante fragmentado, Mercedes Classe, cores) |
| 2026-07-21 (1ª passada) | Validação de **existência** contra catálogo real: 432 anúncios corrigidos, 24 no suplemento, causa raiz de marca-composta/eco corrigida no pipeline |
| 2026-07-21 (2ª passada) | Canonização de grafia (`D-20`→`D20`, raiz + 1076 anúncios), descolar modelo grudado (`Fusca1300`→`Fusca`), typos de Willys; `modelo='0'`/ano-vazado zerados. Pares distintos 1067→963 |
| 2026-08-04 | Auditoria da **versão**: `decompor_versao` (geração e motor em campos próprios), vocabulário de trim do catálogo, sentinela `VERSAO_AGREGADA`, Webmotors deixa de gravar cru. Versões distintas 2.593→1.339; anúncios em grupo com 3+ amostras 90%→93% |

## 9. Limitações conhecidas

- `_resolver_willys_composto` (ano decide Ford x Willys) só roda no caminho de **título livre**
  (`_inferir_marca_modelo_bruto_ano`) — a variante de ficha técnica estruturada
  (`sanear_marca_modelo`) não recebe `ano`. Não é problema hoje (só o OLX tem esse padrão, e OLX
  não usa ficha técnica — ver decisão em `docs/` de 2026-07-16 sobre isso), mas revisitar se mudar.
- ~256 pares marca/modelo (1-2 anúncios cada) continuam SEM_MATCH — mas a maioria são **nomes
  reais fora do catálogo** (modelos raros, motos), não erros; e ~30 são revenda multi-carro (título
  cita vários carros, sem modelo recuperável com segurança). `scripts/analisar_modelos_suspeitos.py`
  classifica cada par por tipo de problema; `scripts/auditar_existencia_marca_modelo.py` lista os
  sem-match crus.
- 46 anúncios ficaram com modelo vazio (hot rods pré-guerra, títulos de revenda sem modelo de
  fábrica) — vazio honesto em vez de um valor inventado. Somem da listagem por marca/modelo mas
  seguem no banco.
- O suplemento manual (`_SUPLEMENTO`) é código, não dado — cresce a cada rodada de auditoria e não
  tem mecanismo de expiração/revisão automática. Se o CSV base for atualizado no futuro, vale
  checar quais entradas do suplemento já passaram a existir lá (duplicata inofensiva, mas evitável).

## Auditoria da VERSÃO (2026-08-05)

Cruzamento do campo `versao` do banco com o vocabulário de trim do catálogo
(`_indice_trim`, extraído da coluna `nome_versao` do CSV base). Primeira vez que esse eixo foi
medido — as rodadas anteriores só olharam marca/modelo.

**Ponto de partida:** dos 33.351 anúncios, 19.425 (58%) têm versão. Desses, só **67,7%** tinham
todos os tokens reconhecidos pelo catálogo.

**O número engana nos dois sentidos.** O teste é contra um vocabulário derivado da Webmotors,
que cobre 869 dos 1.018 pares do banco e não lista trim nacional real. Conferindo os títulos
originais, o balde "não bate" tinha três causas bem diferentes:

1. **Banco certo, catálogo incompleto** — Corcel II "L", Belina "L", S10 "Luxe" são trims de
   fábrica. O título prova (`"Corcel II L 1979 com 55.000 km originais"`). Não é erro.
2. **Erro de extração** — corrigidos nesta rodada, ver abaixo.
3. **Valor certo, campo errado** — `C1`/`C4` da Corvette, `MK1` do Golf, `E34` do M5 são
   geração, não trim.

### O que foi corrigido no código

| Bug | Origem | Correção |
|---|---|---|
| versão `"DE"` (83 anúncios) | `"Band.Jipe Cap.de Aço"` — preposição de "capota **de** aço" | `_aparar_conectivos`: nenhum trim começa ou termina com preposição |
| versão `"VW"` (8) | `"Vw Fusca 1200"` — alias de marca vazou | `_tokens_redundantes` passou a incluir os aliases de `_ALIASES_MARCA` |
| versão `"AERO"` (30) | modelo `AERO-WILLYS` era um token só | `_tokens_redundantes` passou a quebrar no hífen |
| versão `"S-10"` em Blazer (36 no total) | nome de outro carro da marca | `_versao_e_so_outro_modelo` |
| versão `"IA"` (16) | `"328I /IA"` — sufixo de câmbio da forma agregada da OLX | entrou em `_SPEC_INJECAO` |
| `RT`/`SLE` não casavam (112) | o CSV grafa `R/T` e `SL/E`; a barra virava espaço e o vocabulário ficava com `R`+`T` | `_indice_trim` aplica `_VERSAO_SINONIMO_FRASE`, a mesma canonização do lado do anúncio |

**Duas armadilhas que o dry-run pegou** (e viraram teste de regressão):

- A regra de "modelo vazou" testava token a token e comia o `CHEYENNE` de
  `"Suburban Cheyenne Super 20"` — Cheyenne é modelo Chevrolet **e** trim de Suburban. Passou a
  exigir que a versão INTEIRA seja o nome do outro carro; nos 36 casos medidos era sempre assim.
- A poda de preposição rodava antes da checagem de modelo e transformava `"DE VILLE"` em
  `"VILLE"`, um trim que nunca existiu. A ordem foi invertida: modelo vazado primeiro.

Reprocessamento: 432 linhas alteradas, conformidade **67,7% → 70,8%**, combinações
(marca, modelo, versão) distintas 2.079 → 1.979.

### O que sobrou é curadoria, não código

637 combinações (1.334 anúncios) seguem sem reconhecimento, e a maior parte é catálogo
incompleto. Viraram a aba **"Versões a conferir"** de `/admin/pendencias`, classificadas em
`trim_provavel` (356), `sem_referencia` (275) e `geracao` (6). Decidir "É trim real" grava em
`data/suplemento_versao.csv`, que `_indice_trim` lê junto com o CSV base — o mesmo desenho do
`suplemento_manual.csv` pro eixo marca/modelo.

### Os 42% sem versão nenhuma

14.213 anúncios (42% da base). Investigados na sequência, e a suspeita inicial (o ML esconder o
dado na ficha técnica) estava errada — o problema é de extração e vale para todas as fontes.
A classe de cada um:

| Classe | Anúncios | O que é |
|---|---|---|
| `fonte_nao_diz` | 9.367 (66%) | o título só tem spec: "Fusca 1.3 8V Gasolina 2P". Não há trim a extrair |
| `recuperavel` | **3.284 (23%)** | o trim ESTÁ no título e não foi capturado: "Gol 1.8 Mi **Gl** 8v", "Civic 1.6 **Lx** 16v" |
| `sem_vocabulario` | 1.089 (8%) | o par não tem vocabulário de trim no catálogo |
| `enumeracao` | 473 (3%) | o título lista a linha inteira; deveria virar `VERSAO AGREGADA` |

**A causa dos recuperáveis é o corte de spec.** `_indice_corte_spec` interrompe a varredura no
primeiro token de spec, e nesses títulos o trim vem DEPOIS da cilindrada:

```
Chevrolet Blazer 1997 4.3 V6 Dlx 5p   ->  corta em "4.3", o DLX nunca é visto
Fiat Tempra 1994 Tempra Ouro 16v 2.0  ->  corta em "16v", perde o OURO
```

Não é o ano no meio do título (testado: mover o ano pro fim não muda nada) nem particularidade
do ML — é geral, e o ML só aparece mais por causa do formato de título dele.

**Cuidado ao medir isto de novo:** carroceria/tração (PICK-UP, FURGÃO, 4X4, COUPÉ) está no
vocabulário do catálogo mas o pipeline manda pra `obs` de propósito. Contá-la como "trim
perdido" inflava a conta de 3.284 pra 5.122 — quase o dobro. A primeira medição errou nisso.

Virou a aba **"Sem versão"** de `/admin/pendencias`, agrupada por marca/modelo — 14 mil linhas
não se tria à mão, e a pergunta que interessa ("onde há dado sendo perdido?") só aparece no
agregado.

### A correção: pescar o trim na cauda

`_trims_na_cauda` varre o que ficou DEPOIS do corte e recupera o que o catálogo avaliza como
trim daquele carro exato. A exigência do catálogo é o que permite pescar ali sem trazer junto o
resto da cauda, que é feita de spec e texto de venda ("aceito troca", "ótimo estado").

A correção mora em `separar_modelo_versao_obs`, que roda nos CONECTORES — então
`reprocessar_decomposicao_versao.py` não a alcança (ele parte do campo `versao`, que nesses
anúncios está vazio). Daí `scripts/reprocessar_trim_da_cauda.py`, que parte do TÍTULO, com duas
travas: só mexe onde `versao` está vazia, e só quando a marca/modelo re-inferidos BATEM com os
gravados. A segunda trava pulou 80 anúncios e evitou estragos reais —
`KARMANN-GHIA`→`KARMANN`, `380 SEC`→`380`, `E 320`→`BENZ`.

Dois ajustes que o dry-run exigiu:

- **Cilindrada casando com trim por prefixo.** O catálogo tem o trim `1.8S` no Gol, e a expansão
  por prefixo de `canonizar_trim` casava a cilindrada `1.8` com ele: "Gol 1.8 Mi Gl" virava
  versão `1.8 GL`. A cauda passou a descartar token de spec antes de consultar o catálogo.
- **Cor que é edição, não pintura.** "Gol Geração III **Ouro**" e "Tempra **Ouro**" perdiam o
  nome porque OURO está na lista de cores, cuja única exceção era vir depois de "Série". Agora
  a cor sobrevive também quando o catálogo a lista como trim daquele carro. A exceção é estreita:
  vale para 11 pares no catálogo inteiro (OURO, METAL, PRATA, PRETO). `PRATA` numa Caravan e
  `VERDE` num Fusca continuam descartados.

**Resultado.** Anúncios com versão: 19.425 → **22.570** (58% → 68% da base). Recuperáveis
pendentes na aba: 3.284 → **445** (86% resolvidos). Conformidade dos que têm versão: 70,8% →
**72,1%**.

O resíduo de 445 é o que a trava de par divergente pulou, mais casos onde o trim recuperado é
carroceria (vai pra `obs`) ou não está no catálogo — esses últimos dependem da curadoria da aba
"Versões a conferir"; assim que o trim entra no suplemento de versão, `_trims_na_cauda` passa a
pescá-lo sem mudança de código.

## O lixo que o próprio vocabulário avalizava (2026-08-07)

Os 445 "recuperáveis" acima eram quase todos falso positivo, e foi a **exportação da aba
"Sem versão"** que mostrou: lidos em CSV, os trims supostamente perdidos eram `I`, `6`, `DE`,
`E`. Não é que a extração falhasse — o vocabulário estava mandando pescar lixo.

`_indice_trim` tira a spec de `nome_versao` por duas listas que olham **um token por vez**.
Três formas de spec só se reconhecem pelo token VIZINHO e passavam batido:

| `nome_versao` | indexava | em | por quê |
|---|---|---|---|
| `2.8 6 CILINDROS` | `6` | 59 pares | `CILINDROS` é spec, mas o número antes dele não |
| `1.3 I SEDAN` | `I` | 34 pares | injeção, irmã de `MI`/`MPI`/`IE` que já eram spec |
| `TETO DE LONA`, `SUPER DE LUXE` | `DE` | 12 pares | conectivo |

E `_trims_na_cauda`, cuja regra é "confio no que o catálogo avaliza", pescava tudo isso de volta:
a Mercedes 280 SE ficou com versão `6`, o Gol com `I`, o Escort com `I XR3`.

`_e_trim_de_verdade` barra os três na origem. **A regra é posicional, não uma lista de tokens
proibidos** — `CARRERA 4` da Porsche e `MACH 1` do Mustang são trim de verdade, e o que separa
do `6` de `6 CILINDROS` é só o vizinho. Banir dígito solto destruiria os dois.

**A contrapartida:** `CUSTOM DE LUXE` (D20, Veraneio, Bonanza, A20) é nome real de trim. Tirar o
`DE` do vocabulário produziria `CUSTOM LUXE`, carro que não existe. Por isso o conectivo saiu do
vocabulário — onde significaria "vale por si" — e ganhou uma ponte em `_trims_na_cauda`: ele é
preservado quando está **entre dois trims aceitos e adjacentes**. Sozinho continua não sendo nada,
que é o que evita a versão `DE` da Bandeirante (83 anúncios, auditoria de 2026-08-05).

**Retroativo:** `scripts/reprocessar_vocabulario_limpo.py`. O escopo é calculado, não escrito à
mão — o script reconstrói o vocabulário ANTIGO e trata só os anúncios cuja versão contém um token
que o índice deixou de avalizar naquele par. Isso importa porque em boa parte da base a versão
**não vem do título**, vem do campo estruturado da ficha técnica; re-derivar tudo trocaria dado
bom por dado pior. 353 anúncios no escopo, 265 alterados (115 ficaram sem versão, porque a versão
era só o lixo), 0 pulados por par divergente.

**Resultado.** Recuperáveis na aba: 445 → **43**, e os 43 que sobram são reais (`A-10 de Luxe`,
`348 Tb`, `Ram 2500`, `Range Rover Hse`). Conformidade por combinação: 72,1% → **66,1%** — caiu,
e essa é a leitura certa: um token-lixo no vocabulário fazia combinações passarem por
conformes sem serem. Por anúncio a conformidade é 92,2%.

Os 88 anúncios inalterados são de duas naturezas: `CUSTOM DE LUXE` (73), que é a ponte
funcionando, e casos em que o token está no MIOLO do título, antes do corte de spec, onde o
vocabulário nunca mandou — `WOLFSBURG EDITION I` (de "Logus Wolfsburg Edition 2000i") e `SO 6`
(de "Mercedes 320 E SÓ 65.000 KM"). Esses são outro bug; ficam visíveis na fila "Versões a
conferir", que é onde a curadoria manual decide.
