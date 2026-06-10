---
title: "Sprint 1 - Portal First"
status: done
created: 2026-05-29
updated: 2026-06-10
---

# Sprint 1 - Portal First (C04, C05, C06)

## Objetivo

Colocar em funcionamento os conectores iniciais de portais/loja especializada para gerar primeira estimativa util de preco no fluxo MVP.

## Escopo fechado

1. C04 Maxicar — ✅ concluido (2026-05-30)
2. C05 Super Antigo — ✅ concluido (2026-05-30)
3. C06 Atelie do Carro — ✅ concluido (2026-06-10)

## Progresso

### ✅ C04 Maxicar — concluido

- Conector implementado em `src/connectors/maxicar.py`.
- Pipeline completo: coleta, normalização, dedup, filtro IQR, estatísticas por ano.
- Testes de snapshot: `tests/test_maxicar_parser.py` com fixture `tests/fixtures/maxicar_sample.html`.
- Portal web MVP operacional: `app.py` + `index.html` + `static/`.
- API com 5 endpoints: `/`, `/api/marcas`, `/api/modelos`, `/api/anos`, `/api/buscar`.
- Busca encadeada Marca → Modelo → Ano funcional no front-end.

### ✅ C05 Super Antigo — concluido

- Spike: site é SPA Vite+React (CSR). `requests + BeautifulSoup` retorna shell vazio (~7.5KB). Playwright obrigatório.
- Conector implementado em `src/connectors/superantigo.py` com Playwright headless.
- Extração: título (`h3` em `div.p-4`), preço (regex `R$` no texto do card), marca/modelo/ano (URL slug).
- Paginação via click em `a[aria-label='Ir para a próxima página']` (href="#", JS-only).
- Fixture de snapshot salva em `tests/fixtures/superantigo_sample.html` (capturada via Playwright).
- Testes: `tests/test_superantigo_parser.py` — 14 testes (7 com HTML mínimo + 7 com snapshot real), todos passando.
- Degradação graciosa implementada no `app.py`: falha do Super Antigo não derruba resposta.
- `fontes_ativas` e `fontes_com_falha` dinâmicos na resposta da API.

### ✅ C06 Atelie do Carro — concluido

- Conector implementado em `src/connectors/ateliedocarro.py` com métricas de latência/volume.
- Testes de snapshot: `tests/test_ateliedocarro_parser.py`, todos passando.
- Integrado ao agregador em `app.py` junto com Maxicar e Super Antigo.
- Investigações documentadas em `investigations/` (busca vazia e caso Kombi).

## Sequencia de execucao

- [x] 1. Preparar adapters baseados no contrato canonico (INF-01) e pipeline comum (INF-02).
- [x] 2. Implementar parser Maxicar + testes de snapshot.
- [x] 3. Implementar parser Super Antigo + testes de snapshot.
- [x] 4. Implementar parser Atelie do Carro + testes de snapshot.
- [x] 5. Integrar os 3 conectores no agregador de consulta.
- [x] 6. Publicar metricas operacionais (sucesso/falha/latencia/volume).

## Definition of Done da sprint

1. Cada conector executa em 3 ciclos consecutivos sem quebra critica.
2. Consulta por modelo+ano retorna media, mediana, faixa e amostra com pelo menos uma das 3 fontes.
3. Falha isolada de um conector nao derruba resposta final.
4. Fontes ativas exibidas no detalhe de transparencia da consulta.

## Riscos da sprint

1. Mudanca de HTML em portal durante desenvolvimento.
2. Cobertura limitada por volume de anuncios em alguns modelos.

## Mitigacao

1. Snapshot tests com fixture por fonte e alerta de regressao.
2. Fallback de resposta com mensagem de baixa amostra quando necessario.
