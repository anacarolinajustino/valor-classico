---
title: "Addendum - Fontes de Dados"
status: draft
created: 2026-05-29
updated: 2026-05-29
---

# Addendum: Inventario de Fontes para Coleta

## Objetivo

Registrar o inventario inicial de fontes de anuncios e referencias de preco para o Valor Classico, conforme lista fornecida pela usuaria.

## Fontes Mapeadas

| # | Fonte | URL | Tipo | Viabilidade | Tecnica sugerida | Volume estimado | Observacoes |
|---|---|---|---|---|---|---|---|
| 1 | Mercado Livre | https://www.mercadolivre.com.br | Classificado Geral | Viavel | API oficial REST | ~2.800 anuncios | Maior volume. API gratuita e estavel. Melhor custo-beneficio. |
| 2 | OLX Brasil | https://www.olx.com.br | Classificado Geral | Viavel | requests + BeautifulSoup | Alto | Alto volume. HTML acessivel, layout muda com frequencia. |
| 3 | Webmotors | https://www.webmotors.com.br | Classificado Geral | Parcial | Selenium / Playwright | Alto | Renderizado em JavaScript. Requer navegador headless. |
| 4 | iCarros | https://www.icarros.com.br | Classificado Geral | Parcial | requests + BS4 / Playwright | Alto | Parcialmente JS. Boa cobertura nacional. |
| 5 | Netmotors | https://www.netmotors.com.br | Classificado Geral | Viavel | requests + BeautifulSoup | Medio | Categoria "Colecionador". Volume menor e publico qualificado. |
| 6 | Facebook Marketplace | https://www.facebook.com/marketplace | Rede Social | Bloqueado | Inviavel (login + anti-bot) | Muito Alto | Login obrigatorio e bloqueio agressivo. Alternativa paga: Apify. |
| 7 | Maxicar | https://www.maxicar.com.br | Portal Especializado | Viavel | requests + BeautifulSoup | Medio/Alto | Maior portal de antigomobilismo do BR. |
| 8 | Super Antigo | https://www.superantigo.com.br | Portal Especializado | Viavel | requests + BeautifulSoup | Medio | Exclusivo para veiculos ate 1999. |
| 9 | Clube da Caminhonete | https://www.clubedacaminhonete.com.br | Portal Especializado | Viavel | requests + BeautifulSoup | Medio | Carros antigos, caminhonetes e motos com +25 anos. |
| 10 | Armazem do Vovo | https://www.armazemdovovo.com.br | Portal Especializado | Viavel | requests + BeautifulSoup | Medio | Classificados de veiculos antigos raros e premium. |
| 11 | Retroauto | https://www.retroauto.com.br | Portal Especializado | Viavel | requests + BeautifulSoup | Pequeno/Medio | Portal de antigomobilismo com anuncios e eventos. |
| 12 | Atelie do Carro | https://www.ateliedocarro.com.br | Loja Especializada | Viavel | requests + BeautifulSoup | Pequeno | Plataforma especializada com boa visibilidade nacional. |
| 13 | L'ART Veiculos Antigos | https://www.lartbr.com.br | Loja Especializada | Viavel | requests + BeautifulSoup | Pequeno (~30-60) | Loja premium em SP (Moema). |
| 14 | Brunelli Veiculos Antigos | https://www.brunelliveiculosantigos.com.br | Loja Especializada | Viavel | requests + BeautifulSoup | Pequeno (~40-80) | Tradicao familiar. Parceira do CARDE/Magalhaes Gouvea. |
| 15 | Classic Car BR | https://www.classiccarbr.com.br | Loja Especializada | Viavel | requests + BeautifulSoup | Pequeno (~20-50) | Compra, venda e consignacao. |
| 16 | JS Autos Antigos | https://www.jsautosantigos.com.br | Loja Especializada | Viavel | requests + BeautifulSoup | Pequeno (~30-60) | 15+ anos em SP. Consignacao, compra e locacao. |
| 17 | Franz Veiculos Antigos | https://www.franzveiculosantigos.com.br | Loja Especializada | Viavel | requests + BeautifulSoup | Pequeno (~20-40) | Porto Alegre com atuacao nacional. |
| 18 | Circuito de Leiloes | https://www.circuitodeleiloes.com.br | Leilao | Parcial | requests + BS4 / Playwright | Variavel | +9.500 vendidos. Precos realizados sao valiosos. |
| 19 | CARDE / Magalhaes Gouvea | https://www.artmg.com.br | Leilao | Parcial | requests + BeautifulSoup | Variavel | Leiloes de prestigio com catalogos e resultados. |

## Priorizacao Recomendada

### Onda 1 (MVP imediato)

1. Mercado Livre
2. OLX Brasil
3. Netmotors
4. Maxicar
5. Super Antigo
6. Atelie do Carro

### Onda 2 (MVP expandido)

1. iCarros
2. Webmotors
3. Armazem do Vovo
4. Retroauto
5. Clube da Caminhonete
6. Lojas especializadas restantes

### Onda 3 (dados premium)

1. Circuito de Leiloes
2. CARDE / Magalhaes Gouvea

## Notas de Risco

1. Cada fonte deve passar por checagem juridica (ToS, robots, limites, uso comercial).
2. Fontes com JS pesado devem usar browser automation com controle de custo.
3. Facebook Marketplace fica fora do MVP sem integracao oficial/parceria.

## Contexto de Negocio (Canvas e Lean Canvas)

### Problema refinado

1. Falta de uma tabela de referencia de valores medios para veiculos colecionaveis.
2. Veiculos antigos, especialmente os produzidos antes de 1985, costumam ser precificados por comparacao informal entre anuncios semelhantes.
3. O mercado opera com muita assimetria de informacao e pouca padronizacao.

### Proposta de valor ampliada

1. Ser referencia nacional de informacao para o segmento de veiculos antigos.
2. Criar um ativo de dados que sirva tanto ao consumidor final quanto a empresas do ecossistema.
3. Viabilizar no futuro produtos derivados como seguros, consorcios, financiamentos e servicos de avaliacao.

### Segmentos de clientes citados

1. Colecionadores de veiculos antigos de colecao.
2. Pessoas que usam automovel antigo como investimento.
3. Seguradoras.
4. Consorcios.
5. Financeiras.
6. Comerciantes de veiculos antigos.
7. Oficinas e profissionais de restauracao.

### Canais citados

1. Website.
2. Aplicativo para dispositivos moveis.
3. Redes sociais.
4. Divulgacao de eventos.

### Parcerias-chave citadas

1. Federacao Brasileira de Veiculos Antigos (FBVA).
2. Clubes de colecionadores.
3. Vendedores de veiculos antigos.
4. Vendedores de pecas para automoveis antigos.
5. Mecanicos e restauradores especializados.

### Fontes de receita sugeridas

1. Assinaturas.
2. Anuncios premium.
3. Avaliacao profissional.
4. Parcerias comerciais.
5. Publicidade.
6. Lojas oficiais / souvenirs.

## Base Canonica de Veiculos (CSV Webmotors)

Arquivo recebido: `/Users/ana.justino/Downloads/base_dados_webmotors.csv`

Estrutura identificada:

1. `nome_marca`
2. `nome_modelo`
3. `ano_modelo`
4. `nome_versao`
5. `data_coleta`

Leitura inicial do dataset:

1. Aproximadamente 26.200 linhas de dados + cabecalho.
2. 157 marcas.
3. 1.128 pares marca-modelo.
4. 7.303 combinacoes marca-modelo-ano.
5. Bom espalhamento em veiculos antigos e de nicho, com exemplos como Willys Jeep, Fusca, Kombi, Bandeirante e Porsche 911.

Uso recomendado no produto:

1. Catalogo canonico para autocomplete e sugestao de busca.
2. Normalizacao de consultas digitadas livremente pelo usuario.
3. Matching entre anuncios coletados e entidades padronizadas de veiculo.
4. Base para reduzir ambiguidade entre nomes de modelo e versao.

Limite importante:

1. Este CSV nao substitui fonte de preco; ele funciona como base de referencia de entidades (marca/modelo/ano/versao).
