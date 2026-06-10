---
title: "Especificacao - Catalogo e Matching de Veiculos"
status: draft
created: 2026-05-29
updated: 2026-05-29
---

# Especificacao de Catalogo e Matching

## Objetivo

Definir como o Valor Classico usara o CSV base de veiculos para busca assistida, desambiguacao de entidades e normalizacao dos anuncios coletados.

## Origem de dados

Arquivo de entrada: `/Users/ana.justino/Downloads/base_dados_webmotors.csv`

Colunas de origem:

1. `nome_marca`
2. `nome_modelo`
3. `ano_modelo`
4. `nome_versao`
5. `data_coleta`

## Papel do catalogo no produto

O catalogo nao e fonte de preco. Ele e a base canonica de entidades de veiculo para:

1. sugerir marcas, modelos, anos e versoes na busca;
2. reduzir ambiguidade na digitacao do usuario;
3. padronizar anuncios coletados de fontes externas;
4. melhorar matching entre nomes divergentes do mesmo veiculo.

## Modelo canonico recomendado

### Entidade `vehicle_make`

1. `make_id`
2. `make_name_canonical`
3. `make_name_normalized`
4. `is_active`

### Entidade `vehicle_model`

1. `model_id`
2. `make_id`
3. `model_name_canonical`
4. `model_name_normalized`
5. `model_search_tokens`
6. `is_active`

### Entidade `vehicle_model_year`

1. `model_year_id`
2. `model_id`
3. `year_model`
4. `catalog_source`
5. `source_last_seen_at`

### Entidade `vehicle_version`

1. `version_id`
2. `model_year_id`
3. `version_name_canonical`
4. `version_name_normalized`
5. `fuel_type_normalized`
6. `transmission_normalized`
7. `body_hint`

## Regras de normalizacao

### Texto

1. Remover acentos para indexacao e matching tecnico.
2. Preservar texto original/canonico para exibicao na interface.
3. Normalizar caixa para uppercase ou lowercase no indice tecnico.
4. Colapsar espacos duplicados e remover pontuacao irrelevante.

### Tokens de busca

Gerar tokens pesquisaveis por:

1. marca;
2. modelo;
3. marca + modelo;
4. modelo + ano;
5. versao resumida, quando aplicavel.

Exemplo:

1. `VOLKSWAGEN`
2. `KOMBI`
3. `VOLKSWAGEN KOMBI`
4. `KOMBI 1995`

## Fluxo de busca do usuario

### Modo MVP recomendado

1. Campo principal aceita texto livre.
2. Sistema sugere marca/modelo conforme digitacao.
3. Ano continua como campo separado e obrigatorio no MVP.
4. Versao aparece como refinamento opcional quando houver ambiguidade alta.

### Regras de UX

1. Se houver um unico match forte, preencher a entidade canonica internamente.
2. Se houver multiplos matches fortes, exibir lista curta de sugestoes.
3. Se o usuario informar apenas modelo generico, solicitar confirmacao de marca quando necessario.
4. Quando nao houver match exato, aplicar busca aproximada e exibir "voce quis dizer".

## Fluxo de matching de anuncios

### Entrada

Cada conector fornece ao menos:

1. marca extraida ou inferida;
2. modelo extraido;
3. ano do anuncio/modelo;
4. versao textual, quando existir.

### Pipeline de matching

1. Normalizar texto do anuncio.
2. Buscar match exato por marca + modelo + ano.
3. Se falhar, buscar match por marca + modelo.
4. Se ainda falhar, aplicar similaridade textual controlada sobre modelo.
5. Se houver mais de um candidato plausivel, marcar como `needs_review` ou `low_confidence_match`.

### Resultado esperado

Cada anuncio processado deve sair com:

1. `canonical_make_id`
2. `canonical_model_id`
3. `canonical_model_year_id`
4. `canonical_version_id` quando houver seguranca suficiente
5. `match_confidence`
6. `match_strategy` (exact, normalized_exact, fuzzy, manual_review)

## Politica de confianca do matching

### High confidence

1. Marca exata.
2. Modelo exato apos normalizacao.
3. Ano exato.

### Medium confidence

1. Marca exata.
2. Modelo aproximado ou abreviado.
3. Ano exato ou ausente.

### Low confidence

1. Marca ausente ou inferida.
2. Modelo ambiguo entre multiplas entidades.
3. Versao conflitante.

Regra MVP: anuncios com `low_confidence_match` nao entram automaticamente no calculo principal sem regra adicional de saneamento.

## Regras para versao

1. Versao nao deve ser obrigatoria para o MVP de busca inicial.
2. Versao melhora matching, mas nao deve bloquear consulta quando ausente.
3. Quando a mesma combinacao marca/modelo/ano tiver muitas versoes, a interface pode pedir refinamento opcional.

## Casos especiais a cobrir

1. Modelos com muitas decadas de continuidade (ex.: Kombi, Fusca, Jeep).
2. Grafias alternativas ou abreviadas.
3. Modelos iguais em marcas diferentes.
4. Veiculos raros e series pequenas.
5. Anuncios com marca faltando mas versao/modelo altamente sugestivos.

## Decisoes de implementacao para Sprint 0

### Entregas minimas

1. Importador do CSV para entidades canonicas.
2. Endpoint/servico de sugestao por marca/modelo.
3. Funcao de normalizacao textual compartilhada.
4. Funcao de matching basico para conectores da Sprint 1.

### Fora do escopo inicial

1. Correcoes manuais em painel de curadoria.
2. Ontologia completa de combustivel/carroceria.
3. Sinônimos enriquecidos por IA ou modelos vetoriais.

## Criterios de pronto

1. Usuario consegue buscar com sugestoes canonicas para marcas/modelos comuns.
2. Conectores da Sprint 1 usam o catalogo para matching basico.
3. Matching registra estrategia usada e nivel de confianca.
4. Casos sem match confiavel nao contaminam a media principal.

## Perguntas em aberto

1. O campo de busca inicial sera apenas por modelo ou por marca + modelo no mesmo campo?
2. A versao sera exibida no MVP apenas como refinamento ou tambem na resposta final?
3. Havera recorte inicial por periodo (ex.: antes de 1985) no autocomplete ou isso sera apenas filtro analitico?