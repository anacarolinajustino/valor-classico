---
title: "Backlog Tecnico - Conectores de Fontes"
status: draft
created: 2026-05-29
updated: 2026-06-10
---

# Backlog Tecnico de Conectores (Valor Classico)

> **Atualização 2026-06-10:** incorporadas as fontes novas da pesquisa de descoberta v2
> ([connectors-research-v2.md](../../connectors-research-v2.md)) — C20 a C29 e PAR-01.

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
| 12 | C12 | LART Veiculos Antigos | requests + BeautifulSoup | P | Baixo | C01-C06 | Integracao homologada para anuncios premium SP. ⚠️ Pesquisa v2: muitos anuncios "preco sob consulta" — baixo valor para scraping de preco; validar proporcao no spike antes de comprometer sprint. |
| 13 | C13 | Brunelli Veiculos Antigos | requests + BeautifulSoup | P | Baixo | C01-C06 | Integracao homologada para anuncios premium. |
| 14 | C14 | Classic Car BR | requests + BeautifulSoup | P | Baixo | C01-C06 | Integracao homologada para compra/venda/consignacao. |
| 15 | C15 | JS Autos Antigos | requests + BeautifulSoup | P | Baixo | C01-C06 | Integracao homologada para anuncios em SP. |
| 16 | C16 | Franz Veiculos Antigos | requests + BeautifulSoup | P | Baixo | C01-C06 | Integracao homologada com foco Sul + nacional. |
| 19 | C20 | WebClassicos | requests + BeautifulSoup | P | Baixo | C01-C06 | Classificados C2C de nicho (no ar desde ~2011, oficial do Encontro Paulista). Spike retorna marca/modelo/ano/preco/url/data para >= 90% dos anuncios. Site antigo — verificar qualidade do HTML. |
| 20 | C21 | Classificados Classicos | requests + BeautifulSoup | P | Baixo | C01-C06 | Classificados C2C de alcance nacional (96K seguidores no Instagram). Validar volume real no site vs. Instagram durante o spike. |
| 21 | C22 | SoCarrao (carros-classicos) | requests + BS4 / Playwright | M | Medio | C01-C06, INF-05 | Categoria dedicada com filtros estruturados (marca, ano, preco, cambio). Site comercial — spike anti-bot antes de comprometer sprint. |
| 22 | C23 | Pastore Car Collection | requests + BeautifulSoup | P | Baixo | C01-C06 | Loja de curadoria (Bento Goncalves-RS), uma das maiores do segmento. Flag `tipo_fonte: loja` (Tier 2, peso 1.2x). |
| 23 | C24 | The Garage | requests + BeautifulSoup | P | Baixo | C01-C06 | Loja de curadoria com grande estoque de classicos (SP). Flag `tipo_fonte: loja` (Tier 2, peso 1.2x). |
| 24 | C25 | Classicos do Vale | requests + BeautifulSoup | P | Baixo | C01-C06 | Loja/intermediadora (Diamantina-MG), foco em colecionadores e clubes. Volume provavelmente baixo — monitorar custo/beneficio. |

## Onda 3 - Dados premium (precos realizados)

| Ordem | ID | Fonte | Tecnica | Esforco | Risco | Dependencias | Criterio de pronto |
|---|---|---|---|---|---|---|---|
| 17 | C17 | Circuito de Leiloes | requests + BS4 / Playwright | M | Medio | C01-C16, INF-03 | Precos realizados incorporados como sinal separado de anuncios. |
| 18 | C18 | CARDE / Magalhaes Gouvea | requests + BeautifulSoup | M | Medio | C01-C16, INF-03 | Resultados de leilao extraidos com mapeamento de lote/modelo/ano. |
| 25 | C26 | Sodre Santoro | requests + BS4 / Playwright | M | Medio | C17, INF-03 | Categoria dedicada de carros antigos, leiloes online recorrentes. Filtro por ano + curadoria de categoria obrigatorios (leiloes de financeira misturam comuns/sinistrados). |
| 26 | C27 | Picelli Leiloes | requests (Supabase REST) | P | Baixo | C17 | ⚠️ Provavel sobreposicao com C17: o spike do Circuito de Leiloes revelou que os dados vem da plataforma Picelli (Supabase REST). Validar se picelli.com.br e o mesmo backend antes de criar conector separado — pode ser so ampliacao de escopo do C17. |
| 27 | C28 | Freitas Leiloeiro | requests + BS4 / Playwright | M | Medio | C17, INF-03 | Leiloes online recorrentes incluindo classicos. Mesmo cuidado de filtro/curadoria do C26. |
| 28 | C29 | Buaiz Leiloes | requests + BeautifulSoup | P | Medio | C17, INF-03 | Eventos pontuais de antigos (60+ lotes), lance inicial e atual publicos. Cadencia irregular — conector sob demanda por evento. |

Notas da pesquisa v2 para a Onda 3:

- Lotes "nao vendidos" tambem sao sinal de mercado (preco pedido rejeitado) — registrar com `status: nao_vendido` no schema de leilao, mesmo fora do calculo principal.
- O conector C17 ja implementa na pratica o schema de leilao (lote, status vendido/condicional, lance final); usar como referencia para C26-C29.

## Fora do MVP

| ID | Fonte | Status | Justificativa | Possivel reentrada |
|---|---|---|---|---|
| C19 | Facebook Marketplace | Bloqueado | Login obrigatorio e anti-bot agressivo | Somente com parceria, API oficial ou fornecedor terceirizado. |

## Acao paralela (nao-scraping)

| ID | Oportunidade | Contexto | Proximo passo |
|---|---|---|---|
| PAR-01 | TopClassic / FBVA (topclassic.com.br) | Filiado a FBVA, credenciado SENATRAN para emissao de CVCOL/Placa Preta; tem secao de classificados. | Vini sondar internamente na FBVA: parceria de dados oficial pode valer mais que crawler — e abre porta para credibilidade institucional ("dados reconhecidos pela federacao"). |

## Nota metodologica: preco pedido vs. preco realizado

Nem todas as fontes produzem o mesmo tipo de dado. A distinção é metodologicamente crítica:

- **Preço pedido** (anúncios, portais, lojas): o vendedor define o preço. Sujeito a ancoragem, outliers e veículos fora de padrão.
- **Preço realizado** (leilões com venda confirmada): o mercado define o preço. É o dado mais próximo do valor de referência real.

O sistema trata esses dois tipos como sinais distintos no pipeline de agregação. Fontes de preço realizado (C17, C18) recebem peso 1.5x na média ponderada; lojas especializadas (Tier 2) recebem 1.2x; classificados gerais (Tier 3) recebem 1.0x ou 0.8x conforme dispersão histórica. Ver tabela completa em [source-governance.md](source-governance.md).

Essa separação é a diferença entre um agregador de anúncios e uma referência de mercado — análoga ao modelo do Hagerty Price Guide nos EUA.

## Ordem sugerida de sprints (revisada)

1. Sprint 0: INF-01 a INF-06.
2. Sprint 1 (portal-first): C04, C05, C06.
3. Sprint 2 (em andamento): **C01 (ML API)** + **C17 (Circuito de Leiloes)** — API zero fricção + dado de preço realizado que diferencia o produto.
4. Sprint 3: **C20 (WebClassicos)** + **C21 (Classificados Classicos)** + C09 (Armazem do Vovo) — Tier 1 da pesquisa v2: nicho puro, baixo risco, mesma natureza do Maxicar. Critério: amostra média por modelo popular ≥ 10 anúncios. C02, C03, C10, C11 entram conforme capacidade.
5. Sprint 4: C22 (SoCarrao), C07, C08 e lojas especializadas C12-C16 + C23-C25, com governança `tipo_fonte: loja` implementada.
6. Sprint 5: C18, C26-C29 (avaliar sobreposição C27/C17 antes) + recalibração do score com pesos de tier.

Justificativa da mudança: C17 subiu do Sprint 5 para o Sprint 2 porque preço realizado de leilão é o ativo diferenciador do produto. Com +9.500 vendas no Circuito de Leilões, é possível construir curva histórica por modelo — algo que nenhum agregador de anúncios brasileiro tem.

Governanca de decisao por fonte (API vs HTML, criterios go/no-go e tabela de pesos) em [source-governance.md](source-governance.md).

## Criterios de aceite globais

1. Cada conector precisa de testes de parse em amostras reais salvas (snapshot tests).
2. Falha de um conector nao pode derrubar a consulta final (degradacao graciosa).
3. Toda resposta ao usuario deve exibir tamanho de amostra e data da coleta mais recente.
4. Conectores sem compliance aprovado permanecem desativados em producao.
5. Anuncios "preco sob consulta" ficam fora do calculo, mas contam na transparencia de amostra ("X anuncios encontrados, Y com preco"). (pesquisa v2)
6. Deduplicacao entre fontes por heuristica marca+modelo+ano+preco±5%+UF — mesmo carro em 2+ sites nao pode inflar a amostra. Detalhar na spec de catalogo (INF-02/INF-06). (pesquisa v2)
7. Spike de fetch (1 dia/fonte) antes de comprometer qualquer fonte nova em sprint — anti-bot e qualidade de HTML sao hipoteses, nao fatos. (pesquisa v2)
