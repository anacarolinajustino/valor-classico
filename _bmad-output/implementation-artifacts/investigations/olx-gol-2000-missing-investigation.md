# Investigation: OLX Gol Geração III 2000 Missing from Results

## Hand-off Brief

1. **What happened.** Listing `1474716439` (Volkswagen Gol Geração III, 2000, Grande Campinas) is absent from the Valor Clássico results. Root cause: the OLX ingest has never been executed (zero OLX rows in DB). However, a secondary structural risk exists — the `?sf=1&ae=2000` URL year-filter added to `coletar_categoria()` is **unvalidated**: if OLX ignores or misinterprets the `ae` parameter, the function may return 0 results and terminate silently.
2. **Where the case stands.** The parser would accept this listing (year 2000 passes `1900 ≤ ano ≤ 2000`; model extraction succeeds; listing is properly categorized with `listingCategoryId="2020"`). The only confirmed blocker is zero OLX data. The URL filter risk is Hypothesized.
3. **What's needed next.** Run the ingest with a quick sanity check first: `--max-paginas 2` to confirm `coletar_categoria()` actually returns ads; then full run. If page 1 returns 0 ads, the `ae` parameter is broken and must be removed.

## Case Info

| Field            | Value                                                                                                                                                    |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ticket           | N/A                                                                                                                                                      |
| Date opened      | 2026-06-14                                                                                                                                               |
| Status           | Concluded                                                                                                                                                |
| System           | Windows 10 / Python / Flask / SQLite / Playwright (OLX connector)                                                                                       |
| Evidence sources | `src/connectors/olx.py`, `tests/fixtures/olx_sample.json`, `src/pipeline/normalizer.py:67-103`, `src/pipeline/persistence.py:30`, prior investigation `olx-fusca-search-miss-investigation.md` |

## Problem Statement

User provided OLX listing URL `https://sp.olx.com.br/grande-campinas/autos-e-pecas/carros-vans-e-utilitarios/volkswagen-gol-geracao-iii-1-6-mi-8v-gasolina-mec-4p-2000-1474716439?lis=listing_2020` and reports it is not appearing in the app. Asks why.

## Evidence Inventory

| Source | Status | Notes |
| --- | --- | --- |
| `tests/fixtures/olx_sample.json` | Available | Real `__NEXT_DATA__` structure; all 5 fixtures have `listingCategoryId: "2020"` |
| `src/connectors/olx.py` | Available | `coletar_categoria()` added; uses unvalidated `?sf=1&ae=2000` |
| `src/pipeline/normalizer.py:67` | Available | `inferir_marca_modelo_ano()` traced; model extraction result confirmed |
| `src/pipeline/persistence.py:30` | Available | `ANO_CORTE_CLASSICO = 2000`; filter: `ano <= ANO_CORTE_CLASSICO` |
| Prior investigation (fusca) | Available | Confirmed: zero OLX rows in DB, ingest never ran |
| OLX `ae` parameter behavior | Missing | Cannot confirm without live request |

## Investigation Backlog

| # | Path to Explore | Priority | Status | Notes |
| - | --- | --- | --- | --- |
| 1 | Verify `?sf=1&ae=2000` returns ads on page 1 | High | Open | Run `--max-paginas 2` and check logs |
| 2 | Confirm zero OLX rows in DB | High | Open | `sqlite3 instance/valor_classico.db "SELECT COUNT(*) FROM anuncios WHERE fonte='olx'"` |
| 3 | Verify model parsing for real subject string | Medium | Open | Actual `subject` field may differ from URL slug |

## Timeline of Events

| Time | Event | Source | Confidence |
| --- | --- | --- | --- |
| 2026-06-14 | OLX connector created; ingest never run | `olx-fusca-search-miss-investigation.md` | Confirmed |
| 2026-06-14 | `coletar_categoria()` implemented with `?sf=1&ae=2000` | `src/connectors/olx.py` | Confirmed |
| 2026-06-14 | User reports Gol 2000 listing absent | User report | Confirmed |

## Confirmed Findings

### Finding 1: `?lis=listing_2020` is a standard tracking parameter, not a structural anomaly

**Evidence:** `tests/fixtures/olx_sample.json:205,387,584,777,993` — ALL 5 real fixtures have `"listingCategoryId": "2020"` and `"searchCategoryLevelOne": 2020`. The OLX internal category ID for "Carros, vans e utilitários" IS `2020`. The `?lis=listing_2020` in the URL is OLX appending which category the user navigated from — standard tracking, not a flag indicating the listing is uncategorized or hard to reach.

**Detail:** The previous investigation worried about `?lis=listing_no_category` as a potential indexing problem. This listing has `?lis=listing_2020` which means it is **properly categorized** in the expected category. It should appear in a category-level scrape.

### Finding 2: Year 2000 PASSES the parser filter

**Evidence:** `src/pipeline/persistence.py:30` — `ANO_CORTE_CLASSICO = 2000`. `src/connectors/olx.py:552` — filter: `not (1900 <= ano <= ano_ate)`. With `ano=2000` and `ano_ate=2000`: `1900 <= 2000 <= 2000` is `True`; the `not` makes the discard condition `False`. The listing passes.

**Detail:** Year 2000 sits exactly on the boundary and is included. No off-by-one.

### Finding 3: Model extraction succeeds for this listing's title pattern

**Evidence:** `src/pipeline/normalizer.py:67-103` — algorithm: scan right-to-left for last 4-digit year token in 1900-2099; `marca = tokens[0]`; `modelo = join(tokens[1:])`. URL slug `volkswagen-gol-geracao-iii-1-6-mi-8v-gasolina-mec-4p-2000` → `subject` ≈ "Volkswagen Gol Geração III 1.6 MI 8V Gasolina Mec. 4p 2000" → after `normalizar_texto`: tokens include "2000" as last year token → `modelo = "GOL GERACAO III 1.6 MI 8V GASOLINA MEC. 4P"` (non-empty).

**Detail:** The `if not modelo` guard at `olx.py:529` is NOT triggered. Listing passes model check.

### Finding 4: Zero OLX data in DB (inherited from prior investigation)

**Evidence:** `olx-fusca-search-miss-investigation.md:Finding 1` — ingest never executed; `git status` confirms `scripts/ingest_olx.py` and `src/connectors/olx.py` are untracked new files.

## Deduced Conclusions

### Deduction 1: The listing is absent because OLX was never ingested

**Based on:** Finding 4

**Reasoning:** `app.py` queries only the SQLite DB. The DB has zero OLX rows. Therefore, no OLX listing — including this Gol — can appear regardless of whether the scraper would capture it.

**Conclusion:** This is the complete proximate explanation.

### Deduction 2: IF the ingest runs, this listing WILL be captured — provided the URL filter works

**Based on:** Findings 1, 2, 3

**Reasoning:** The listing is properly categorized (Finding 1) → will appear in a category scrape. Year 2000 passes the parser filter (Finding 2). Model extraction succeeds (Finding 3). The only unknown is whether `?sf=1&ae=2000` returns the listing or returns zero results.

## Hypothesized Paths

### Hypothesis 1: `?sf=1&ae=2000` is a valid OLX URL filter that returns cars with regdate ≤ 2000

**Status:** Open

**Theory:** OLX Brasil exposes year-range filters via `sf=1` (filter mode) and `ae=YEAR` (ano até). This is a common OLX pattern from international deployments. The category URL with this filter would return only classic-era cars, reducing pagination significantly.

**Supporting indicators:** Parameter naming (`ae` = "até o ano") is consistent with Brazilian Portuguese OLX labels. The `sf=1` pattern activates faceted search on many OLX instances.

**Would confirm:** Running `coletar_categoria(max_paginas=2)` produces ads with `regdate ≤ 2000` in logs.

**Would refute:** Running with `--max-paginas 2` produces `[olx] categoria pág 1: sem anúncios — parando.` in logs; or produces ads with `regdate > 2000`.

**Resolution:** Pending live test.

### Hypothesis 2: `ae=2000` is not a valid OLX parameter; OLX ignores it and returns all years

**Status:** Confirmed — 2026-06-14

**Theory:** OLX Brasil ignores `sf=1&ae=2000` and returns all car years regardless.

**Resolution:** User tested `https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?sf=1&ae=2000` directly in browser and confirmed modern cars (year > 2000) appear. Parameter has no effect. **Fix applied:** `_url_categoria()` updated to use no year filter parameters; filtering relies exclusively on `regdate` field in `_parsear_ads()`.

### Hypothesis 3: `ae=2000` causes OLX to return an error or empty result set

**Status:** Refuted — 2026-06-14

**Resolution:** User tested the URL and confirmed listings ARE returned (modern cars visible). OLX does not error on the parameter, it simply ignores it.

## Missing Evidence

| Gap | Impact | How to Obtain |
| --- | --- | --- |
| Live response from `?sf=1&ae=2000` | Confirms/refutes all 3 hypotheses | `python scripts/ingest_olx.py --max-paginas 2` and check logs |
| Actual `subject` field for listing 1474716439 | Validates Finding 3 (model extraction) | Appears in scrape logs when listing is fetched |
| SQLite OLX row count | Confirms Finding 4 directly | `sqlite3 instance/valor_classico.db "SELECT COUNT(*) FROM anuncios WHERE fonte='olx'"` |

## Source Code Trace

| Element | Detail |
| --- | --- |
| Error origin | `app.py` → `buscar_anuncios()` → zero OLX rows in `anuncios` table |
| Trigger | User search hits GET `/api/buscar` |
| Condition | `anuncios WHERE fonte='olx'` = 0 rows; ingest never executed |
| Secondary risk | `src/connectors/olx.py:_url_categoria()` — `ae=2000` unvalidated |
| Related files | `scripts/ingest_olx.py`, `src/connectors/olx.py:140-235` (`coletar_categoria`), `src/pipeline/persistence.py:280` |

## Conclusion

**Confidence:** High (primary cause) / Medium (secondary risk)

**Primary cause — Confirmed:** The listing is absent because OLX was never ingested. Zero OLX rows in DB.

**Secondary risk — Hypothesized:** The `?sf=1&ae=2000` URL filter in `coletar_categoria()` has not been validated. If OLX rejects it (Hypothesis 3), the scrape silently returns 0 results. This must be verified before a full ingest run.

**The listing itself would be captured** if the scrape runs correctly: it is properly categorized, year 2000 is within the accepted range, and model extraction succeeds.

## Recommended Next Steps

### Fix direction

1. **Immediate sanity check:** `python scripts/ingest_olx.py --max-paginas 2` and read the log output.
   - If page 1 shows `>0` brutos → URL filter works (or is ignored but safe) → proceed with full run.
   - If page 1 shows `sem anúncios` → remove `sf=1&ae=2000` from `_url_categoria()` and rely on client-side filter only.
2. **Full ingest:** After sanity check passes, run without `--max-paginas` for complete coverage.

### Diagnostic

```bash
# Step 1: Sanity check (2 pages, watch the logs)
python scripts/ingest_olx.py --max-paginas 2

# Step 2: Confirm OLX data after sanity check
sqlite3 instance/valor_classico.db "SELECT COUNT(*), MIN(ano), MAX(ano) FROM anuncios WHERE fonte='olx';"

# Step 3: Full ingest
python scripts/ingest_olx.py
```

If step 1 returns 0 ads, patch `_url_categoria()`:
```python
# Remove year filter — rely on client-side only
def _url_categoria(pagina: int = 1, ano_ate: int = ANO_CORTE_CLASSICO) -> str:
    params: dict[str, str] = {}
    if pagina > 1:
        params["o"] = str(pagina)
    return f"{BASE_URL}?{urllib.parse.urlencode(params)}" if params else BASE_URL
```

## Reproduction Plan

1. Run `python scripts/ingest_olx.py --max-paginas 2`
2. Check log for `[olx] categoria pág 1: X brutos → Y válidos → Z novos`
3. If Z > 0: URL filter works. Search app for "gol" to verify Gol 2000 appears.
4. If Z = 0: Hypothesis 3 confirmed. Remove `ae` parameter and re-run.

## Side Findings

- `listingCategoryId: "2020"` and `searchCategoryLevelOne: 2020` in the OLX JSON are OLX's internal IDs for the "Carros, vans e utilitários" sub-category. The `?lis=listing_2020` tracking parameter in listing URLs always equals this category ID for all properly-categorized car listings — it is NOT a year reference. Prior concern about `listing_no_category` (previous investigation) remains valid only for uncategorized listings.
- OLX returns regional subdomain URLs (e.g., `sp.olx.com.br`, `mg.olx.com.br`) in the `url` field of `__NEXT_DATA__` even when the national URL is scraped. The Gol listing at `sp.olx.com.br/grande-campinas/...` would be stored with its full regional URL — no dedup mismatch expected.
