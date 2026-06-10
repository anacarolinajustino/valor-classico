---
title: "Backlog de Enriquecimento de Produto"
status: draft
created: 2026-06-01
updated: 2026-06-01
---

# Backlog de Enriquecimento de Produto — Valor Clássico

Ideias de enriquecimento que melhoram precisão, UX ou qualidade dos dados, mas que estão fora do escopo do MVP imediato. Registradas para não perder contexto.

---

## ENR-01 — Anos de Fabricação por Modelo no Catálogo Canônico

**Contribuidor:** Vini  
**Data:** 2026-06-01  
**Prioridade sugerida:** Alta (impacto direto na UX de busca por ano)  
**Esforço estimado:** M (pesquisa + ingestão de dados + ajuste de API)

### Problema

Hoje a API `/api/anos` retorna todos os anos em que há *anúncios* para o modelo pesquisado. Isso não reflete os anos em que o carro foi de fato fabricado.

Exemplos de ruído que isso gera:

- VW Fusca fabricado no Brasil de 1959 a 1986 (e mais um lote em 1993-1996). Um anúncio com "ano 2005" é erro de cadastro — mas aparece na lista.
- VW Kombi encerrou produção em 2013. Anos posteriores a isso são inválidos.
- Fiat Marea foi fabricado de 1999 a 2007. Anos fora desse range são ruído.

### Proposta

Levantar o intervalo de anos de fabricação oficial (ano início, ano fim) por modelo e incorporá-lo ao catálogo canônico como **parâmetro de validação**.

**Comportamento desejado:**

```
GET /api/anos?marca=VOLKSWAGEN&modelo=FUSCA
→ Retorna apenas anos dentro do range de fabricação real do modelo
→ Filtra fora anos que só aparecem por erro de anúncio
```

### Implementação sugerida

#### Opção A — Enriquecer `vehicle_model` com range de fabricação

Adicionar ao modelo canônico:

| Campo | Tipo | Descrição |
|---|---|---|
| `ano_fabricacao_inicio` | integer | Primeiro ano de produção no Brasil |
| `ano_fabricacao_fim` | integer | Último ano de produção (null = ainda em produção) |
| `anos_especiais` | JSON | Ex: `[1993, 1994, 1995, 1996]` para o Fusca "relançamento" |
| `fabricacao_source` | string | Fonte consultada para validar o range |

#### Opção B — Tabela canônica de anos válidos por modelo

Criar `vehicle_model_year_canonical` separada dos anos vindos de anúncios:

- `model_id`
- `year`
- `is_validated` (true = confirmado por fonte confiável)
- `source` (ex: `wikipedia`, `denatran`, `fabricante`, `manual`)

Esta opção é mais flexível para modelos com gaps (ex: produção pausada por anos).

#### Fonte de dados sugerida

1. **Wikipedia** — artigos de cada modelo têm ficha técnica com anos de produção.
2. **Sites de fabricantes** (VW, Fiat, Ford, GM Brasil) — histórico de modelos.
3. **DENATRAN/SENATRAN** — base histórica de emplacamentos.
4. **Curation manual** — para os 30-50 modelos mais buscados, curação manual rápida.

#### Ajuste na API

```python
# Ao retornar anos disponíveis para seleção:
anos_anuncios = get_anos_from_ads(marca, modelo)
anos_validos = get_anos_fabricacao(marca, modelo)  # novo

if anos_validos:
    anos = [a for a in anos_anuncios if a in anos_validos]
else:
    anos = anos_anuncios  # fallback se não tiver dado de fabricação ainda
```

### Critério de pronto

- [ ] Range de fabricação levantado para os top 20 modelos mais buscados.
- [ ] Campo(s) de range adicionados ao catálogo canônico.
- [ ] API `/api/anos` filtra pela janela de fabricação quando disponível.
- [ ] Fallback gracioso quando o range não está no catálogo (usa anos de anúncios).
- [ ] Cobertura expandível incrementalmente (começa com os mais populares).

### Valor esperado

- Elimina anos absurdos da lista de seleção (melhora confiança do usuário).
- Reduz ruído nos cálculos de preço médio por ano.
- Melhora o score de confiança da estimativa (NFR6, NFR7).
- Cria base para validação automática de anúncios com ano inconsistente.

---

> *Adicione novas ideias de enriquecimento seguindo o padrão ENR-NN acima.*
