---
title: "Product Brief - Valor Classico"
status: draft
created: 2026-05-29
updated: 2026-05-29
---

# Product Brief: Valor Classico

## Executive Summary

Valor Classico e uma plataforma web que estima o valor medio de carros antigos e populares fora do recorte tradicional da Tabela FIPE, usando anuncios reais publicados em marketplaces e classificados online. O usuario informa modelo e ano (ex.: Palio 2008) e recebe uma media de preco baseada em amostras recentes, junto com faixas de valor e qualidade da amostra.

A proposta resolve um problema pratico: para carros antigos, versoes especificas, carros modificados ou com baixa liquidez, a FIPE frequentemente nao representa o preco real negociado no mercado. Ao agregar dados de diferentes fontes e aplicar filtros de qualidade, o Valor Classico entrega uma referencia mais aderente ao "preco de rua".

O material complementar de Canvas e Lean Canvas reforca um recorte importante: o mercado inicial mais aderente nao e apenas o de carros usados em geral, mas o de veiculos antigos e colecionaveis, especialmente nos segmentos com pouca referencia publica e baixa padronizacao de valor. Isso posiciona o produto como infraestrutura de informacao para um ecossistema maior, incluindo colecionadores, lojistas, seguradoras, financeiras e oficinas especializadas.

O projeto comeca com foco no Brasil, priorizando fontes acessiveis e relevantes para o segmento de usados antigos. A primeira versao privilegia confiabilidade da estimativa, transparencia dos dados e simplicidade da experiencia.

O portifolio inicial de fontes foi mapeado pela usuaria com 19 origens (marketplaces, portais especializados, lojas e leiloes), com classificacao de viabilidade tecnica por fonte. A execucao sera por ondas para reduzir risco legal/operacional e acelerar tempo ate o primeiro valor util.

## The Problem

Quem compra, vende ou avalia carros antigos hoje enfrenta tres dores centrais:

1. Falta de referencia realista de preco para modelos antigos e anos especificos.
2. Grande variacao de precos em anuncios com pouca transparencia sobre estado do veiculo, versao e localizacao.
3. Tempo alto para pesquisar manualmente em varios sites e consolidar uma media confiavel.

Nos materiais enviados, aparece uma dor ainda mais especifica: veiculos colecionaveis, em especial os produzidos antes de 1985, costumam ser avaliados de forma artesanal, por comparacao informal entre anuncios semelhantes, sem base historica centralizada.

A consequencia e decisao de compra/venda com alta incerteza, risco de sobrepreco/subpreco e negociacoes mais demoradas.

## The Solution

Valor Classico oferece um buscador de valor medio por modelo e ano baseado em anuncios reais.

Fluxo principal:

1. Usuario digita modelo e ano (ex.: "Palio", 2008), com apoio de um catalogo base de marcas, modelos, anos e versoes para reduzir ambiguidades.
2. Sistema coleta anuncios em fontes suportadas (inicialmente, comecando por sites definidos no MVP, incluindo a referencia mencionada pelo usuario: ateliedocarro.com.br).
3. Motor de normalizacao limpa os dados (moeda, quilometragem quando houver, versao textual, duplicidades, outliers extremos).
4. Algoritmo calcula media, mediana e faixa sugerida.
5. Site retorna painel simples com:
   - Preco medio estimado
   - Faixa tipica (min/max filtrado)
   - Quantidade de anuncios usados na conta
   - Data da ultima atualizacao

## What Makes This Different

1. Foco explicito em carros antigos e nichos onde a FIPE tem baixa precisao percebida.
2. Estimativa baseada em anuncios reais multi-fonte, nao apenas tabela de referencia unica.
3. Uso de um catalogo canonicamente estruturado de marca, modelo, ano e versao para melhorar busca, correspondencia e limpeza de dados.
4. Transparencia sobre qualidade da amostra (quantidade de anuncios, recencia e dispersao).
5. Possibilidade de evoluir para indice historico por modelo/ano (valor ao longo do tempo).
5. Potencial de se tornar camada de referencia para servicos adjacentes como seguro, consorcio, financiamento, avaliacao profissional e marketplace premium.

## Who This Serves

Publico primario:

1. Proprietarios e compradores de carros antigos/populares usados.
2. Lojistas e revendedores de usados de giro lento.
3. Entusiastas e colecionadores que precisam de referencia de mercado.
4. Pessoas que tratam automovel antigo como ativo de investimento.

Publico secundario:

1. Pequenos avaliadores e consultores de compra.
2. Criadores de conteudo automotivo que comentam precificacao.
3. Seguradoras, consorcios e financeiras que precisam de referencia de valor.
4. Comerciantes de pecas, oficinas e restauradores especializados.

## Success Criteria

Metas da fase inicial (MVP):

1. Tempo medio de resposta da busca <= 8 segundos (com cache para consultas repetidas).
2. Pelo menos 70% das consultas com amostra minima util (>= 10 anuncios validos) nos modelos priorizados.
3. Taxa de satisfacao qualitativa >= 80% em testes com usuarios ("estimativa parece realista").
4. Taxa de retorno em 30 dias >= 25% dos usuarios que fizeram ao menos 1 consulta.

## Scope

In-scope (MVP):

1. Website responsivo com busca por modelo + ano.
2. Coleta e consolidacao de anuncios de fontes priorizadas e tecnicamente viaveis.
3. Calculo de media, mediana e faixa filtrada.
4. Exibicao de metrica de confianca da amostra (qtd. anuncios e recencia).
5. Painel administrativo simples para monitorar fontes e falhas de coleta.
6. Estrategia de ingestao por fases com prioridade para fontes marcadas como "Viavel".
7. Catalogo base de veiculos para busca assistida, sugestao e normalizacao de consultas.

Out-of-scope (MVP):

1. Avaliacao individual por placa/chassi.
2. Precificacao com inspeção fisica do estado do carro.
3. Aplicativo mobile nativo.
4. Automacao de compra/venda dentro da plataforma.

## Business Positioning

Papel inicial do produto:

1. Tabela de referencia viva para veiculos antigos e colecionaveis.
2. Camada de inteligencia de mercado para um nicho com pouca padronizacao de dados.

Possiveis canais validados pelo material enviado:

1. Website como canal principal do MVP.
2. Aplicativo mobile como expansao futura.
3. Aproximacao com clubes, federacoes e comunidades de antigomobilismo.
4. Divulgacao de eventos e presenca em redes sociais como alavanca de aquisicao.

Possiveis parcerias-chave:

1. FBVA e clubes de colecionadores.
2. Vendedores e lojas de veiculos antigos.
3. Comerciantes de pecas e oficinas de restauracao.
4. Rede de profissionais especializados em avaliacao e restauracao.

Monetizacao de medio prazo observada nos canvases:

1. Assinaturas.
2. Anuncios premium.
3. Avaliacao profissional.
4. Parcerias comerciais.
5. Publicidade e lojas oficiais.

## Competitive Landscape

**Analise realizada em:** 2026-05-30
**Tipo:** Mapeamento de mercado + avaliacao de ameacas

### Situacao atual: mercado vazio

Nao existe nenhum concorrente direto com essa proposta no Brasil. Nenhuma plataforma nacional agrega anuncios de multiplas fontes e calcula media de preco de mercado para carros antigos. O vacuo e real e confirmado.

O que existe sao substitutos parciais e inadequados:

| Solucao atual do mercado | Limitacao critica |
|---|---|
| Tabela FIPE | Nao e adequada para classicos ou colecionaveis. Valor medio reflete o que circula regularmente — nao contempla raridade, originalidade ou apelo emocional. Precos de mercado chegam a 20x mais que a FIPE para modelos iconicos. |
| Maxicar / Atelie / Super Antigo | Portais de anuncio — nao calculam media nem geram referencia de preco. |
| Forums e clubes | Conhecimento informal, nao estruturado, sem transparencia de amostra. |
| Avaliacao por laudo | Cara, lenta, nao escalavel — usada principalmente por seguradoras. |
| Busca editorial ("quanto vale meu fusca") | Retorna artigos com valores pontuais defasados, sem metodologia. |

### Benchmark internacional: Hagerty (EUA/UK)

Unico benchmark relevante globalmente. Cobre mais de 40.000 veiculos com dados de leiloes publicos, vendas privadas, dealers e precos pedidos. Atualiza o Price Guide trimestralmente com classificacao por 4 condicoes (ruim, regular, bom, concours). Modelo de negocio: avaliacao gratuita como isca → seguro especializado como receita principal.

Gap critico: Hagerty nao cobre o mercado brasileiro. Modelos nacionais (Fusca, Opala, Kombi, Puma, Karmann Ghia) simplesmente nao existem no banco de dados deles.

### Score de ameaca competitiva

| Dimensao | Score | Observacao |
|---|---|---|
| Concorrente direto nacional | 1/10 | Mercado vazio — janela aberta |
| Risco de entrada da FIPE | 3/10 | Instituicao lenta, sem DNA de produto digital |
| Risco de entrada de Maxicar/Atelie | 4/10 | Tem dados, mas nao tem visao de plataforma de referencia |
| Risco de grandes portais (OLX, Webmotors) | 5/10 | Poderiam construir, mas classicos sao nicho desprezado para eles |
| Risco Hagerty entrando no Brasil | 2/10 | Sem planos conhecidos + curva de aprendizado do mercado BR e alta |

Score geral de ameaca: **2/10 — campo livre agora.**

### Movimentos prioritarios para ocupar o territorio

1. **Reconhecimento de marca como "a referencia":** o nome Valor Classico precisa aparecer toda vez que alguem googlar preco de Opala, Fusca ou Kombi. SEO + conteudo editorial sao as armas principais.
2. **Formalizar a metodologia publicamente:** transparencia de amostra (quantos anuncios, de quais fontes, em que periodo) e o que diferencia uma "tabela" de uma simples media — e cria barreira de credibilidade dificil de copiar rapido.
3. **Dominar o catalogo core primeiro:** Fusca, Opala, Kombi, Chevette, Karmann Ghia, Puma. Esses 6 modelos concentram ~70% das buscas do publico. Cobertura profunda neles vale mais do que cobertura rasa em 100 modelos.

O risco real nao e ser copiado agora; e demorar demais e deixar a janela fechar quando algum portal grande resolver que classicos valem atencao.

## Data Source Strategy (MVP)

Resumo do inventario recebido:

1. Marketplaces/classificados gerais: Mercado Livre, OLX, Webmotors, iCarros, Netmotors, Facebook Marketplace.
2. Portais especializados em antigos: Maxicar, Super Antigo, Clube da Caminhonete, Armazem do Vovo, Retroauto.
3. Lojas especializadas para referencia: Atelie do Carro, L'ART, Brunelli, Classic Car BR, JS Autos Antigos, Franz Veiculos Antigos.
4. Leiloes para preco realizado: Circuito de Leiloes, CARDE/Magalhaes Gouvea.

Plano de rollout de conectores:

1. Fase 1 (go-live): Mercado Livre (API oficial), OLX, Netmotors, Maxicar, Super Antigo, Atelie do Carro.
2. Fase 2 (expansao): iCarros, Webmotors, lojas especializadas restantes, Retroauto, Armazem do Vovo, Clube da Caminhonete.
3. Fase 3 (inteligencia de mercado): conectores de leiloes para incorporar preco realizado.

Restricao declarada:

1. Facebook Marketplace permanece fora do MVP por bloqueio tecnico (login obrigatorio e anti-bot agressivo), salvo parceria/API de terceiro.

Inventario detalhado de fontes (tecnica sugerida, volume estimado e observacoes) em [addendum.md](addendum.md).
Backlog tecnico com ordem de implementacao, risco e esforco em [connectors-backlog.md](connectors-backlog.md).
Plano de epicos e historias para execucao em [_bmad-output/planning-artifacts/epics.md](../../epics.md).

## Assumptions and Risks

[ASSUMPTION] O produto usara apenas metodos de coleta permitidos por termos de uso, robots.txt e/ou APIs oficiais, com estrategia juridica para cada fonte.

Riscos principais:

1. Bloqueios tecnicos e juridicos de scraping em marketplaces (OLX, Facebook etc.).
2. Ruido alto nos dados de anuncios (valores irreais para chamar atencao, duplicidade, anuncios desatualizados).
3. Variacao regional de preco pode distorcer media nacional sem segmentacao geografica.
4. Dependencia de poucas fontes no inicio reduz cobertura.

Mitigacoes iniciais:

1. Priorizar fontes com acesso viavel e politica clara; manter conectores modulares.
2. Usar mediana e filtros robustos de outlier alem da media.
3. Exibir intervalo de confianca e tamanho da amostra para transparencia.
4. Introduzir segmentacao por estado/cidade em fase posterior.

## Vision

Se o Valor Classico acertar o problema de referencia de preco para usados antigos, ele pode evoluir de "calculadora de media" para "indice vivo de valorizacao/desvalorizacao" por modelo, ano e regiao. Em 2-3 anos, a plataforma pode se tornar referencia nacional para consulta de valor de carros classicos e de baixa liquidez, apoiando consumidores, lojistas e criadores de conteudo com dados mais proximos do mercado real.

Na visao de negocio sugerida pelos canvases, esse caminho tambem abre espaco para uma plataforma com comunidade, divulgacao de eventos, servicos B2B e produtos premium para o ecossistema de veiculos antigos.

## Immediate Next Decisions

1. Validar juridico/compliance por fonte da Fase 1 (termos de uso, robots e limites de acesso).
2. Definir criterio de "carro antigo" para priorizacao de modelos e ponderacao de fontes.
3. Escolher estrategia de atualizacao (near-real-time vs. lotes diarios) por categoria de fonte.
4. Definir metrica oficial de confianca exibida ao usuario (amostra, dispersao e recencia).
5. Definir como o catalogo base sera usado na UX: autocomplete, sugestao de versao e desambiguacao de nomes.
