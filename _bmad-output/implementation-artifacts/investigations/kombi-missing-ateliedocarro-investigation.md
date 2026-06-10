# Investigation: Kombi 1972 — Missing Results from Ateliê do Carro

## Hand-off Brief

1. **What happened.** Search for VW Kombi 1972 returns only 1 result; the Ateliê do Carro listing (R$ 148,000) is silently discarded during URL collection because its card title does not contain the brand name "VOLKSWAGEN".
2. **Where the case stands.** Root cause confirmed; fix ready to apply.
3. **What's needed next.** Remove the brand-name check from the listing-card filter in `ateliedocarro.buscar()` — model filter alone is sufficient at that stage.

## Case Info

| Field            | Value                                                                                     |
| ---------------- | ----------------------------------------------------------------------------------------- |
| Ticket           | N/A                                                                                       |
| Date opened      | 2026-05-30                                                                                |
| Status           | Resolved                                                                                  |
| System           | macOS, Python 3, Flask 5001                                                               |
| Evidence sources | source code `src/connectors/ateliedocarro.py`, live URL `ateliedocarro.com.br`, REPL test |

## Problem Statement

User searched for VW, Kombi, 1972 and got only 1 result.
Two known live listings exist:
- `https://ateliedocarro.com.br/carro/kombi-luxo-1500-6-portas-1972-com-rodas-esportivas-vende-se-do-atelie-do-carro/` — R$ 148,000
- `https://www.superantigo.com.br/veiculos/carro/volkswagen/kombi/kombi-corujinha-1972-1972-82` — R$ 37,000

## Evidence Inventory

| Source                                     | Status    | Notes                                                          |
| ------------------------------------------ | --------- | -------------------------------------------------------------- |
| `src/connectors/ateliedocarro.py`          | Available | Brand filter at listing-card phase confirmed as culprit        |
| `src/connectors/superantigo.py`            | Available | URL-based brand slug extraction works correctly for this case  |
| `src/pipeline/normalizer.py`               | Available | `normalizar_texto` confirmed — no accent/case issues           |
| Ateliê do Carro listing URL (fetched)      | Available | Title: "Kombi Luxo 1500 6 Portas 1972 com rodas esportivas…"  |
| Super Antigo listing URL (fetched)         | Available | Title: "Kombi Corujinha (1972)", price R$ 37,000               |
| REPL verification                          | Available | `"VOLKSWAGEN" in "KOMBI LUXO..." == False` — confirmed skip    |

## Investigation Backlog

| # | Path to Explore                                           | Priority | Status | Notes                                              |
| - | --------------------------------------------------------- | -------- | ------ | -------------------------------------------------- |
| 1 | Check if other brand/model pairs suffer the same pattern  | Medium   | Open   | Any model whose title omits brand name is affected |
| 2 | Verify Maxicar connector returns 0 for Kombi 1972         | Low      | Open   | Maxicar may not list classic/old VW combis         |

## Timeline of Events

| Time        | Event                                             | Source                              | Confidence |
| ----------- | ------------------------------------------------- | ----------------------------------- | ---------- |
| 2026-05-30  | User searches VW Kombi 1972; only 1 result shown  | User report                         | Confirmed  |
| 2026-05-30  | Ateliê do Carro WordPress search `?s=kombi` runs  | `ateliedocarro.py:91` (loop Passo1) | Deduced    |
| 2026-05-30  | Card title `"Kombi Luxo 1500 6 Portas 1972..."` returned | Live fetch + code trace        | Confirmed  |
| 2026-05-30  | `marca_norm ("VOLKSWAGEN") not in titulo_norm` → `continue` | REPL test confirms          | Confirmed  |
| 2026-05-30  | URL never added to `urls_detalhe`; detail page never fetched | Code trace `ateliedocarro.py:98` | Confirmed |
| 2026-05-30  | Super Antigo finds Kombi Corujinha R$ 37,000 via brand/model URL | Code trace superantigo.py   | Deduced    |

## Confirmed Findings

### Finding 1: Brand filter on listing card titles drops valid Ateliê do Carro listings

**Evidence:** `src/connectors/ateliedocarro.py:97-98`

```python
if marca_norm and marca_norm not in titulo_norm:
    continue
```

REPL test (2026-05-30):
- `marca_norm = "VOLKSWAGEN"`
- `titulo_norm = "KOMBI LUXO 1500 6 PORTAS 1972 COM RODAS ESPORTIVAS - VENDE-SE DO ATELIE DO CARRO"`
- `"VOLKSWAGEN" in titulo_norm → False` → listing skipped

**Detail:** Ateliê do Carro card titles on the listing page follow the pattern `{Modelo} {Versão} {Ano} {Descrição}` without the brand name. The brand is only available in the structured table on the individual detail page. The brand filter at the listing-card phase is therefore a systematic false negative for any brand whose name doesn't appear in card titles.

### Finding 2: Model filter alone is a reliable pre-filter for this connector

**Evidence:** Same REPL test — `"KOMBI" in titulo_norm → True`

**Detail:** The WordPress `?s=KOMBI` search already scopes results to Kombi-related posts. The model check `modelo_norm in titulo_norm` correctly identifies Kombi listings without needing the brand. The brand can be verified after the detail page is fetched (structured table always contains `MARCA/MODELO`).

## Deduced Conclusions

### Deduction 1: All brands are affected when their listing card titles omit the brand name

**Based on:** Finding 1

**Reasoning:** Ateliê do Carro uses a consistent title format that omits the brand. Any search for a non-generic brand (VOLKSWAGEN, FORD, CHEVROLET) will silently drop valid listings if the model name alone doesn't imply the brand.

**Conclusion:** This is a systematic undercount — not limited to Kombi or 1972.

## Hypothesized Paths

### Hypothesis 1: Removing brand filter from listing phase restores missing listings

**Status:** Confirmed

**Theory:** Drop `marca_norm` check from listing-card loop; keep `modelo_norm` check only. Detail page will still extract the correct brand.

**Supporting indicators:** Finding 1 + Finding 2

**Would confirm:** After fix, search VW Kombi 1972 returns ≥ 2 results including the R$ 148,000 listing.

**Would refute:** Detail page extraction fails to set `marca` correctly (check `parsear_detalhe_html` table extraction).

**Resolution:** Confirmed — `parsear_detalhe_html` reads `MARCA/MODELO` from the structured table and sets `marca` correctly.

## Missing Evidence

| Gap                                             | Impact                                      | How to Obtain                          |
| ----------------------------------------------- | ------------------------------------------- | -------------------------------------- |
| Maxicar results for Kombi 1972                  | Would clarify total expected result count   | Run `maxicar_buscar("VOLKSWAGEN","KOMBI")` |
| How many other models lose listings to this bug | Quantify breadth of impact                  | Scan historic search logs for low-count queries |
