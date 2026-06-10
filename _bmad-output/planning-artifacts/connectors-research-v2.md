---
title: Backlog de Conectores v2 — Fontes de Scraping
status: draft
created: 2026-06-10
updated: 2026-06-10
---

# Backlog de Conectores v2 — Valor Clássico

> Resultado da pesquisa de descoberta de fontes (jun/2026). Substitui/expande o backlog v1.
> **Validado:** existência e natureza de cada fonte (pesquisa web).
> **Hipótese:** volume de anúncios, estrutura HTML, barreiras anti-bot — validar via spike técnico (Claude Code).
>
> **Nota de integração (2026-06-10):** as fontes novas desta pesquisa foram incorporadas ao
> [connectors-backlog.md](briefs/brief-valor-classico-2026-05-29/connectors-backlog.md) como C20–C29 e PAR-01.
> Este arquivo preserva a pesquisa original na íntegra.

---

## Estado atual

| Conector | Status |
|---|---|
| Maxicar | ✅ Ativo |
| Super Antigo | 🔄 Sprint 1 |
| Ateliê do Carro | 🔄 Sprint 1 |

---

## Tier 1 — Classificados de nicho (prioridade alta)

Mesma natureza do Maxicar: anúncios C2C, preço público, foco exclusivo em antigos. Baixo atrito de modelagem — entram direto na média principal.

| Fonte | URL | Tipo | Por que entra | Risco/observação |
|---|---|---|---|---|
| WebClássicos | webclassicos.com.br | Classificados C2C | No ar desde ~2011, classificados oficiais do Encontro Paulista de Autos Antigos | Site antigo — verificar qualidade do HTML |
| Classificados Clássicos | classificadosclassicos.com.br | Classificados C2C | Alcance nacional, presença forte (96K seguidores no Instagram) | Validar volume real no site vs. Instagram |
| Armazém do Vovô | armazemdovovo.com.br | Classificados C2C | Nicho puro: antigos, raros e de coleção | Volume desconhecido |

**Critério de pronto (spike):** conector retorna `marca`, `modelo`, `ano`, `preco`, `url_anuncio`, `data_coleta` para ≥ 90% dos anúncios listados.

---

## Tier 2 — Marketplaces generalistas + lojas de curadoria

### Marketplaces com filtro de clássicos

| Fonte | URL | Avaliação | Risco |
|---|---|---|---|
| SóCarrão | socarrao.com.br/carros-classicos | 🟢 Categoria dedicada, filtros estruturados (marca, ano, preço, câmbio) | Médio — site comercial, possível anti-bot |
| Webmotors | webmotors.com.br/carros-antigos | 🟡 Página existe mas volume baixo (~dezenas de anúncios) | Alto — anti-bot agressivo esperado |
| OLX / Mercado Livre (Coleções) | — | 🟡 Maior volume bruto do mercado (hipótese) | Alto — muito ruído (carro velho ≠ clássico) + anti-scraping. Avaliar API/parceria, não crawler |

### Lojas com curadoria

⚠️ **Decisão de governança:** preço de loja tende a viés para cima (curadoria + margem). Marcar com `tipo_fonte: loja` para permitir ponderação ou exibição segregada na transparência de amostra.

| Fonte | URL | Observação |
|---|---|---|
| Pastore Car Collection | pastore.com.br | Uma das maiores do segmento (Bento Gonçalves-RS); compra, venda e restauração |
| Brunelli | brunelli.com.br | Anúncios com alto padrão descritivo e visual |
| The Garage | thegarage.com.br | Grande estoque de clássicos (SP) |
| L'ART | lartbr.com.br | Acervo relevante, **porém muitos anúncios "preço sob consulta"** → baixo valor para scraping de preço |
| Clássicos do Vale | classicosdovale.com.br | Loja/intermediadora (Diamantina-MG), foco em colecionadores e clubes; volume provavelmente baixo |

---

## Tier 3 — Leilões (épico separado: "Preços Realizados")

**Não entram na média principal.** Semântica de preço diferente: lance inicial ≠ preço de mercado; arremate só vale após encerramento. Em contrapartida, **arremate é preço realizado** — mais confiável que "preço pedido" de classificado. Ninguém consolida isso para clássicos no Brasil → diferencial competitivo potencial.

| Fonte | URL | O que oferece |
|---|---|---|
| Circuito de Leilões | circuitodeleiloes.com.br | Especializado em antigos ("maior circuito de leilões de clássicos do Brasil"), lotes com checagem documental |
| Sodré Santoro | sodresantoro.com.br | Categoria dedicada de carros antigos, leilões online recorrentes |
| Picelli Leilões | picelli.com.br | Leilões de clássicos presencial + online, ~80 carros por evento |
| Freitas Leiloeiro | freitasleiloeiro.com.br | Leilões online recorrentes incluindo clássicos |
| Buaiz Leilões | buaizleiloes.com.br | Eventos pontuais de antigos (60+ lotes), lance inicial e atual públicos |

**Schema proposto (não validado):**

```yaml
fonte_leilao:
  lote_id: string
  marca: string
  modelo: string
  ano: int
  lance_inicial: decimal
  lance_final: decimal | null   # null enquanto leilão aberto
  status: aberto | arrematado | nao_vendido
  data_evento: date
  leiloeiro: string
```

**Cuidados específicos:**
- Leilões judiciais/de financeira misturam clássicos com carros comuns e sinistrados → filtro por ano + curadoria de categoria obrigatórios.
- Lotes "não vendidos" também são sinal de mercado (preço pedido rejeitado) — registrar.

---

## Ação paralela (não-scraping)

| Oportunidade | Contexto | Próximo passo |
|---|---|---|
| **TopClassic / FBVA** (topclassic.com.br) | Filiado à FBVA, credenciado SENATRAN para emissão de CVCOL/Placa Preta. Tem seção de classificados. | Vini sondar internamente na FBVA: parceria de dados oficial pode valer mais que crawler — e abre porta para credibilidade institucional do Valor Clássico ("dados reconhecidos pela federação") |

---

## Sequenciamento proposto

| Sprint | Escopo | Critério de sucesso |
|---|---|---|
| Sprint 1 (em andamento) | Super Antigo + Ateliê do Carro | 3 fontes ativas |
| Sprint 2 | WebClássicos + Classificados Clássicos + Armazém do Vovô (Tier 1) | 6 fontes ativas; amostra média por modelo popular ≥ 10 anúncios |
| Sprint 3 | SóCarrão + 1–2 lojas (Pastore, Brunelli) com flag `tipo_fonte: loja` | Governança de ponderação implementada |
| Backlog | Épico "Preços Realizados" (leilões) | Spec própria antes de implementar |
| Paralelo | Sondagem FBVA/TopClassic | Conversa exploratória agendada |

---

## Riscos transversais

1. **Anti-bot:** spike de fetch por fonte antes de comprometer sprint (1 dia/fonte, Claude Code).
2. **Termos de uso:** revisar ToS de cada fonte antes de ativar conector em produção — especialmente marketplaces grandes.
3. **Duplicidade entre fontes:** mesmo carro anunciado em 2+ sites infla a amostra → deduplicação por heurística (marca+modelo+ano+preço±5%+UF) precisa entrar na spec de catálogo.
4. **Anúncios "sob consulta":** descartar do cálculo, mas contar na transparência de amostra ("X anúncios encontrados, Y com preço").
