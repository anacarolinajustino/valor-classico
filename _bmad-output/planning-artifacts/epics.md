---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
inputDocuments:
  - _bmad-output/planning-artifacts/briefs/brief-valor-classico-2026-05-29/brief.md
  - _bmad-output/planning-artifacts/briefs/brief-valor-classico-2026-05-29/addendum.md
  - _bmad-output/planning-artifacts/briefs/brief-valor-classico-2026-05-29/connectors-backlog.md
  - /Users/ana.justino/Downloads/base_dados_webmotors.csv
---

# valor-classico - Epic Breakdown

## Overview

Este documento define o desdobramento de epicos e historias do Valor Classico a partir do brief e backlog tecnico de conectores, com foco em entrega incremental de valor ao usuario final: consultar preco medio de carros antigos por modelo e ano com transparencia de amostra.

## Requirements Inventory

### Functional Requirements

FR1: O usuario deve conseguir pesquisar por modelo e ano do veiculo.
FR2: O sistema deve coletar anuncios de fontes externas suportadas.
FR3: O sistema deve normalizar dados de anuncios (preco, modelo, ano, metadados).
FR4: O sistema deve remover duplicidades e filtrar outliers extremos.
FR5: O sistema deve calcular preco medio e mediana por consulta.
FR6: O sistema deve exibir faixa de preco tipica (intervalo filtrado).
FR7: O sistema deve exibir tamanho da amostra usada na estimativa.
FR8: O sistema deve exibir data/hora da ultima atualizacao dos dados.
FR9: O sistema deve apresentar metrica de confianca da estimativa.
FR10: O sistema deve manter painel administrativo para status dos conectores.
FR11: O sistema deve degradar graciosamente quando uma ou mais fontes falharem.
FR12: O sistema deve permitir rollout progressivo de fontes por ondas (Fase 1, 2, 3).
FR13: O sistema deve registrar observabilidade por conector (sucesso, falha, latencia, volume).
FR14: O sistema deve incorporar dados de leiloes como sinal de preco realizado (fase posterior).
FR15: O sistema deve usar um catalogo canonico de marca, modelo, ano e versao para apoiar busca e normalizacao.

### NonFunctional Requirements

NFR1: Tempo medio de resposta de consulta <= 8 segundos para buscas com cache.
NFR2: Disponibilidade parcial da resposta mesmo com falha de algum conector.
NFR3: Compliance por fonte (ToS, robots, rate limits, politica de acesso) antes de producao.
NFR4: Arquitetura modular de conectores para facilitar manutencao e expansao.
NFR5: Rastreabilidade e monitoramento operacional minimo por fonte.
NFR6: Precisao estatistica robusta usando mediana e filtros de dispersao.
NFR7: Transparencia para o usuario sobre qualidade da amostra.

### Additional Requirements

- Contrato canonico de anuncio versionado (schema comum para todas as fontes).
- Pipeline de limpeza, dedupe e enriquecimento reaproveitado por todos os conectores.
- Feature flags para ativacao/desativacao de fonte por ambiente.
- Fallback tecnico para fontes parcialmente renderizadas em JS (Playwright quando necessario).
- Separacao de sinal de "anuncio" versus "preco realizado de leilao" no modelo analitico.
- Facebook Marketplace fica fora do MVP inicial por bloqueio tecnico e de acesso.
- Ingestao de catalogo base de veiculos para desambiguacao de busca e matching de entidades.

### UX Design Requirements

UX-DR1: Formulario simples com campos "modelo" e "ano" com validacao clara e apoio de busca assistida.
UX-DR2: Resultado deve destacar preco medio, mediana e faixa tipica de forma legivel.
UX-DR3: Exibir bloco de confianca com tamanho da amostra, recencia e dispersao.
UX-DR4: Exibir estados de carregamento, vazio e erro por consulta.
UX-DR5: Layout responsivo para mobile e desktop.
UX-DR6: Exibir fontes utilizadas na resposta para transparencia.

### FR Coverage Map

FR1: Epic 1 - Consulta e experiencia de busca.
FR2: Epic 2 e Epic 4 - Conectores por ondas.
FR3: Epic 1 - Normalizacao inicial e contrato de dados.
FR4: Epic 1 - Dedupe e filtros de outlier.
FR5: Epic 1 - Calculo estatistico base.
FR6: Epic 1 - Exibicao de faixa tipica.
FR7: Epic 1 - Exibicao de tamanho de amostra.
FR8: Epic 1 - Exibicao de ultima atualizacao.
FR9: Epic 3 - Score de confianca e transparencia.
FR10: Epic 3 - Painel administrativo de fontes.
FR11: Epic 3 - Degradacao graciosa entre conectores.
FR12: Epic 2 e Epic 4 - Rollout por fases.
FR13: Epic 3 - Observabilidade operacional.
FR14: Epic 5 - Integracao de dados de leiloes.
FR15: Epic 1 - Busca assistida e normalizacao via catalogo.

## Epic List

### Epic 1: Consulta de Preco MVP
Entregar busca por modelo+ano com resposta estatistica confiavel (media, mediana, faixa, amostra e recencia) usando pipeline de dados padrao.
**FRs covered:** FR1, FR3, FR4, FR5, FR6, FR7, FR8, FR15

### Epic 2: Coleta de Mercado - Onda 1
Conectar fontes viaveis de maior impacto para disponibilizar cobertura inicial util no go-live.
**FRs covered:** FR2, FR12

### Epic 3: Confianca Operacional e Governanca
Garantir confiabilidade do produto com score de confianca, observabilidade, painel administrativo e degradacao graciosa.
**FRs covered:** FR9, FR10, FR11, FR13

### Epic 4: Expansao de Cobertura - Onda 2
Ampliar cobertura com fontes parciais e especializadas para melhorar representatividade dos resultados.
**FRs covered:** FR2, FR12

### Epic 5: Sinal Premium de Leiloes
Integrar resultados de leiloes como dado complementar para aumentar qualidade da avaliacao de classicos.
**FRs covered:** FR14

## Epic 1: Consulta de Preco MVP

Entregar a experiencia principal de consulta de valor para que o usuario receba uma referencia de mercado clara, transparente e util para tomada de decisao.

### Story 1.1: Busca por modelo e ano

As a comprador ou vendedor de carro antigo,
I want informar modelo e ano em uma busca simples,
So that eu consiga iniciar a consulta de valor rapidamente.

**Acceptance Criteria:**

**Given** que estou na pagina inicial
**When** preencho modelo e ano validos e envio a busca
**Then** o sistema inicia a consulta e retorna um estado de carregamento
**And** valida entradas invalidas com mensagem clara.

### Story 1.2: Catalogo canonico para busca assistida

As a usuario final,
I want receber sugestoes consistentes de marca, modelo, ano e versao,
So that eu encontre o veiculo correto com menos ambiguidade.

**Acceptance Criteria:**

**Given** um catalogo base de veiculos carregado no sistema
**When** eu digito uma marca ou modelo na busca
**Then** o sistema sugere entradas canonicas correspondentes
**And** usa essa entidade padronizada para apoiar a consulta.

### Story 1.3: Contrato canonico e normalizacao de anuncios

As a sistema de avaliacao,
I want normalizar anuncios de diferentes fontes em um schema unico,
So that os calculos estatisticos usem dados consistentes.

**Acceptance Criteria:**

**Given** anuncios brutos de fontes diferentes
**When** o pipeline de normalizacao processa os registros
**Then** todos os campos obrigatorios do schema canonico sao preenchidos
**And** registros invalidos sao marcados e excluidos dos calculos.

### Story 1.4: Dedupe e filtro de outliers

As a usuario final,
I want que anuncios duplicados e precos absurdos sejam filtrados,
So that a estimativa final fique mais realista.

**Acceptance Criteria:**

**Given** um conjunto de anuncios com duplicidades e valores extremos
**When** o processo de limpeza e aplicado
**Then** duplicidades por URL/hash sao removidas
**And** outliers fora da regra definida sao excluidos da amostra valida.

### Story 1.5: Calculo de media, mediana e faixa tipica

As a usuario final,
I want ver media, mediana e faixa de preco,
So that eu tenha referencia objetiva para negociar.

**Acceptance Criteria:**

**Given** uma amostra valida apos limpeza
**When** o motor estatistico executa o calculo
**Then** media e mediana sao retornadas com precisao monetaria padrao
**And** faixa tipica e calculada por regra documentada.

### Story 1.6: Resultado transparente ao usuario

As a usuario final,
I want ver tamanho da amostra e recencia dos dados,
So that eu entenda o nivel de confianca do resultado.

**Acceptance Criteria:**

**Given** uma resposta de consulta concluida
**When** os resultados sao exibidos
**Then** a interface mostra tamanho da amostra e ultima atualizacao
**And** exibe as fontes utilizadas na composicao da estimativa.

## Epic 2: Coleta de Mercado - Onda 1

Conectar as fontes de maior retorno para disponibilizar uma base inicial robusta no MVP.

### Story 2.1: Conector Mercado Livre via API oficial

As a plataforma Valor Classico,
I want integrar Mercado Livre por API oficial,
So that eu tenha alto volume de anuncios com custo tecnico controlado.

**Acceptance Criteria:**

**Given** credenciais e endpoints oficiais configurados
**When** uma consulta por modelo e ano e executada
**Then** anuncios do Mercado Livre sao ingeridos no schema canonico
**And** falhas de API sao tratadas com retry e log estruturado.

### Story 2.2: Conector OLX Brasil

As a plataforma Valor Classico,
I want coletar anuncios da OLX com parser resiliente,
So that eu aumente cobertura de mercado de particulares.

**Acceptance Criteria:**

**Given** paginas de busca da OLX disponiveis
**When** o conector executa a coleta
**Then** anuncios relevantes sao extraidos e normalizados
**And** mudancas de layout criticas geram alerta operacional.

### Story 2.3: Conector Netmotors (incluindo categoria colecionador)

As a plataforma Valor Classico,
I want integrar Netmotors e sua categoria de colecionador,
So that eu capture sinais qualificados de carros antigos.

**Acceptance Criteria:**

**Given** consultas ativas para modelo e ano
**When** o conector Netmotors processa resultados
**Then** anuncios da categoria colecionador entram no pipeline
**And** o conector publica metricas de volume e latencia.

### Story 2.4: Conectores Maxicar e Super Antigo

As a plataforma Valor Classico,
I want integrar dois portais especializados de antigos,
So that eu melhore a representatividade de nicho no MVP.

**Acceptance Criteria:**

**Given** regras de parser para Maxicar e Super Antigo
**When** a coleta periodica roda
**Then** anuncios de antigos sao ingeridos e deduplicados
**And** falhas por fonte nao interrompem as demais coletas.

### Story 2.5: Conector Atelie do Carro

As a plataforma Valor Classico,
I want integrar Atelie do Carro como referencia especializada,
So that eu acrescente sinal de mercado com curadoria de loja.

**Acceptance Criteria:**

**Given** pagina de listagem da fonte disponivel
**When** o conector executa
**Then** anuncios da fonte entram no modelo canonico
**And** a fonte aparece no detalhamento de origem da consulta.

## Epic 3: Confianca Operacional e Governanca

Garantir que o produto funcione com qualidade e transparencia mesmo sob variacao de fontes.

### Story 3.1: Score de confianca da estimativa

As a usuario final,
I want um score de confianca visivel,
So that eu saiba quando confiar mais ou menos no preco exibido.

**Acceptance Criteria:**

**Given** resultado com amostra processada
**When** o score e calculado
**Then** o score considera tamanho de amostra, recencia e dispersao
**And** a interface exibe explicacao resumida do score.

### Story 3.2: Degradacao graciosa por falha de conector

As a usuario final,
I want receber resultado parcial mesmo com fonte indisponivel,
So that eu nao fique sem resposta total da consulta.

**Acceptance Criteria:**

**Given** falha em uma ou mais fontes durante a coleta
**When** a consulta termina
**Then** o sistema retorna resultado com fontes restantes validas
**And** sinaliza no detalhe quais fontes falharam.

### Story 3.3: Painel administrativo de fontes

As a operador da plataforma,
I want visualizar status dos conectores,
So that eu consiga agir rapidamente em falhas de coleta.

**Acceptance Criteria:**

**Given** acesso ao painel administrativo
**When** abro a visao de fontes
**Then** vejo status, ultima execucao, latencia e volume por conector
**And** consigo filtrar por fonte com falha recente.

### Story 3.4: Camada de compliance por fonte

As a time de produto,
I want controlar ativacao de fontes apenas apos validacao juridica,
So that o sistema opere dentro de politicas de acesso permitidas.

**Acceptance Criteria:**

**Given** cadastro de politicas por fonte
**When** uma fonte nao esta aprovada
**Then** o conector permanece desativado em producao
**And** o painel mostra o motivo de bloqueio/compliance.

## Epic 4: Expansao de Cobertura - Onda 2

Ampliar cobertura com fontes adicionais e parcialmente JS para aumentar robustez estatistica.

### Story 4.1: Integracao iCarros com fallback JS

As a plataforma Valor Classico,
I want integrar iCarros com estrategia hibrida,
So that eu obtenha dados mesmo em paginas parcialmente renderizadas em JavaScript.

**Acceptance Criteria:**

**Given** tentativa de coleta por requests
**When** os dados essenciais nao forem encontrados
**Then** o fluxo usa fallback Playwright para concluir extracao
**And** o custo de execucao e monitorado por consulta.

### Story 4.2: Integracao Webmotors via Playwright

As a plataforma Valor Classico,
I want coletar Webmotors via browser automation,
So that eu amplie cobertura de anuncios de alta relevancia no Brasil.

**Acceptance Criteria:**

**Given** ambiente headless configurado
**When** o conector Webmotors roda
**Then** anuncios sao coletados com estabilidade minima definida
**And** bloqueios/timeout sao registrados com telemetria.

### Story 4.3: Integracao de portais e lojas especializadas restantes

As a plataforma Valor Classico,
I want adicionar as demais fontes especializadas da Onda 2,
So that a base de classicos fique mais representativa por nicho e regiao.

**Acceptance Criteria:**

**Given** conectores configurados para Armazem do Vovo, Retroauto, Clube da Caminhonete, LART, Brunelli, Classic Car BR, JS Autos Antigos e Franz
**When** a coleta periodica executa
**Then** cada fonte publica metricas individuais de volume/sucesso
**And** anuncios entram no pipeline canonico sem quebrar consultas existentes.

## Epic 5: Sinal Premium de Leiloes

Adicionar dados de precos realizados para enriquecer a inteligencia de avaliacao.

### Story 5.1: Integracao Circuito de Leiloes

As a usuario final,
I want que dados de leiloes sejam usados como sinal complementar,
So that eu tenha referencia mais forte para carros classicos de baixa liquidez.

**Acceptance Criteria:**

**Given** catalogos/resultados disponiveis da fonte
**When** o conector de leilao processa os dados
**Then** precos realizados sao armazenados separadamente de anuncios
**And** a consulta indica quando o sinal de leilao foi considerado.

### Story 5.2: Integracao CARDE / Magalhaes Gouvea

As a usuario final,
I want incluir outra fonte de leilao de prestigio na analise,
So that a estimativa reflita melhor o mercado de classicos premium.

**Acceptance Criteria:**

**Given** dados de lotes/resultados da fonte
**When** a ingestao e executada
**Then** modelo, ano e preco realizado sao mapeados corretamente
**And** o motor de estimativa aplica regra de ponderacao documentada para esse sinal.

### Story 5.3: Calibracao estatistica com sinal de leilao

As a time de produto,
I want calibrar o peso de anuncios versus leiloes,
So that o preco final seja util em segmentos populares e premium.

**Acceptance Criteria:**

**Given** consultas com e sem dados de leilao
**When** o algoritmo final calcula a estimativa
**Then** a ponderacao segue regra configuravel por perfil de veiculo
**And** testes comparativos comprovam melhora de consistencia em casos de classicos.
