# Investigation: Ateliê do Carro — busca retorna vazio

## Hand-off Brief

1. **What happened.** `parsear_listagem_html` retorna 0 cards para qualquer página de listagem do Ateliê do Carro porque o seletor primário (`h2.entry-title`) e o fallback (`<article>`) não existem no tema customizado do site; o fallback final (`/carro/` links) existe mas é silenciado por um bug em `_card_de_link` que adiciona a URL ao set `seen` *antes* de obter o título, usando o image-link (texto vazio) para bloquear o title-link subsequente. Adicionalmente, o conector nunca é chamado pois não está registrado em `app.py`.
2. **Where the case stands.** Root cause identificada e confirmada via live parse. Três bugs isolados com patches prontos.
3. **What's needed next.** Aplicar os três patches e validar com live fetch + test suite.

## Case Info

| Field            | Value                                                                 |
| ---------------- | --------------------------------------------------------------------- |
| Ticket           | N/A                                                                   |
| Date opened      | 2026-05-30                                                            |
| Status           | Concluded                                                             |
| System           | macOS / Python 3.12 / BeautifulSoup + lxml                           |
| Evidence sources | Live fetch da página, código fonte `src/connectors/ateliedocarro.py`, `app.py` |

## Problem Statement

User reported: busca por Honda Odyssey (URL real confirmada em ateliedocarro.com.br) retornou vazio. User observou que o campo `Marca/Modelo` exibe `Honda/Odyssey` sem espaços ao redor da barra.

## Evidence Inventory

| Source                                        | Status    | Notes                                                                |
| --------------------------------------------- | --------- | -------------------------------------------------------------------- |
| Live fetch `/carro/honda-odyssey-lx-1995/...` | Available | `parsear_detalhe_html` funciona: extrai HONDA/ODYSSEY/R$59.900 ✓    |
| Live fetch `/carros-a-venda/`                 | Available | 0 `<h2>`, 0 `<article>`, 12 `div.car-loop`, 48 links `/carro/`      |
| `src/connectors/ateliedocarro.py`             | Available | `_card_de_link`: `seen.add` antes do título — bug confirmado         |
| `app.py`                                      | Available | Importa apenas `maxicar_buscar` e `superantigo_buscar` — ateliedocarro ausente |
| `resp.encoding` / `resp.apparent_encoding`    | Available | Server declara `ISO-8859-1`; chardet detecta `utf-8` (correto)      |

## Confirmed Findings

### Finding 1: `parsear_listagem_html` retorna 0 cards na listagem real

**Evidence:** live execute `2026-05-30` — `parsear_listagem_html(html_utf8, "2026-05-30")` → `0 cards`

**Detail:** O tema customizado do site não usa `<h2 class="entry-title">` nem `<article>`. O seletor primário e o fallback 1 ambos retornam listas vazias. O fallback 2 (qualquer link `/carro/`) seria ativado mas é neutralizado pelo Bug 2.

---

### Finding 2: Bug em `_card_de_link` — URL adicionada a `seen` antes do título (`ateliedocarro.py:238`)

**Evidence:** `src/connectors/ateliedocarro.py:238` — `seen.add(href)` ocorre antes de `titulo = link.get_text(strip=True)`

**Detail:** Cada card tem 4 links para a mesma URL: image-link (texto vazio) → title-link → "1972/72" → "Mais detalhes". O image-link é processado primeiro: URL adicionada a `seen`, título ausente, função retorna `None`. O title-link chega com `href in seen` → `return None`. Todos os 4 links do card são descartados.

---

### Finding 3: `ateliedocarro` não está registrado em `app.py`

**Evidence:** `app.py:31-32` — apenas `maxicar_buscar` e `superantigo_buscar` são importados.

**Detail:** Mesmo que os bugs 1 e 2 fossem corrigidos, o conector nunca seria invocado pela API web.

---

### Finding 4: `"Honda/Odyssey"` (sem espaços) é tratado corretamente

**Evidence:** live execute — `_split_marca_modelo("Honda/Odyssey")` → `("Honda", "Odyssey")`. `parsear_detalhe_html` retorna `marca='HONDA', modelo='ODYSSEY'`.

**Detail:** Não é um bug. `_split_marca_modelo` usa `.split("/")` que funciona com ou sem espaços. A preocupação do usuário é refutada pela evidência.

---

### Finding 5: Encoding — `apparent_encoding` correto para este site

**Evidence:** live check — `resp.encoding = 'ISO-8859-1'` (header), `resp.apparent_encoding = 'utf-8'` (chardet). `_requisitar` usa `apparent_encoding` → UTF-8 correto.

**Detail:** O servidor declara erroneamente ISO-8859-1 mas envia UTF-8. O uso de `apparent_encoding` (chardet) na atual implementação é o comportamento correto para este site.

## Deduced Conclusions

### Deduction 1: Fluxo completo de falha

**Based on:** Findings 1, 2, 3

**Reasoning:**
1. `buscar()` chama `parsear_listagem_html()` → retorna `[]` (Finding 1+2).
2. `urls_detalhe = []` → loop de detalhe não executa → `buscar()` retorna `[]`.
3. Mesmo que `buscar()` funcionasse, `app.py` não o chama (Finding 3).

**Conclusion:** A busca vazia tem duas causas independentes que se reforçam. Corrigir qualquer uma isoladamente não resolve a experiência do usuário.

## Hypothesized Paths

### Hypothesis 1: Honda Odyssey estaria nas primeiras 2 páginas da listagem

**Status:** Refuted

**Theory:** Com paginas=2 padrão, o carro seria encontrado.

**Resolution:** Sem evidência de que Honda Odyssey está nas páginas 1-2. Com 71 páginas e ~12 carros/página, carros raros provavelmente ficam em páginas mais antigas. Além disso, Finding 1+2 mostram que mesmo página 1 retorna 0 cards. Hipótese refutada.

## Fix Direction

| # | Bug | Mecanismo | Patch |
|---|-----|-----------|-------|
| 1 | `_card_de_link` polui `seen` antes do título | `seen.add(href)` movido para após extração bem-sucedida | `ateliedocarro.py` |
| 2 | Nenhum seletor bate no tema customizado | Adicionar `div.car-loop` como seletor de alta prioridade | `ateliedocarro.py` |
| 3 | Conector não registrado | Importar e incluir no `ThreadPoolExecutor` do `app.py` | `app.py` |

## Reproduction Plan

```python
import requests
from bs4 import BeautifulSoup
from src.connectors.ateliedocarro import parsear_listagem_html

r = requests.get("https://ateliedocarro.com.br/carros-a-venda/", ...)
html = r.content.decode("utf-8")
cards = parsear_listagem_html(html, "2026-05-30")
# Antes dos patches: len(cards) == 0
# Após os patches:   len(cards) == 12
```
