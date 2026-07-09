# Investigation: Reginaldo de Campinas — Data Not Captured by Collector

## Resolution (2026-07-09)

**Fixed.** `src/connectors/reginaldodecampinas.py` now routes its `requests.Session` through
the DataImpulse residential proxy (`src.connectors._browser.requests_proxies()`) when the
`DATAIMPULSE_*` env vars are set — same credentials/mechanism already used for the
`mercadolivre` connector, but without Playwright/stealth (this block is plain IP reputation, not
automation fingerprinting, so a routed `requests.Session` is enough).

Verified live: `coletar_completo()` via proxy → 16 anúncios, 0 erros, same result as the
no-proxy local baseline. Removed `reginaldodecampinas` from `FONTES_INATIVAS` in `app.py`.
Depends on the `DATAIMPULSE_*` env vars being configured wherever the app runs in production
(confirmed set on Render as of 2026-07-09).

## Hand-off Brief

1. **What happened.** O domínio `reginaldodecampinas.com.br` bloqueia **todas** as requisições HTTP vindas do IP do Render (Frankfurt/datacenter), incluindo a WP REST API — a coleta termina em 0,2 s com 0 anúncios porque a primeira chamada à API falha instantaneamente.
2. **Where the case stands.** Causa raiz confirmada: bloqueio por IP de datacenter no nível do CDN/Hostinger, afetando todos os endpoints do domínio. O mesmo padrão já está documentado para registro9, lopesantigos, lexicar e autoclassic.
3. **What's needed next.** Marcar a fonte como inativa em `FONTES_INATIVAS` (solução imediata) ou implementar um proxy residencial brasileiro / scraper via GitHub Actions (solução definitiva).

## Case Info

| Field            | Value                                                                 |
| ---------------- | --------------------------------------------------------------------- |
| Ticket           | N/A                                                                   |
| Date opened      | 2026-06-25                                                            |
| Status           | Active                                                                |
| System           | Python/Flask on Render (Frankfurt); PostgreSQL; `src/connectors/reginaldodecampinas.py` |
| Evidence sources | Source code, local test run, git log, `app.py`, `persistence.py`     |

## Problem Statement

User-reported: "por algum motivo os dados do site Reginaldo de Campinas não estão sendo captados pelo coletor, ainda que aparentemente consiga acessar as informações."

Translation: the collector does not store anúncios even though it appears to access the site's information.

## Evidence Inventory

| Source | Status | Notes |
| ------ | ------- | ----- |
| `src/connectors/reginaldodecampinas.py` | Available | Commit `c8451b0` — uses WP REST API since 2026-06-25 |
| `app.py:215-317` | Available | `/api/buscar` reads DB only; no live connector calls |
| `app.py:408-447` | Available | `admin_coletar` calls `coletar_completo()` then `upsert_anuncios()` |
| `src/pipeline/persistence.py:277-313` | Available | `buscar_anuncios()` filters `ano <= 2000` |
| Local test of `coletar_completo()` | Available | Returns 19 anúncios; 9 pass `ano <= 2000` |
| WP REST API response locally | Available | `GET /wp-json/wp/v2/product?product_cat=61` → 200, 36 products |
| Render execution log after deploy | **Missing** | Would confirm which hypothesis is correct |
| Render network access to `reginaldodecampinas.com.br` | **Missing** | Whether WP API / detail pages are blocked from Frankfurt IP |

## Investigation Backlog

| # | Path to Explore | Priority | Status | Notes |
| - | --------------- | -------- | ------ | ----- |
| 1 | Trigger collection on Render after deploy; observe admin log time + error counts | High | Open | Single observation collapses all 4 hypotheses |
| 2 | Check `erros_detalhe` count in Render log | High | Open | > 0 confirms H3 (detail pages blocked) |
| 3 | Check if WP REST API endpoint is accessible from datacenter IPs | Medium | Open | Can proxy-test or add explicit logging |
| 4 | Verify brand-matching for captured anúncios in DB vs user search terms | Low | Open | Some brands (LANCER, VESPA) may not match catalog |

## Timeline of Events

| Time | Event | Source | Confidence |
| ---- | ----- | ------ | ---------- |
| Pre-fix (≤ 2026-06-25 16:36) | Collection runs in 2.2 s, returns 0 anúncios | Admin log (user-reported) | Confirmed |
| 2026-06-25 ~16:36 | Admin log: `reginaldodecampinas — 0 anúncios · 0 novos · 0 atualizados · 2.2s` | User message | Confirmed |
| 2026-06-25 ~16:45 | Fix deployed: commit `c8451b0` switches listing scraping → WP REST API | git log | Confirmed |
| 2026-06-25 (today) | Local test: `coletar_completo()` → 19 anúncios via WP API | Direct observation | Confirmed |
| 2026-06-25 (today) | User reports search still returns 0 results | User message | Confirmed |
| 2026-06-25 (today) | Render deploy status unknown; collection on Render not confirmed triggered | — | Missing |

## Confirmed Findings

### Finding 1: Pre-fix execution time = 2.2 s identifies where failure occurred

**Evidence:** Admin log, user message 2026-06-25 16:36.

**Detail:** `_requisitar` with `TIMEOUT=20` and `BACKOFF=2.0` with 2 retries takes ~2.2 s when *both* requests fail quickly (fast rejection + 2.0 s sleep). This rules out a timeout failure (which would take 40+ s) and confirms the listing page (`/categoria-produto/veiculos-venda/`) returned a non-HTML or bot-challenge response, not a slow response.

### Finding 2: `/api/buscar` reads from DB only

**Evidence:** `app.py:240` — `todos = buscar_anuncios(marca, modelo, ano_filtro)`, no connector calls below it.

**Detail:** For anúncios to appear in a homepage search, `coletar_completo()` must have been run and its results stored via `upsert_anuncios()`. Searching without prior collection always returns 0 for any source.

### Finding 3: `coletar_completo()` returns 19 anúncios locally (post-fix)

**Evidence:** Direct test run, 2026-06-25.

**Detail:** 36 candidatos returned by WP REST API; 17 filtered (no price or filtered by title cleaner); 19 valid anúncios produced. Of those 19, only 9 have `ano <= 2000` and would be returned by `buscar_anuncios()`.

### Finding 4: `buscar_anuncios()` has a hard `ano <= 2000` cutoff

**Evidence:** `src/pipeline/persistence.py:301` — `AND (ano IS NULL OR ano <= %s)` with `ANO_CORTE_CLASSICO = 2000`.

**Detail:** 10 of the 19 anúncios collected locally have `ano > 2000` (Lancer 2015, Mini 2025, GOL G3 2001, etc.) and are permanently invisible to the homepage search, even if stored.

## Deduced Conclusions

### Deduction 1: Empty DB for this source explains 0 search results

**Based on:** Findings 2, 3.

**Reasoning:** If `coletar_completo()` has not been successfully run on Render since the fix (commit `c8451b0`) was deployed, the `anuncios` table contains no rows with `fonte = 'reginaldodecampinas'`. `buscar_anuncios()` would return an empty list regardless of query.

**Conclusion:** Either (a) collection has not been triggered post-deploy, or (b) collection was triggered but captured 0 anúncios on Render.

### Deduction 2: WP API or detail pages may be blocked on Render

**Based on:** Finding 1.

**Reasoning:** The listing HTML page was confirmed blocked from Render's Frankfurt IP (2.2 s pattern). The WP REST API is a different route (`/wp-json/wp/v2/product`) but on the same Hostinger-hosted domain. Hostinger may apply the same anti-bot rules at the server/CDN level regardless of path. Product detail pages (`/produto/[slug]/`) are also on the same domain and may be similarly blocked.

**Conclusion:** The new API-based path may encounter the same blocking, producing either 0 candidatos (H2) or 0 prices from detail pages (H3).

## Hypothesized Paths

### Hypothesis 1: Collection not triggered on Render after fix deploy

**Status:** Refuted

**Theory:** The fix was pushed ~10 minutes before this investigation opened. The user may have tested before the Render auto-deploy finished.

**Resolution:** Refuted by observation. Old code took ~2.2 s (2 retries + 2.0 s sleep). New code ran in 0.2 s → confirms new code is active. Deploy was complete.

### Hypothesis 2: WP REST API also blocked on Render's IP

**Status:** Confirmed

**Theory:** Hostinger blocks all requests from datacenter IPs at the CDN layer — not just the HTML listing page, but every endpoint on the domain including the WP REST API.

**Would confirm:** Collection runs in < 0.5 s with 0 anúncios on Render (no time for any HTTP round-trip to succeed).

**Resolution:** Confirmed. User-reported execution time = 0.2 s with 0 anúncios and no errors. The new code (post-fix) makes only one external call — `sessao.get(API_URL, ...)` in `_obter_urls_api`. 0.2 s is consistent with an immediate TCP rejection or fast HTTP 403/bot-challenge before any product URL is retrieved. Identical pattern to registro9, lopesantigos, lexicar, autoclassic.

### Hypothesis 3: WP API works but product detail pages are blocked on Render

**Status:** Refuted

**Theory:** WP API returns candidatos but detail pages are blocked.

**Resolution:** Refuted. If 36 candidatos had been fetched, the connector would then sleep 1 s per detail page × 36 = ~36+ s total. Observed time was 0.2 s — no detail pages were ever requested.

### Hypothesis 4: Data stored in DB but query matching prevents retrieval

**Status:** Refuted

**Theory:** Data in DB but brand mismatch hides it from search.

**Resolution:** Refuted. 0.2 s collection time means 0 anúncios were ever produced or stored. The DB is empty for this source.

## Missing Evidence

| Gap | Impact | How to Obtain |
| --- | ------- | ------------- |
| Render admin log after deploy | Collapses H1/H2/H3 simultaneously | Trigger collection from admin panel; inspect log |
| Execution time of post-fix collection on Render | Distinguishes H2 (fast, ~2 s) from H3 (slow, ~36 s) | Same admin log |
| `erros_detalhe` count in post-fix collection | Distinguishes H3 (36 errors) from success (0 errors) | Same admin log |
| DB contents for `fonte = 'reginaldodecampinas'` | Distinguishes H4 from H1/H2/H3 | `SELECT COUNT(*) FROM anuncios WHERE fonte = 'reginaldodecampinas'` |

## Source Code Trace

| Element | Detail |
| ------- | ------- |
| Error origin | `src/connectors/reginaldodecampinas.py:_obter_urls_api` (candidatos) or `:_extrair_preco_detalhe` (prices) |
| Trigger | Admin panel "Coletar" → `app.py:427` `mod.coletar_completo()` |
| Condition | Network access to `reginaldodecampinas.com.br` from Render Frankfurt IP |
| Related files | `app.py:408-447`, `src/pipeline/persistence.py:165-205`, `src/pipeline/persistence.py:277-313` |

## Conclusion

**Confidence:** High

**Causa raiz confirmada:** O CDN/Hostinger que serve `reginaldodecampinas.com.br` bloqueia todas as requisições HTTP originadas do IP do Render (Frankfurt/datacenter), independente do endpoint — HTML listing, WP REST API, páginas de detalhe. A coleta termina em 0,2 s porque a primeira chamada à API falha instantaneamente, sem retry (já que `_obter_urls_api` usa try/except com break imediato). O mesmo padrão está confirmado em outros 4 conectores inativos do projeto: `registro9`, `lopesantigos`, `lexicar`, `autoclassic`.

A percepção do usuário de que "o coletor aparentemente acessa as informações" refere-se ao comportamento local (onde funciona), não ao Render.

**Status:** Concluded

## Fix Direction

### Opção A — Marcar como inativa (imediato, sem custo)
Adicionar `"reginaldodecampinas"` ao conjunto `FONTES_INATIVAS` em `app.py:112`. Documenta o motivo (ECONNREFUSED / anti-bot de datacenter). Sem impacto para o usuário além de deixar de tentar coletar.

### Opção B — GitHub Actions scraper (definitivo, moderado esforço)
Criar um workflow `.github/workflows/scrape-reginaldo.yml` que roda o conector de um runner do GitHub Actions (IP residencial/não-datacenter), salva os anúncios em JSON, e faz POST para um endpoint protegido no Render. Resolve o bloqueio de IP sem custo adicional de proxy.

### Opção C — Proxy residencial brasileiro (definitivo, custo mensal)
Rotear as requisições do conector por um serviço de proxy com IPs residenciais brasileiros (ex.: BrightData, Oxylabs). Mais complexo de manter.

## Reproduction Plan

Já reproduzido e confirmado:
1. Deploy commit `c8451b0` no Render ✓
2. Coletar via admin panel → 0,2 s, 0 anúncios, sem erros ✓
3. Diagnóstico: bloqueio de IP no CDN/Hostinger ✓

## Side Findings

- Of 19 anúncios captured locally, 10 have `ano > 2000` and are permanently excluded from the homepage search by the `ano <= 2000` filter — this is expected behavior but means maximum visible yield from this source is ~9 anúncios.
- Brand alias `_MARCA_ALIAS` in the connector does not cover `LANCER` (Mitsubishi), `VESPA` (own brand), or `RAM` (own brand). These are stored with non-standard `marca` values. The 2 vehicles affected that pass `ano <= 2000` are Vespa PX 200S 1987 and Ram 1500 V8 1995 — searchable only if the user queries `VESPA` or `RAM` directly.
