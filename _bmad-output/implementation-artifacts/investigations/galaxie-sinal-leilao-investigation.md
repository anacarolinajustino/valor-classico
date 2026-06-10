# Investigation: FORD GALAXIE 500 1968 (lote Picelli) não aparece na busca

## Hand-off Brief

1. **What happened.** O lote `4-fordgalaxie-500-19681968` não aparece no sinal de leilão porque está com `status: "aberto"` na fonte (leilão em andamento, 1 lance de R$ 70.000) — e o conector, por decisão metodológica documentada, só considera `status: "vendido"` (preço realizado). **Confirmed.**
2. **Where the case stands.** Root cause confirmado; comportamento é by design, não defeito. A busca FORD GALAXIE funciona (3 anúncios do Ateliê do Carro retornados; `sinal_leilao.considerado: false` correto).
3. **What's needed next.** Decisão de produto: exibir ou não lotes de leilão EM ANDAMENTO como um terceiro sinal ("leilão aberto — lance atual"), distinto de preço pedido e preço realizado.

## Case Info

| Field            | Value                                                                |
| ---------------- | -------------------------------------------------------------------- |
| Ticket           | N/A                                                                   |
| Date opened      | 2026-06-10                                                            |
| Status           | Concluded                                                             |
| System           | Valor Clássico local (Flask :5001), fonte api.picellileiloes.com.br  |
| Evidence sources | API Supabase da fonte, endpoint local /api/buscar, catálogo, código  |

## Problem Statement

Usuária: "pesquisei esse carro https://www.picellileiloes.com.br/lote/4-fordgalaxie-500-19681968 e nao achou" — premissa inicial de defeito na busca/conector.

## Evidence Inventory

| Source                              | Status    | Notes                                          |
| ----------------------------------- | --------- | ---------------------------------------------- |
| API da fonte (public_lots por slug) | Available | Consulta direta em 2026-06-10                  |
| /api/buscar local (reprodução)      | Available | marca=FORD&modelo=GALAXIE                      |
| Catálogo (/api/modelos?marca=FORD)  | Available | GALAXIE presente                               |
| Código do conector                  | Available | src/connectors/circuitodeleiloes.py            |
| Spike de decisões                   | Available | _bmad-output/implementation-artifacts/sprint2-spike-circuitodeleiloes.md |

## Timeline of Events

| Time                       | Event                                              | Source              | Confidence |
| -------------------------- | -------------------------------------------------- | ------------------- | ---------- |
| 2026-06-10 (spike)         | Decisão: só `vendido` entra no sinal realizado     | spike doc           | Confirmed  |
| 2026-06-10T16:31:26Z       | Lote GALAXIE atualizado na fonte, status `aberto`  | API public_lots     | Confirmed  |
| 2026-06-10 (investigação)  | Busca local retorna 3 anúncios, sinal não considerado | /api/buscar      | Confirmed  |

## Confirmed Findings

### Finding 1: O lote existe na fonte com status "aberto"

**Evidence:** GET `public_lots?slug=eq.4-fordgalaxie-500-19681968` → `status: "aberto"`, `highest_bid_value: 70000.0`, `bid_count: 1`, `updated_at: 2026-06-10T16:31:26Z`.

**Detail:** R$ 70.000 é o lance ATUAL de um leilão em andamento — não é venda homologada.

### Finding 2: O conector exclui status ≠ "vendido" por design

**Evidence:** src/connectors/circuitodeleiloes.py:114 (`"status": "eq.vendido"` no filtro server-side) e :158 (guarda no parser); decisão documentada no spike e coberta por testes (tests/test_circuitodeleiloes_parser.py — `test_outros_status_nao_entram`, `test_fusca_aberto_nao_gera_sinal`).

### Finding 3: A busca do portal encontra o GALAXIE

**Evidence:** `/api/buscar?marca=FORD&modelo=GALAXIE` → 3 linhas (anúncios Ateliê do Carro), `sinal_leilao.considerado: false`. Catálogo contém GALAXIE para FORD.

## Deduced Conclusions

### Deduction 1: Não há defeito — é o comportamento especificado

**Based on:** Findings 1–3.

**Reasoning:** O lote está fora do sinal exatamente pela regra "preço realizado = vendido"; o restante do fluxo de busca funciona.

**Conclusion:** O sintoma reportado é consequência da decisão metodológica, não de bug.

## Hypothesized Paths

### Hypothesis 1 (premissa da usuária): defeito impede o carro de aparecer

**Status:** Refuted

**Theory:** Conector ou busca falham em trazer o lote.

**Resolution:** Findings 1–3 — o lote está `aberto` na fonte; a exclusão é regra documentada e testada; a busca retorna anúncios normalmente.

### Hypothesis 2: lacuna de produto — lotes abertos são invisíveis ao usuário

**Status:** Confirmed (como lacuna, não defeito)

**Theory:** Usuário que conhece um lote em leilão espera vê-lo na consulta; hoje não há sinal "leilão em andamento".

**Resolution:** Comportamento confirmado pela reprodução. Tratamento é decisão de produto (novo sinal/exibição), não correção.

## Missing Evidence

| Gap | Impact | How to Obtain |
| --- | ------ | ------------- |
| — (nenhum para o root cause) | | |

## Source Code Trace

| Element       | Detail                                                            |
| ------------- | ----------------------------------------------------------------- |
| Error origin  | Não é erro — filtro intencional em src/connectors/circuitodeleiloes.py:114 e :158 |
| Trigger       | Consulta a modelo cujo lote na fonte tem status ≠ "vendido"       |
| Condition     | Lote `aberto`/`condicional`/`retirado`/`encerrado` sem venda      |
| Related files | app.py (bloco sinal_leilao), tests/test_circuitodeleiloes_parser.py |

## Conclusion

**Confidence:** High

Root cause **Confirmed**: o lote GALAXIE está com leilão em andamento (`aberto`) na fonte e o sinal de leilão só considera vendas homologadas (`vendido`) — regra metodológica documentada no spike e coberta por testes. Não há defeito de código. Permanece a lacuna de produto (Hypothesis 2): lotes em andamento não são exibidos.

## Recommended Next Steps

### Fix direction

Decisão de produto, três opções:
1. **Exibir "leilão em andamento"** como informação separada (lance atual + link), claramente distinta de preço realizado — maior valor para o usuário, mantém pureza metodológica.
2. **Não exibir** e documentar no front ("vendas em leilão aparecem após homologação").
3. Incluir `condicional` com flag — NÃO recomendado (mistura lance não homologado com preço realizado).

### Diagnostic

Nenhum pendente — root cause confirmado.

## Reproduction Plan

1. `curl /api/buscar?marca=FORD&modelo=GALAXIE` → `sinal_leilao.considerado: false`.
2. Confirmar na fonte: `public_lots?slug=eq.4-fordgalaxie-500-19681968` → `status: "aberto"`.
3. Quando o lote for homologado (`vendido`), repetir (1): a venda passa a aparecer no sinal sem mudança de código.

## Side Findings

- A fixture de testes (tests/fixtures/circuitodeleiloes_sample.json) já capturou este mesmo lote com `status: "aberto"` e lance de R$ 70.000 em 2026-06-10 — o caso é coberto por teste (`test_fusca_aberto_nao_gera_sinal` cobre o padrão idêntico com o FUSCA).
- O lance subiu de 0 → 70.000 com `bid_count: 1` ao longo do dia: leilão ativo nesta data (transmissão Picelli divulgada no banner do circuitodeleiloes.com.br).
