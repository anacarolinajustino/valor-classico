---
title: "Spike C02 — OLX Brasil"
status: done
created: 2026-06-14
connector_id: C02
---

# Spike C02 — OLX Brasil

## Conclusão

**Viável via Playwright + extração de `__NEXT_DATA__` JSON.**
`requests` é bloqueado pelo Cloudflare. Playwright é obrigatório.

## Achados técnicos

### Cloudflare

- `requests` com User-Agent Chrome/124 → **403 Cloudflare** em todas as URLs, incluindo `robots.txt`
- Playwright headless → **200 OK** (Cloudflare não bloqueia browser real)
- Sem necessidade de modo stealth por enquanto — Playwright puro passa

### robots.txt (via Playwright, 2026-06-14)

- `Disallow: /q/*` — caminho `/q/` proibido
- `/autos-e-pecas/` **NÃO está em Disallow** → ✅ permitido
- Usamos `/autos-e-pecas/carros-vans-e-utilitarios?q=fusca` — path diferente de `/q/`, **permitido**

### Estrutura HTML / `__NEXT_DATA__`

OLX Brasil usa Next.js SSR. Dados de listagem estão embutidos em:

```html
<script id="__NEXT_DATA__" type="application/json">{ ... }</script>
```

Caminho até os anúncios:

```
data["props"]["pageProps"]["ads"]          → list[dict]
data["props"]["pageProps"]["totalOfAds"]   → int (ex: 2856)
data["props"]["pageProps"]["pageIndex"]    → int (1-based)
data["props"]["pageProps"]["pageSize"]     → int (50)
```

### Campos do anúncio (confirmados em dados reais)

| Campo JSON | Exemplo real | Mapeamento canônico |
|---|---|---|
| `subject` | "Volkswagen Fusca 1300 1979" | `titulo` |
| `priceValue` | "R$ 25.000" | `preco` via `normalizar_preco()` |
| `url` | "https://sp.olx.com.br/vale-do-paraiba.../volkswagen-fusca-1300-1979-1432880566" | `url` |
| `properties[vehicle_brand]` | "Volkswagen" | `marca` |
| `properties[vehicle_model]` | "Volkswagen 1300" ⚠️ | ver nota abaixo |
| `properties[regdate]` | "1979" | `ano` via `int()` |
| `location` | "Jacareí - SP" | não mapeado no schema atual |

⚠️ `vehicle_model` contém "Marca Motor" (ex: "Volkswagen 1300") — não é o nome do modelo.
Usar `inferir_marca_modelo_ano(subject)` para extrair o modelo correto ("FUSCA").

### Outros campos disponíveis (não no schema canônico atual)

`mileage`, `fuel`, `gearbox`, `cartype`, `carcolor`, `location` — disponíveis se schema expandir.

### URLs confirmadas

| Propósito | URL validada |
|---|---|
| Busca por modelo | `https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q={modelo}` |
| Paginação | `?q={modelo}&o={page_number}` |
| Ingestão batch | `?q=carros+antigos` |

### Paginação

- Parâmetro: `?o=N` (N = número da página, 1-based)
- Validado: `?q=fusca&o=2` retorna `pageIndex=2`, 57 anúncios, primeiro ad diferente da p1
- `totalOfAds / pageSize = ceil(2856 / 50) = 58 páginas` para "fusca"

### Fixture

`tests/fixtures/olx_sample.json` — 5 anúncios reais de busca "fusca" (2026-06-14).

Estrutura da fixture:

```json
{
  "props": {
    "pageProps": {
      "ads": [ ... ],
      "pageIndex": 1,
      "totalOfAds": 2856,
      "pageSize": 50
    }
  }
}
```

## Decisões arquiteturais (Winston, 2026-06-14)

1. **Playwright obrigatório** — requests bloqueado por Cloudflare sem alternativa prática
2. **Parser via JSON** — `__NEXT_DATA__` elimina parsing HTML frágil; mais estável que seletores CSS
3. **Filtro de ano no conector** — `regdate` estruturado, filtrar antes de `upsert_anuncios()` para não poluir o banco
4. **`app.py` sem mudança** — arquitetura via banco SQLite já inclui OLX automaticamente após ingestão
5. **`requirements.txt` sem mudança** — Playwright já está instalado (SuperAntigo)
6. **Rate limit 2s** — mesmo do SuperAntigo (browser é custoso)

## Riscos residuais

1. Cloudflare pode intensificar detecção de bot → Playwright pode começar a falhar no futuro
2. `__NEXT_DATA__` estrutura pode mudar em deploy do OLX → monitorar `KeyError` em `ads`
3. `vehicle_model` é inútil como nome de modelo → dependemos de `inferir_marca_modelo_ano()` na coluna `subject`
