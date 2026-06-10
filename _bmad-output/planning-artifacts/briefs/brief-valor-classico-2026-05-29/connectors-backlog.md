---
title: "Backlog Tecnico - Conectores de Fontes"
status: draft
created: 2026-05-29
updated: 2026-05-29
---

# Backlog Tecnico de Conectores (Valor Classico)

## Escala usada

- Esforco P: 1-2 dias uteis
- Esforco M: 3-5 dias uteis
- Esforco G: 6-10 dias uteis
- Risco: Baixo, Medio, Alto

## Pre-requisitos transversais (Sprint 0)

| ID | Item | Esforco | Risco | Dependencias | Criterio de pronto |
|---|---|---|---|---|---|
| INF-01 | Definir contrato canonico de anuncio (titulo, preco, ano, modelo, URL, data_coleta, fonte, localizacao, km, versao) | M | Medio | Nenhuma | Schema versionado aprovado e validadores em testes. |
| INF-02 | Implementar pipeline comum de limpeza e deduplicacao | M | Medio | INF-01 | Regras de outlier, dedupe por URL/hash e normalizacao de moeda funcionando. |
| INF-03 | Implementar score de confianca por consulta | M | Medio | INF-01, INF-02 | Score considera amostra, recencia e dispersao, com documentacao. |
| INF-04 | Camada de compliance por fonte (ToS, robots, rate limit, user-agent policy) | M | Alto | Nenhuma | Checklist por fonte preenchido e bloqueio automatico de fontes nao aprovadas. |
| INF-05 | Observabilidade de conectores (sucesso, falha, latencia, volume) | P | Baixo | INF-01 | Dashboard basico com metricas por conector. |
| INF-06 | Ingestao do catalogo base de veiculos (marca, modelo, ano, versao) para busca assistida e normalizacao | M | Baixo | INF-01 | Importador do CSV ativo, entidades canonicas consultaveis e matching basico funcionando. |

Especificacao detalhada de catalogo e matching em [catalog-search-matching-spec.md](../../catalog-search-matching-spec.md).

## Onda 1 - MVP imediato

| Ordem | ID | Fonte | Tecnica | Esforco | Risco | Dependencias | Criterio de pronto |
|---|---|---|---|---|---|---|---|
| 1 | C01 | Mercado Livre | API oficial REST | M | Baixo | INF-01, INF-02, INF-04 | Busca por modelo+ano retorna dados normalizados com paginacao e retries. |
| 2 | C02 | OLX Brasil | requests + BeautifulSoup | M | Medio | INF-01, INF-02, INF-04 | Extracao estavel em 3 ciclos consecutivos sem quebra critica. |
| 3 | C03 | Netmotors | requests + BeautifulSoup | P | Medio | INF-01, INF-02, INF-04 | Categoria colecionador mapeada e integrada ao calculo. |
| 4 | C04 | Maxicar | requests + BeautifulSoup | P | Baixo | INF-01, INF-02, INF-04 | Captura anuncios relevantes de antigos com parse consistente. |
| 5 | C05 | Super Antigo | requests + BeautifulSoup | P | Baixo | INF-01, INF-02, INF-04 | Coleta filtrada por modelos/anos ate 1999. |
| 6 | C06 | Atelie do Carro | requests + BeautifulSoup | P | Baixo | INF-01, INF-02, INF-04 | Fonte integrada e refletida no score de confianca. |

## Onda 2 - Expansao de cobertura

| Ordem | ID | Fonte | Tecnica | Esforco | Risco | Dependencias | Criterio de pronto |
|---|---|---|---|---|---|---|---|
| 7 | C07 | iCarros | requests + BS4 / Playwright | M | Medio | C01-C06, INF-05 | Fallback para browser quando HTML nao trouxer dados completos. |
| 8 | C08 | Webmotors | Playwright | G | Alto | C01-C07, INF-05 | Fluxo headless robusto com tratamento de bloqueio e timeout. |
| 9 | C09 | Armazem do Vovo | requests + BeautifulSoup | P | Baixo | C01-C06 | Fonte integrada com classificacao de nicho premium. |
| 10 | C10 | Retroauto | requests + BeautifulSoup | P | Baixo | C01-C06 | Integracao ativa com monitoramento de volume baixo/medio. |
| 11 | C11 | Clube da Caminhonete | requests + BeautifulSoup | P | Baixo | C01-C06 | Captura de carros/caminhonetes/motos com taxonomia clara. |
| 12 | C12 | LART Veiculos Antigos | requests + BeautifulSoup | P | Baixo | C01-C06 | Integracao homologada para anuncios premium SP. |
| 13 | C13 | Brunelli Veiculos Antigos | requests + BeautifulSoup | P | Baixo | C01-C06 | Integracao homologada para anuncios premium. |
| 14 | C14 | Classic Car BR | requests + BeautifulSoup | P | Baixo | C01-C06 | Integracao homologada para compra/venda/consignacao. |
| 15 | C15 | JS Autos Antigos | requests + BeautifulSoup | P | Baixo | C01-C06 | Integracao homologada para anuncios em SP. |
| 16 | C16 | Franz Veiculos Antigos | requests + BeautifulSoup | P | Baixo | C01-C06 | Integracao homologada com foco Sul + nacional. |

## Onda 3 - Dados premium (precos realizados)

| Ordem | ID | Fonte | Tecnica | Esforco | Risco | Dependencias | Criterio de pronto |
|---|---|---|---|---|---|---|---|
| 17 | C17 | Circuito de Leiloes | requests + BS4 / Playwright | M | Medio | C01-C16, INF-03 | Precos realizados incorporados como sinal separado de anuncios. |
| 18 | C18 | CARDE / Magalhaes Gouvea | requests + BeautifulSoup | M | Medio | C01-C16, INF-03 | Resultados de leilao extraidos com mapeamento de lote/modelo/ano. |

## Fora do MVP

| ID | Fonte | Status | Justificativa | Possivel reentrada |
|---|---|---|---|---|
| C19 | Facebook Marketplace | Bloqueado | Login obrigatorio e anti-bot agressivo | Somente com parceria, API oficial ou fornecedor terceirizado. |

## Nota metodologica: preco pedido vs. preco realizado

Nem todas as fontes produzem o mesmo tipo de dado. A distinção é metodologicamente crítica:

- **Preço pedido** (anúncios, portais, lojas): o vendedor define o preço. Sujeito a ancoragem, outliers e veículos fora de padrão.
- **Preço realizado** (leilões com venda confirmada): o mercado define o preço. É o dado mais próximo do valor de referência real.

O sistema trata esses dois tipos como sinais distintos no pipeline de agregação. Fontes de preço realizado (C17, C18) recebem peso 1.5x na média ponderada; lojas especializadas (Tier 2) recebem 1.2x; classificados gerais (Tier 3) recebem 1.0x ou 0.8x conforme dispersão histórica. Ver tabela completa em [source-governance.md](source-governance.md).

Essa separação é a diferença entre um agregador de anúncios e uma referência de mercado — análoga ao modelo do Hagerty Price Guide nos EUA.

## Ordem sugerida de sprints (revisada)

1. Sprint 0: INF-01 a INF-06.
2. Sprint 1 (portal-first): C04, C05, C06.
3. Sprint 2: **C01 (ML API)** + **C17 (Circuito de Leiloes)** — API zero fricção + dado de preço realizado que diferencia o produto.
4. Sprint 3: C02, C03, C09, C10, C11.
5. Sprint 4: C07, C08 e lojas especializadas C12-C16.
6. Sprint 5: C18 + recalibração do score com pesos de tier.

Justificativa da mudança: C17 subiu do Sprint 5 para o Sprint 2 porque preço realizado de leilão é o ativo diferenciador do produto. Com +9.500 vendas no Circuito de Leilões, é possível construir curva histórica por modelo — algo que nenhum agregador de anúncios brasileiro tem.

Governanca de decisao por fonte (API vs HTML, criterios go/no-go e tabela de pesos) em [source-governance.md](source-governance.md).

## Criterios de aceite globais

1. Cada conector precisa de testes de parse em amostras reais salvas (snapshot tests).
2. Falha de um conector nao pode derrubar a consulta final (degradacao graciosa).
3. Toda resposta ao usuario deve exibir tamanho de amostra e data da coleta mais recente.
4. Conectores sem compliance aprovado permanecem desativados em producao.
