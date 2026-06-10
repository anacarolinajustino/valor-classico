---
title: "Governanca de Fontes - API e HTML"
status: draft
created: 2026-05-29
updated: 2026-05-29
---

# Governanca de Fontes do Valor Classico

## Decisao de arquitetura de coleta

Estrategia oficial: modelo hibrido.

1. Usar API oficial quando houver canal formal e permitido.
2. Usar conector HTML somente com compliance aprovado por fonte.
3. Proibir coleta sem checklist juridico e tecnico concluido.

## Matriz de decisao go/no-go por fonte

| Tipo de fonte | Metodo preferencial | Go | No-go |
|---|---|---|---|
| Marketplace | API oficial quando disponivel; HTML controlado como excecao | Termos de uso claros, robots permitido, rate limit definido, estabilidade minima do parser | Bloqueio tecnico persistente, proibicao explicita de coleta, risco juridico nao mitigado |
| Portal especializado | HTML via requests + parser simples | Estrutura estavel, volume relevante, custo operacional baixo | Layout instavel com alta quebra sem retorno de cobertura |
| Loja especializada | HTML em lote de baixa frequencia | Conteudo publico, parse simples, valor de referencia para nicho | Baixo valor estatistico e alto custo de manutencao |
| Leilao | HTML/API especifica com pipeline separado | Resultado de venda identificavel (preco realizado), dados minimamente estruturados | Dados sem confiabilidade de fechamento ou sem historico aproveitavel |
| Rede social (ex.: Facebook Marketplace) | Fora do MVP | Apenas com parceria, API oficial ou fornecedor homologado | Login obrigatorio + anti-bot agressivo sem canal formal |

## Checklist obrigatorio para ativar uma fonte

1. Compliance aprovado: ToS, robots e politica de acesso validados.
2. Tecnica aprovada: parser/API com taxa de sucesso minima definida.
3. Operacao aprovada: monitoramento de latencia, falha e volume ativo.
4. Qualidade aprovada: dedupe e outlier funcionando para a fonte.
5. Transparencia aprovada: fonte aparece no detalhamento de amostra ao usuario.

## Politica de rollback por fonte

1. Queda de sucesso por 3 ciclos consecutivos abaixo do limiar.
2. Mudanca juridica que invalide coleta.
3. Custo operacional acima do limite semanal definido.

Quando qualquer regra acima ocorrer, o conector e desativado por feature flag e a consulta continua com degradacao graciosa.

## Arquitetura de confianca por tier de fonte

Fontes nao sao equivalentes metodologicamente. A distinção central é entre **preço pedido** (anúncios) e **preço realizado** (leilões com venda confirmada). O tier define o peso relativo de cada fonte na média ponderada.

| Tier | Tipo | Fontes | Peso na média | Justificativa |
|---|---|---|---|---|
| 1 — Alta confiança | Preço realizado | Circuito de Leilões (C17), CARDE / Magalhães Gouvêa (C18) | 1.5x | Preço de fechamento de venda — dado mais confiável disponível no mercado brasileiro |
| 2 — Média confiança | Preço praticado por especialista | Brunelli (C13), L'ART (C12), Classic Car BR (C14), JS Autos (C15), Franz (C16), Ateliê do Carro (C06) | 1.2x | Fichas técnicas com preços de loja especializada — curadoria humana, menos ruído |
| 3 — Volume | Preço pedido por particular ou portal | Mercado Livre (C01), Maxicar (C04), Super Antigo (C05), Netmotors (C03), Retroauto (C10) | 1.0x | Base de volume; ruído controlado via outlier filter |
| 3 — Volume (alto ruído) | Preço pedido em marketplace generalista | OLX (C02), iCarros (C07) | 0.8x | Alta dispersão entre veículos de diferentes estados de conservação |

Implementação do peso no pipeline: campo `fonte_tier` no schema canônico (INF-01), aplicado na agregação estatística (INF-03).

## Ordem executiva recomendada

1. Sprint 0: pre-requisitos INF-01 a INF-05.
2. Sprint 1 (portal-first): C04, C05, C06.
3. Sprint 2: C01 (ML API — zero fricção) + **C17 (Circuito de Leilões — dado diferenciado imediato)**.
4. Sprint 3: C02, C03, C09, C10, C11.
5. Sprint 4: C07, C08 e lojas especializadas C12-C16.
6. Sprint 5: C18 + recalibração do score com pesos de tier.

Justificativa da mudança no Sprint 2: leilões fornecem preço realizado, que transforma o Valor Clássico de agregador de anúncios em referência de mercado. Referência metodológica: Hagerty Price Guide (EUA) usa preço realizado em leilão como âncora primária.
