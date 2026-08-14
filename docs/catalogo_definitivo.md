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

## A tabela mostra só o que se decide

Marca, modelo, versão, anos e as ações. **A procedência e a contagem de
anúncios saíram da tabela** (2026-08-13): a pergunta ali é "este carro existe
e com que anos", e de onde a informação veio não muda a resposta.

A unificação continua acontecendo por trás — as sete fontes seguem sendo
lidas e a faixa exibida continua sendo a união delas. O que mudou é o que a
tela mostra.

Sobrevive um lugar onde a procedência aparece: **dentro do editor**, na linha
"Origem". Quando se está mexendo em `ano_min`/`ano_max`, saber que o catálogo
estrangeiro diz 1959–1986 e os anúncios dizem 1962–1996 é a evidência que
justifica o número escolhido. Fora do editor, não aparece em lugar nenhum.

## Ordenar

Clique no cabeçalho da coluna: o primeiro clique ordena crescente, o segundo
inverte, o terceiro volta ao padrão. O terceiro estado existe pra dar saída —
sem ele, escolher uma coluna por engano prenderia a lista nela. O botão
"Ordem padrão" também limpa.

Ordenam **Marca**, **Modelo**, **Versão**, **Anos** e **Ações** (esta última
agrupa por situação: confirmado, descartado, pendente).

A ordenação é feita **no servidor, sobre o conjunto inteiro**. Ordenar no
navegador ordenaria só as 100 linhas à vista, e a lista mudaria de critério a
cada página.

Linha sem ano vai pro fim nas duas direções da ordenação por ano. Invertida,
ela encabeçaria a lista com um vazio — o pior lugar possível pra quem está
procurando faixa.

## O que a ordenação por ano revela

Ordenar por **Anos** é a maneira mais rápida de achar dado ruim, porque o
catálogo unificado **não é filtrado por ano** (diferente da base de anúncios,
que corta em 2000):

- **2.395 combinações com ano acima de 2000** — Chevrolet Montana 2023–2025 e
  companhia, que vieram do catálogo da Webmotors e estão fora do escopo de
  carro clássico.
- **5.597 sem ano nenhum** — a maioria do vocabulário de trim, que não traz
  faixa.
- **1 com ano abaixo de 1900** — `BUGRE III 1796–1977`, erro do
  `base_dados_webmotors.csv`.

Nada disso é filtrado automaticamente: são justamente as linhas que a
curadoria existe pra descartar.

## Por onde começar

Os contadores no topo são clicáveis e recortam a lista.

**Aparecem em anúncios** (2.770) é o recorte que rende: são as combinações
que o mercado de fato mostrou, e as únicas que afetam o índice publicado.
Triar as outras 17 mil, que vieram só de catálogo, é trabalho sem retorno
imediato.

Depois disso, filtrar por marca e ordenar alfabeticamente dá uma fila
previsível — dá pra fechar uma marca inteira por vez.

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
