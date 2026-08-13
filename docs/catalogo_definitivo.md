# Catálogo definitivo

`/admin/catalogo` — as sete fontes de marca, modelo e versão numa tabela só,
com curadoria linha a linha.

O funcionamento está no cabeçalho de `src/catalog/unificado.py` e não se
repete aqui. Este documento é o mapa de trabalho: o que a tela mostra, o que
cada botão faz, e por onde começar a triar.

## O problema

O conhecimento sobre "que carro existe" estava em sete lugares que ninguém
compara de cabeça:

| fonte | granularidade | anos | trios |
|---|---|---|---|
| anúncios coletados | marca+modelo+versão | min/max observados | 2.770 |
| Webmotors | marca+modelo+versão | min/max dos `ano_modelo` | 5.923 |
| Webmotors (bruto) | idem, snapshot anterior | idem | 5.948 |
| catálogo estrangeiro | marca+modelo+versão | `ano_min`/`ano_max` | 5.959 |
| vocabulário de trim | marca+modelo+trim | **nenhum** | 6.065 |
| suplemento do código | marca+modelo | conjunto de anos | 89 |
| suplemento manual | marca+modelo | `ano_min`/`ano_max` | 61 |

Unificados: **20.109 trios** (marca, modelo, versão) e **6.197 pares**, em 424
marcas.

## O que a tela não faz

**Não altera anúncio nenhum.** A curadoria grava em
`data/catalogo_definitivo.csv` e a base coletada segue como registro do que
foi encontrado — decisão da usuária em 2026-08-12. Aplicar as correções
retroativamente aos anúncios é trabalho de um script separado, com dry-run e
backup, como nas rodadas de saneamento anteriores.

## Os botões

| botão | efeito |
|---|---|
| **Editar** | abre os campos de marca, modelo, versão e faixa de anos; salvar já confirma |
| **Confirmar** | entra no catálogo definitivo como está |
| **Descartar** | não é carro válido pro catálogo |
| **Reabrir** | apaga a decisão e devolve a linha à fila |

Reabrir **apaga** a linha do arquivo em vez de gravar "pendente": voltar atrás
tem que devolver a linha ao estado original, e uma linha "pendente" gravada
seria indistinguível de curadoria já feita.

## A chave é a origem, não o nome corrigido

Cada decisão é gravada contra o trio de **origem** (`marca_origem`,
`modelo_origem`, `versao_origem`). O índice é reconstruído das fontes a cada
carga e a decisão se sobrepõe a ele por essa chave.

Sem isso, corrigir "GOL CL" para "GOL CL 1.6" perderia o vínculo com a linha
que originou a decisão, e ela reapareceria como pendente na carga seguinte.

## Por onde começar

Os contadores no topo são clicáveis e recortam a lista.

1. **Com anúncios** (2.770) — são as combinações que afetam o índice
   publicado. Triar aqui rende mais que triar as outras 17 mil.
2. **Com uma fonte só** (13.472) — onde mora tanto o achado legítimo quanto o
   lixo. Combinado com "com anúncios", isola o que só os nossos anúncios
   afirmam e nenhum catálogo confirma: 2.499 trios, e é o recorte mais
   suspeito da base.
3. Ordenar por **menos fontes primeiro** dentro de uma marca dá a fila de
   maior risco daquela marca.

O crachá de cada fonte tem a faixa de anos dela no tooltip. Quando duas
discordam, o intervalo exibido é a união — e é no tooltip que se vê qual das
duas está esticando.

## Exportar

O seletor "Baixar CSV" leva o que foi **confirmado** (o produto da curadoria),
o **descartado** (pra revisar o que se jogou fora) ou o **pendente** (a fila,
pra trabalhar fora do painel). Formato brasileiro: `;`, BOM, CRLF.

## Cache

O índice é construído uma vez por processo (~2,3 s, lê 40 mil linhas de CSV
mais uma agregação do banco) e fica em memória. As **decisões** são relidas a
cada listagem, então a curadoria aparece na hora.

Depois de uma coleta nova ou de editar um CSV de fonte à mão, o índice fica
velho: reiniciar o app resolve, ou chamar
`src.catalog.unificado.invalidar_cache()`.
