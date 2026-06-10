---
title: "Sprint 2 - Sinal Premium (C01 + C17)"
status: in-progress
created: 2026-06-10
updated: 2026-06-10
---

# Sprint 2 — C01 Mercado Livre + C17 Circuito de Leilões

## Escopo (ordem revisada do connectors-backlog)

1. C17 Circuito de Leilões — 🟡 backend concluído (2026-06-10)
2. C01 Mercado Livre API — 🔲 bloqueado: aguarda credenciais OAuth (app no DevCenter ML)

## Progresso

### 🟡 C17 Circuito de Leilões — backend concluído

- Spike: `sprint2-spike-circuitodeleiloes.md` — dados reais vêm da plataforma
  Picelli Leilões (Supabase REST, chave anon pública). Sem Playwright.
- Conector em `src/connectors/circuitodeleiloes.py`: somente lotes
  `status=vendido` com lance > 0 (preço realizado; `condicional` fica fora).
- Parse de título DETRAN (`parsear_titulo`): prefixos IMP/I, segmentos
  duplicados, colchetes com "/", marcas compostas, aliases (VW→VOLKSWAGEN,
  GM→CHEVROLET, MB→MERCEDES-BENZ).
- Testes: `tests/test_circuitodeleiloes_parser.py` — 29 testes (unitários +
  snapshot real `tests/fixtures/circuitodeleiloes_sample.json`). Suite total: 163 ✓.
- Integração `/api/buscar` (Story 5.1): bloco `sinal_leilao` separado dos
  anúncios, com `considerado`, `tipo_preco: realizado`, estatísticas e lista de
  vendas. Coleta em paralelo; falha do conector não derruba a resposta.
- Validado ao vivo: CHEVROLET OPALA → sinal com GM/OPALA DIPLOMATA 4.1 1988,
  R$ 72.000 realizado, separado dos 13 anúncios de preço pedido.

### Pendências do C17

- [x] Exibir `sinal_leilao` no front-end — card "Preço realizado em leilão" em
      `index.html` + `static/app.js` (`renderSinalLeilao`) + `static/styles.css`.
      Funciona também quando só o leilão tem dados (tabela de anúncios oculta).
      Verificado em browser real (Playwright, CHEVROLET OPALA) em 2026-06-10.
- [ ] Persistência separada do sinal (tabela própria, análoga a `precos_historico`)
      para curva histórica por modelo — AC "armazenados separadamente" só estará
      100% atendido com isso.
- [ ] Story 5.3 (calibração de pesos 1.5x) — após C18 ou volume maior.

### 🔲 C01 Mercado Livre — aguardando credenciais

- API de busca exige OAuth: registrar app em developers.mercadolivre.com.br
  e fornecer client_id/secret (vars de ambiente) antes de iniciar.

## Riscos

1. Rotação da chave anon da Picelli → conector degrada graciosamente e loga
   instrução de atualizar `CIRCUITODELEILOES_API_KEY`.
2. Amostra de leilão pequena por modelo → front-end deve sempre exibir amostra.
