# Investigation: Inconsistência de padrão e presença do Picelli na busca

## Hand-off Brief

1. **What happened.** Confirmed in code that Picelli (Circuito de Leilões) is returned in `sinal_leilao` and intentionally excluded from `linhas` table computation in the main response path.
2. **Where the case stands.** Active; strongest current finding explains why Picelli does not appear in the table, and there is a likely consistency gap because `ano` filtering is applied to classifieds but not to auction sales.
3. **What's needed next.** Validate with runtime evidence (API responses for the reported queries) whether `sinal_leilao.vendas` includes years outside requested `ano`, then trace to root-cause confidence.

## Case Info

| Field            | Value                                                                      |
| ---------------- | -------------------------------------------------------------------------- |
| Ticket           | N/A                                                       |
| Date opened      | 2026-06-12                                                                     |
| Status           | Active                                                                     |
| System           | macOS, local Flask app (`app.py`)                                |
| Evidence sources | User report, source code (`app.py`, connector docs), existing investigation artifacts        |

## Problem Statement

Usuária reportou inconsistência: ao buscar "wolksvagen ford 1990", o resultado da fonte Picelli veio fora do padrão; ao buscar "wwosksvagen ford" sem ano, Picelli não apareceu na tabela. Premissa inicial: falta de padrão e consistência na forma como Picelli participa dos resultados.

## Evidence Inventory

| Source   | Status                          | Notes     |
| -------- | ------------------------------- | --------- |
| User report | Available | Duas buscas com comportamento inconsistente descrito em linguagem natural. |
| API behavior (runtime) | Partial | Ainda não coletado nesta investigação; necessário para confirmar efeito observado ponta a ponta. |
| Source code routing (`app.py`) | Available | Picelli separado em `sinal_leilao`; cálculo de `linhas` usa só anúncios classificados. |
| Connector implementation (`circuitodeleiloes`) | Available | Fonte Picelli mapeada via conector Circuito de Leilões. |

## Investigation Backlog

| # | Path to Explore | Priority              | Status                                | Notes     |
| - | --------------- | --------------------- | ------------------------------------- | --------- |
| 1 | Reproduzir chamadas API com e sem `ano` para comparar `linhas` vs `sinal_leilao` | High | Open | Confirmar discrepância reportada com payload real. |
| 2 | Verificar se `ano_filtro` deve aplicar também em `vendas_leilao` por regra de produto | High | Open | Pode ser causa do “fora do padrão” para busca com ano. |
| 3 | Revisar renderização frontend da tabela para entender expectativa de inclusão de Picelli | Medium | Open | Determinar se ausência na tabela é bug ou comportamento intencional de UX. |

## Timeline of Events

| Time        | Event               | Source                | Confidence            |
| ----------- | ------------------- | --------------------- | --------------------- |
| 2026-06-12 | Usuária reporta inconsistência em duas consultas | Prompt da investigação | Confirmed |
| 2026-06-12 | Código confirma separação de Picelli em `sinal_leilao` fora de `linhas` | app.py:163-176, app.py:233-298 | Confirmed |
| 2026-06-12 | Código confirma filtro de ano aplicado a anúncios antes da tabela | app.py:205-206 | Confirmed |

## Confirmed Findings

### Finding 1: Picelli não entra na tabela `linhas`

**Evidence:** `app.py:163-176`, `app.py:233-298`

**Detail:** A coleta de Circuito de Leilões (Picelli) é armazenada em `vendas_leilao` e serializada em `sinal_leilao`; a tabela `linhas` é montada a partir de `anuncios` (classificados), sem incluir `vendas_leilao`.

### Finding 2: Filtro por ano não é aplicado explicitamente ao bloco de leilão

**Evidence:** `app.py:205-206`, `app.py:233-286`

**Detail:** O `ano_filtro` é aplicado apenas em `anuncios`; o bloco `sinal_leilao` é calculado sobre `vendas_validas` derivadas de `vendas_leilao` sem filtro por `ano_filtro` no fluxo exibido.

## Deduced Conclusions

### Deduction 1: Ausência de Picelli na tabela pode ser comportamento por desenho atual

**Based on:** Finding 1

**Reasoning:** Se `linhas` é derivada somente de anúncios e Picelli é emitido em `sinal_leilao`, então Picelli não aparecerá na tabela mesmo quando houver dados de leilão.

**Conclusion:** A parte “Picelli não apareceu na tabela” é consistente com implementação atual e pode não ser defeito técnico isolado.

## Hypothesized Paths

### Hypothesis 1: Inconsistência percebida vem de política diferente entre tabela e sinal de leilão

**Status:** Open

**Theory:** A UI/usuária espera uniformidade entre filtros e blocos, mas o backend aplica semânticas diferentes (anúncios vs preço realizado).

**Supporting indicators:** Encontrada separação explícita no fluxo e comentários de design sobre não misturar preços.

**Would confirm:** Respostas de `/api/buscar` mostrando `linhas` aderente ao ano e `sinal_leilao.vendas` com anos diferentes na mesma consulta com `ano`.

**Would refute:** Respostas reais mostram `sinal_leilao` já filtrado por ano e coerente com expectativa de UX definida.

**Resolution:** Open.

## Missing Evidence

| Gap              | Impact                               | How to Obtain   |
| ---------------- | ------------------------------------ | --------------- |
| Payload real das duas buscas reportadas | Confirma se o comportamento observado bate com o fluxo de código | Executar API local com os mesmos parâmetros da usuária e registrar resposta |
| Regra de produto para exibição de Picelli na tabela | Define se ausência na tabela é bug ou requisito | Revisar artefatos de UX/planejamento e validação com produto |

## Source Code Trace

| Element       | Detail                                      |
| ------------- | ------------------------------------------- |
| Error origin  | `app.py:205-206` (filtro de ano só em anúncios), `app.py:233-286` (`sinal_leilao`) |
| Trigger       | Requisição GET em `/api/buscar` com `marca`, `modelo` e opcional `ano` |
| Condition     | Dados de leilão existentes em `vendas_leilao` e construção separada de resposta |
| Related files | `app.py`, `src/connectors/circuitodeleiloes.py`, `index.html` |

## Conclusion

**Confidence:** Medium

Está confirmado que a arquitetura atual separa Picelli da tabela e que o filtro por ano atinge anúncios, não explicitamente o bloco de leilão. A causa exata da percepção de “fora do padrão” ainda requer validação com payload real das buscas relatadas para elevar confiança para High.

## Recommended Next Steps

### Fix direction

Se confirmado em runtime, alinhar política de filtro (`ano`) entre `linhas` e `sinal_leilao` ou explicitar visualmente semântica distinta para evitar percepção de inconsistência.

### Diagnostic

Executar reproduções controladas de `/api/buscar` com pares de entrada reportados e comparar `linhas`, `sinal_leilao.amostra` e anos em `sinal_leilao.vendas`.

## Reproduction Plan

1. Rodar app local e chamar `/api/buscar?marca=wolksvagen&modelo=ford&ano=1990` (ou equivalentes do front).
2. Chamar `/api/buscar?marca=wwosksvagen&modelo=ford` sem ano.
3. Registrar diferenças de presença em `linhas` e `sinal_leilao`, incluindo anos retornados.

## Side Findings

Tangential observations surfaced during the investigation, evidence-graded, with citation when applicable.

- O conector Picelli é implementado no módulo Circuito de Leilões e já foi alvo de investigação anterior no repositório (`_bmad-output/implementation-artifacts/investigations/galaxie-sinal-leilao-investigation.md`).

## Follow-up: {date}

### New Evidence

### Additional Findings

### Updated Hypotheses

### Backlog Changes

### Updated Conclusion
