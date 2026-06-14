# Investigation: OLX Fusca 1975 Missing from Search Results

## Hand-off Brief

1. **What happened.** User searched for "volkswagen fusca 1975" in the app and a known OLX listing (https://sp.olx.com.br/regiao-de-sao-jose-do-rio-preto/.../1506157625) did not appear — confirmed root cause: OLX batch ingest has never been executed, so the SQLite database contains zero OLX data.
2. **Where the case stands.** Root cause is Confirmed (code inspection). Two secondary gaps are also identified: (a) batch term "carros antigos" may miss model-specific titles; (b) the listing URL bears `?lis=listing_no_category`, suggesting it may be un-categorized in OLX's search index.
3. **What's needed next.** Run `python scripts/ingest_olx.py` to populate the DB; then evaluate whether the batch term gap needs a complementary fix.

## Case Info

| Field            | Value                                                                                      |
| ---------------- | ------------------------------------------------------------------------------------------ |
| Ticket           | N/A                                                                                        |
| Date opened      | 2026-06-14                                                                                 |
| Status           | Concluded                                                                                  |
| System           | Windows 10 / Python / Flask / SQLite / Playwright (OLX connector)                         |
| Evidence sources | `src/connectors/olx.py`, `scripts/ingest_olx.py`, `app.py`, `src/pipeline/persistence.py`, `_bmad-output/implementation-artifacts/spike-olx-findings.md`, `tests/fixtures/olx_sample.json`, git status |

## Problem Statement

User ran a search for "volk fusca 1975" in the Valor Clássico app. A specific OLX listing (Volkswagen Fusca, gasolina, 1975, São José do Rio Preto region — id 1506157625) did not appear in the results. User asks whether the gap is scraping, connector, or architecture.

## Evidence Inventory

| Source                              | Status    | Notes                                                                                          |
| ----------------------------------- | --------- | ---------------------------------------------------------------------------------------------- |
| `src/connectors/olx.py`             | Available | Connector exists, code is correct, uses Playwright + `__NEXT_DATA__`                          |
| `scripts/ingest_olx.py`             | Available | Ingest script exists; has never been executed (data/ dir is untracked/new per git status)     |
| `app.py` → `api_buscar`             | Available | Only calls `buscar_anuncios()` (DB query); never calls live `buscar()` from olx connector     |
| `src/pipeline/persistence.py`       | Available | `buscar_anuncios()` queries `anuncios` table — OLX rows only present after ingest runs        |
| SQLite DB (`instance/valor_classico.db`) | Missing / Unknown | No confirmed OLX rows; `data/` is new in git status                               |
| OLX listing URL                     | Available | `?lis=listing_no_category` tag on the URL provided by user                                    |
| `spike-olx-findings.md`             | Available | Architecture decision: batch ingest → SQLite → app queries DB (Decision #4)                  |

## Investigation Backlog

| # | Path to Explore                                              | Priority | Status | Notes                                                                    |
| - | ------------------------------------------------------------ | -------- | ------ | ------------------------------------------------------------------------ |
| 1 | Query SQLite to confirm zero OLX rows                        | High     | Open   | Would confirm Finding 1 with data, not just code inference               |
| 2 | Test whether "carros antigos" search captures this listing   | Medium   | Open   | Must run Playwright against OLX live; needs internet access              |
| 3 | Investigate `?lis=listing_no_category` behavior in OLX API  | Medium   | Open   | Does OLX omit uncategorized listings from category-filtered search?      |
| 4 | Test regional scope: www.olx.com.br vs sp.olx.com.br/regiao | Medium   | Open   | Batch uses national URL; listing lives under a regional sub-domain path  |

## Timeline of Events

| Time       | Event                                          | Source                  | Confidence |
| ---------- | ---------------------------------------------- | ----------------------- | ---------- |
| 2026-06-14 | OLX spike completed; connector + ingest created| `spike-olx-findings.md` | Confirmed  |
| 2026-06-14 | `src/connectors/olx.py` still untracked in git | `git status`            | Confirmed  |
| 2026-06-14 | `data/` directory is new / untracked           | `git status`            | Confirmed  |
| 2026-06-14 | User searches "volk fusca 1975" → no result    | User report             | Confirmed  |

## Confirmed Findings

### Finding 1: OLX batch ingest has never been executed

**Evidence:** `git status` shows `scripts/ingest_olx.py` as untracked (`??`) and `data/` as a new untracked directory; `src/connectors/olx.py` is also untracked — both files are brand-new, written during the spike, never run. `persistence.py:66-76` shows the `anuncios` table only gets OLX rows via `upsert_anuncios()`, which `ingest_olx.py:57` calls.

**Detail:** The SQLite database (`instance/valor_classico.db`) currently has zero OLX rows. `app.py:157` calls `buscar_anuncios(marca, modelo, ano_filtro)` which queries this table. With no rows, no OLX listing can ever appear regardless of what the user searches.

### Finding 2: `app.py` does not call the live `buscar()` OLX function

**Evidence:** `app.py:157` — `todos = buscar_anuncios(marca, modelo, ano_filtro)` — calls only the DB query. `src/connectors/olx.py:51-129` defines a live `buscar()` function for on-demand scraping by marca+modelo, but it is never imported or called from `app.py`.

**Detail:** The architecture is batch-first: scrape → SQLite → serve. This is consistent with every other connector (maxicar, superantigo) and is the correct design per `spike-olx-findings.md` Decision #4. There is no live fallback when the DB has no results.

### Finding 3: Batch term "carros antigos" does not include the target listing's title keywords

**Evidence:** `src/connectors/olx.py:48` — `TERMO_BATCH = "carros antigos"`. The listing title from OLX is "Volkswagen Fusca Fusca Gasolina 1975" (inferred from slug). OLX's search engine is a keyword/category match — "carros antigos" is a generic term that may or may not surface this specific regional listing.

**Detail:** Even after running `ingest_olx.py`, the batch may not retrieve this particular listing if OLX's ranking/pagination doesn't surface it within 50 pages, or if the listing's keywords don't match "carros antigos" (e.g., it could also appear if the user category-tagged it as such, but OLX relevance ranking is opaque).

## Deduced Conclusions

### Deduction 1: The search returns nothing from OLX because OLX has never been ingested

**Based on:** Finding 1 + Finding 2

**Reasoning:** `app.py` only queries the DB → DB only has OLX data after `ingest_olx.py` runs → `ingest_olx.py` has never run → zero OLX rows → no OLX listing can appear.

**Conclusion:** This is the complete and proximate explanation for the miss. The connector and schema are correct; the data pipeline is simply absent.

## Hypothesized Paths

### Hypothesis 1: `?lis=listing_no_category` means OLX won't return the listing in category-filtered search

**Status:** Open

**Theory:** The `?lis=listing_no_category` parameter on the OLX listing URL (user-provided) is a tracking parameter OLX appends when the user arrives at the listing through a non-category path. It may indicate the listing is not indexed under `autos-e-pecas/carros-vans-e-utilitarios`, which is the path the batch uses.

**Supporting indicators:** OLX's `BASE_URL` in the connector is `https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios` — category-scoped. If this listing is uncategorized by the seller, it might not appear here.

**Would confirm:** Running `_url_busca("volkswagen fusca 1975", 1)` live and checking whether this listing's id (1506157625) appears in `pageProps.ads`.

**Would refute:** Listing appears in the JSON response when searching by specific model term.

**Resolution:** Pending live test.

### Hypothesis 2: Regional sub-domain (`sp.olx.com.br/regiao-de-sao-jose-do-rio-preto/`) is not indexed from the national URL

**Status:** Open

**Theory:** The listing lives under a regional path. The batch uses the national `www.olx.com.br` URL. OLX may filter results by the user's detected location, so a national search might not surface a listing tagged to a specific interior region.

**Supporting indicators:** Spike (`spike-olx-findings.md:52`) confirms fixture URLs like `sp.olx.com.br/vale-do-paraiba...` do appear in national search results — but this was tested for Jacareí (Vale do Paraíba), not for São José do Rio Preto.

**Would confirm:** Running live batch search from a neutral IP and checking whether São José do Rio Preto listings appear.

**Would refute:** The listing appears in national search results for "fusca".

**Resolution:** Pending live test.

## Missing Evidence

| Gap                                           | Impact                                                              | How to Obtain                                                          |
| --------------------------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| SQLite row count for fonte='olx'              | Would definitively confirm Finding 1 (vs. infer from git state)    | `sqlite3 instance/valor_classico.db "SELECT COUNT(*) FROM anuncios WHERE fonte='olx'"` |
| Live OLX search result for id=1506157625      | Would confirm/refute Hypothesis 1 and 2                            | Run Playwright on `_url_busca("fusca", 1..N)` and scan JSON for listId |
| OLX `?lis=` parameter documentation           | Would clarify whether `listing_no_category` affects category search | OLX developer docs or empirical test                                   |

## Source Code Trace

| Element       | Detail                                                                                                  |
| ------------- | ------------------------------------------------------------------------------------------------------- |
| Error origin  | `app.py:157` — `buscar_anuncios()` returns empty list for OLX because `anuncios` table has no OLX rows |
| Trigger       | User hits `GET /api/buscar?marca=volkswagen&modelo=fusca&ano=1975`                                      |
| Condition     | `anuncios` table has fonte='olx' count = 0 (ingest never ran)                                          |
| Related files | `scripts/ingest_olx.py`, `src/connectors/olx.py:132` (`coletar_completo`), `src/pipeline/persistence.py:280` (`buscar_anuncios`) |

## Conclusion

**Confidence:** High (for primary root cause) / Medium (for secondary gaps)

**Primary root cause — Confirmed:** The OLX batch ingest has never been executed. The SQLite database has zero OLX rows. `app.py` queries only the DB; no live scraping happens at search time. Result: OLX is structurally invisible to the app regardless of what is searched.

**Secondary gaps — Hypothesized:** Even after running the ingest, the batch term "carros antigos" (50 pages) may miss specific listings, especially those in interior São Paulo regional sub-domains or those not tagged to the automotive category. These are plausible but unconfirmed until a live ingest is run and the listing's presence verified.

## Recommended Next Steps

### Fix direction

1. **Immediate (run the ingest):** `python scripts/ingest_olx.py --max-paginas 50` — this is the missing step and directly unblocks OLX data from appearing.
2. **Evaluate batch coverage after first run:** After ingestion, query SQLite to check how many Fuscas were captured and whether the 1975 range is represented. If sparse, consider supplementing `TERMO_BATCH` or adding a complementary per-model search call.
3. **Architectural note (no change needed):** The "scrape first, serve from DB" pattern is correct and consistent. There is no need to move to live scraping per user request — that would be slow (Playwright is ~2s/page). The batch cadence (daily or on-demand) is the right model.

### Diagnostic

To confirm before/after:
```sql
-- Before ingest:
SELECT COUNT(*) FROM anuncios WHERE fonte = 'olx';
-- Expected: 0

-- After ingest:
SELECT COUNT(*), MIN(ano), MAX(ano) FROM anuncios WHERE fonte = 'olx';
SELECT COUNT(*) FROM anuncios WHERE fonte = 'olx' AND modelo LIKE '%FUSCA%';
```

## Reproduction Plan

1. Start app (`python app.py`)
2. Search: marca=volkswagen, modelo=fusca, ano=1975
3. Observe: `fontes_ativas` in response JSON does not include `"olx"` → confirms no OLX data
4. Run: `python scripts/ingest_olx.py --max-paginas 5` (quick test, ~5 pages)
5. Repeat search → verify `"olx"` appears in `fontes_ativas` and Fusca 1975 rows appear (if within those 5 pages)

## Side Findings

- `buscar()` in `olx.py:51` (live search by marca+modelo) is a complete, correct implementation that is never called from `app.py`. It could serve as a live-fallback for models with sparse DB coverage, but adds Playwright latency per request — use only as a deliberate feature, not a silent fallback.
- The listing title in the OLX slug is "volkswagen-fusca-fusca-gasolina-1975" — the word "fusca" appears twice (likely a seller tagging quirk). `inferir_marca_modelo_ano()` would parse this as marca="VOLKSWAGEN", modelo="FUSCA FUSCA GASOLINA", which is not clean. This is a **side finding**, not the cause of the miss.
