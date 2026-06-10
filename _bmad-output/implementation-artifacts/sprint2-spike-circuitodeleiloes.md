---
title: "Sprint 2 - Spike C17 Circuito de Leiloes"
status: done
created: 2026-06-10
updated: 2026-06-10
---

# Spike C17 — Circuito de Leilões (preço realizado)

## Descoberta principal

**circuitodeleiloes.com.br é site institucional** (galeria de fotos 2018, sem catálogo
nem resultados). Os leilões reais rodam na plataforma do leiloeiro oficial:
**Picelli Leilões** — https://www.picellileiloes.com.br (plataforma "Ares").

## Arquitetura da fonte

- SPA React atrás de Cloudflare (anti-bot ativo no HTML).
- Dados servidos por **Supabase** em `api.picellileiloes.com.br` (REST PostgREST).
- A chave `sb_publishable_*` é pública por design (anon role + RLS) — a mesma
  entregue a qualquer visitante do site. **Não é necessário Playwright.**
- Rota de detalhe do lote no site: `/lote/{slug}`.

## Dados disponíveis (verificado 2026-06-10)

- Tabela/view `public_lots` legível com a chave anon.
- Categoria relevante: `categories.slug = "veiculos_antigos_e_especiais"`
  (id `de136bb4-6b19-456d-abce-64dc5173e91e`).
- Campos-chave: `title`, `status`, `highest_bid_value`, `bid_count`,
  `evaluation_value`, `slug`, `updated_at`.
- Distribuição de status na categoria (10/06/2026): 70 condicional, 46 vendido,
  16 aberto, 12 retirado, 7 encerrado.
- Título no padrão DETRAN: `"MARCA/MODELO - ANOFAB/ANOMOD"`
  (ex.: `"CHEVROLET/CHEVROLET SILVERADO LONG BED 4X4 - 1992/1993"`, `"IMP/MG - 1967/1967"`).

## Decisões metodológicas

1. **Preço realizado = `highest_bid_value` com `status = "vendido"`.**
   `condicional` (lance condicional pendente de homologação pelo comitente) fica
   **fora** do sinal — não é venda confirmada. Reavaliar na Story 5.3 (calibração).
2. Sinal de leilão **separado** dos anúncios (AC Story 5.1): não entra no pipeline
   de média de anúncios; resposta da API expõe bloco `sinal_leilao` próprio.
3. Matching por título normalizado contendo marca E modelo da consulta
   (mesma abordagem dos demais conectores).

## Compliance (INF-04)

- `robots.txt` da Picelli: `User-agent: * → Allow: /` com
  `Content-Signal: search=yes, ai-train=no`. Crawlers de treinamento de IA
  específicos (GPTBot, ClaudeBot etc.) bloqueados — nosso uso é agregação de
  preços (search-like), não treinamento de modelo. Uso aprovado com ressalvas:
  rate limit 1 req/s, User-Agent realista, volume baixo (1–2 requests por consulta).
- circuitodeleiloes.com.br sem robots.txt (servidor devolve a home com 200).

## Riscos

1. Chave anon pode rotacionar a qualquer deploy do site → conector deve degradar
   graciosamente (já é requisito global) e logar erro claro de autenticação.
2. RLS pode passar a ocultar `highest_bid_value` de lotes encerrados.
3. Volume baixo por modelo (cauda longa de clássicos) → exibir amostra sempre.

## Conclusão

Viável com `requests` puro contra a API REST. Esforço real menor que o estimado
no backlog (M → P). Sem necessidade de Playwright nem parsing de HTML.
