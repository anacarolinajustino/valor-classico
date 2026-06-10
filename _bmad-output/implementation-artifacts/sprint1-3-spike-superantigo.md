---
story_id: "sprint1.3"
story_key: "sprint1-3-spike-superantigo"
epic: "Sprint 1 — Portal First"
connector_id: "C05"
status: "done"
created: "2026-05-30"
updated: "2026-05-30"
---

# Story Sprint1.3: Spike + Conector — Super Antigo (C05)

Status: done

## Story

As a plataforma Valor Clássico,
I want implementar o conector Super Antigo com validação técnica ponta-a-ponta,
so that anúncios de carros antigos do site sejam ingeridos no pipeline canônico e reflitam no cálculo de valor.

## Contexto Crítico — Achado do Spike

> ⚠️ **MUDANÇA DE TÉCNICA em relação ao backlog original**
>
> O backlog registrava `requests + BeautifulSoup` para C05. O spike confirmou que
> **Super Antigo é um SPA Vite+React (CSR)**. O `requests` retorna apenas o shell HTML
> de ~7.5 KB sem nenhum dado de anúncio. Playwright (headless browser) é obrigatório.
>
> - `requests + BeautifulSoup`: ❌ HTML shell de 7588 bytes, sem dados
> - `playwright`: ✅ Página renderizada completa com listagens (confirmado via browser)
> - API `/api/*`: ❌ Explicitamente desativada no `robots.txt`
>
> Risco atualizado: **Médio** (Playwright adiciona complexidade de setup + stealth).

## Achados Técnicos do Spike

### Arquitetura do site
- Framework: **Vite + React SPA (Client-Side Rendering)**
- Evidência: `<style data-vite-theme="" data-inject-first="">` no shell; body vazio no HTML estático
- Shell HTML idêntico (7588 bytes) para qualquer URL — `/veiculos`, `/veiculos/carro/*`, home
- Sem `__NEXT_DATA__` ou equivalente SSR — dados 100% carregados via JS

### URLs relevantes

| Propósito | Padrão de URL |
|---|---|
| Listagem com filtros | `https://www.superantigo.com.br/veiculos?brand=volkswagen&vehicleType=car&page=1&limit=12` |
| Listagem por modelo | `https://www.superantigo.com.br/veiculos?brand=volkswagen&model=fusca&vehicleType=car&page=1&limit=12` |
| Detalhe de veículo | `https://www.superantigo.com.br/veiculos/carro/{marca}/{modelo}/{slug}-{ano}-{id}` |

**Dados disponíveis na URL de detalhe (slug estruturado):**
- Ex.: `/veiculos/carro/volkswagen/fusca/vw-fusca-cabriole-1500-1979-1979-443`
- Marca: `volkswagen` (segmento 3)
- Modelo: `fusca` (segmento 4)
- Ano: `1979` (penúltimo número no slug)
- ID: `443` (último número no slug)

### Campos disponíveis na listagem (via Playwright)

| Campo canônico | Disponível | Fonte |
|---|---|---|
| `titulo` | ✅ | Texto do card: "Volkswagen Fusca - VW FUSCA CABRIOLÉ 1500 (1979)" |
| `preco` | ✅ | Texto do card: "R$ 75.000" |
| `marca` | ✅ | URL slug + texto do card |
| `modelo` | ✅ | URL slug + texto do card |
| `ano` | ✅ | URL slug (penúltimo número) + texto do card |
| `versao` | ⚠️ parcial | Inferida do título (ex: "Motor 1500") |
| `url` | ✅ | href do card |
| `km` | ✅ | Texto do card (ex: "12.000 km") — campo extra, não no schema canônico atual |
| `localizacao` | ✅ | Texto do card (ex: "São Paulo - SP") |
| `fonte` | ✅ | Hardcoded `"superantigo"` |
| `data_coleta` | ✅ | Data de execução |

### Robots.txt (verificado 2026-05-30)
- `Allow: /veiculos/` → ✅ acesso explicitamente permitido
- `Disallow: /api/` → ❌ API interna bloqueada
- User-agent `*`: permite crawling das páginas de veículos

### Paginação
- URL param `?page=N` presente nos links HTML
- Links de paginação usam hash (`#`) → cliente JS controla navegação
- **Risco**: `page=2` pode não funcionar server-side via Playwright navigate — validar no teste
- Alternativa: usar `page` como query param e verificar se Playwright renderiza nova listagem

### Amostra de dados observados (listagem brand=volkswagen, 2026-05-30)
- 66 resultados disponíveis (carros VW)
- Exemplos de preços: R$ 19.900, R$ 21.900, R$ 24.900, R$ 25.000, R$ 26.000, R$ 28.000, R$ 29.900, R$ 30.000, R$ 40.000, R$ 42.990, R$ 45.000, R$ 75.000

## Acceptance Criteria

**AC1 — Coleta via Playwright**
**Given** Playwright instalado e o site acessível
**When** o conector executa busca por marca e modelo
**Then** anúncios são coletados com campos: titulo, preco, marca, modelo, ano, versao (quando inferível), url, fonte, data_coleta
**And** anúncios sem preço válido são descartados.

**AC2 — Normalização pelo pipeline canônico**
**Given** o conector retorna anúncios brutos
**When** o pipeline processa os registros
**Then** cada anúncio sai no schema `Anuncio` conforme `src/pipeline/schema.py`
**And** preços são normalizados de "R$ 75.000" → `75000.0`.

**AC3 — Teste de snapshot**
**Given** uma fixture HTML real da listagem Super Antigo salva em `tests/fixtures/superantigo_sample.html`
**When** `parsear_listagem_html()` processa o snapshot
**Then** pelo menos 1 anúncio é retornado com titulo, preco positivo, url e fonte="superantigo".

**AC4 — Integração no pipeline da API**
**Given** a API Flask em `app.py` recebe `?marca=VOLKSWAGEN&modelo=FUSCA`
**When** a busca é executada
**Then** resultados do Super Antigo aparecem na resposta consolidada junto aos do Maxicar
**And** a fonte "superantigo" aparece no campo de transparência.

**AC5 — Degradação graciosa**
**Given** o site Super Antigo está indisponível ou retorna erro
**When** o conector é invocado
**Then** ele lança exceção controlada sem derrubar os demais conectores
**And** o log registra falha com detalhes do erro.

## Tasks / Subtasks

- [ ] 1. Adicionar Playwright às dependências (AC1)
  - [ ] 1.1 Adicionar `playwright>=1.44` ao `requirements.txt`
  - [ ] 1.2 Verificar se `playwright install chromium` está no setup/README
  - [ ] 1.3 Validar que Playwright renderiza a listagem com dados reais

- [ ] 2. Criar fixture de snapshot (AC3)
  - [ ] 2.1 Usar Playwright para capturar HTML renderizado de busca real (ex: VW Fusca)
  - [ ] 2.2 Salvar em `tests/fixtures/superantigo_sample.html`
  - [ ] 2.3 Confirmar que o HTML contém pelo menos 3 cards com preço visível

- [ ] 3. Implementar conector `src/connectors/superantigo.py` (AC1, AC2)
  - [ ] 3.1 Criar função `buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]`
  - [ ] 3.2 Implementar `_abrir_navegador()` com Playwright + user-agent realista
  - [ ] 3.3 Implementar `_navegar_listagem(page, marca, modelo, num_pagina)` com URL de busca
  - [ ] 3.4 Implementar `parsear_listagem_html(html: str, data_coleta: str) -> list[Anuncio]` (função pura, testável sem browser)
  - [ ] 3.5 Implementar extração de preço a partir do texto do card
  - [ ] 3.6 Implementar extração de ano a partir da URL slug (regex `\d{4}` penúltimo grupo) ou texto do card
  - [ ] 3.7 Implementar paginação: testar se `?page=N` funciona; se não, tentar click no botão "próxima página"
  - [ ] 3.8 Tratar timeout do Playwright (30s por página) com log de warning e continuação
  - [ ] 3.9 Rate limit: sleep 2s entre páginas (browser é mais pesado que requests)
  - [ ] 3.10 Fechar contexto Playwright em bloco `finally`

- [ ] 4. Implementar testes de snapshot (AC3)
  - [ ] 4.1 Criar `tests/test_superantigo_parser.py` com mesmo padrão de `tests/test_maxicar_parser.py`
  - [ ] 4.2 Teste: `test_snapshot_retorna_anuncios` — pelo menos 1 anúncio
  - [ ] 4.3 Teste: `test_todos_anuncios_tem_titulo`
  - [ ] 4.4 Teste: `test_todos_anuncios_tem_preco_positivo`
  - [ ] 4.5 Teste: `test_todos_anuncios_tem_url`
  - [ ] 4.6 Teste: `test_todos_anuncios_tem_fonte_superantigo`
  - [ ] 4.7 Teste: `test_todos_anuncios_tem_ano_valido` (>= 1900 e <= 1999)
  - [ ] 4.8 Teste: `test_schema_valida_todos` — `validar(a)` retorna `True` para todos

- [ ] 5. Integrar na API Flask `app.py` (AC4)
  - [ ] 5.1 Importar `superantigo.buscar` no `app.py`
  - [ ] 5.2 No endpoint `/api/buscar`, chamar `superantigo.buscar` em paralelo com `maxicar.buscar` (ou sequencial por ora)
  - [ ] 5.3 Consolidar resultados: concatenar, deduplicar por URL, aplicar pipeline (normalizer, deduplicator, outlier_filter, stats)
  - [ ] 5.4 Incluir fonte "superantigo" na lista de fontes_utilizadas da resposta
  - [ ] 5.5 Se `superantigo.buscar` lançar exceção: logar, continuar com resultado parcial (AC5)

- [ ] 6. Atualizar documentação e sprint (AC1-AC5)
  - [ ] 6.1 Atualizar `README.md`: adicionar instrução `playwright install chromium`
  - [ ] 6.2 Criar findings doc `_bmad-output/implementation-artifacts/spike-superantigo-findings.md` com resumo técnico
  - [ ] 6.3 Atualizar `sprint-1-portal-first-plan.md`: marcar C05 como concluído

## Dev Notes

### Padrão do conector Maxicar — SEGUIR EXATAMENTE
O conector `src/connectors/maxicar.py` é o blueprint. Mantenha:
- Mesma assinatura pública: `buscar(marca, modelo, paginas) -> list[Anuncio]`
- Mesma separação `buscar()` (I/O) + `parsear_listagem_html()` (pura, testável)
- Mesma constante `FONTE = "superantigo"`
- Mesmo padrão de logging: `logger = logging.getLogger(__name__)` + `[superantigo]` prefix
- Mesmo tratamento de post-filtragem por marca e modelo após coleta

### Extração de ano a partir da URL slug
```
# Ex.: /veiculos/carro/volkswagen/fusca/fusca-1600-1975-1975-436
# O ano aparece duas vezes (ano_fab e ano_mod) e o ID é o último número
import re
def _extrair_ano_da_url(url: str) -> int | None:
    nums = re.findall(r'\b(1[89]\d{2}|20[0-2]\d)\b', url)
    return int(nums[-2]) if len(nums) >= 2 else (int(nums[-1]) if nums else None)
```

### Extração de preço do texto do card
O preço aparece como "R$ 75.000" ou "R$ 75.000,00" no texto do card.
Usar `normalizar_preco()` de `src/pipeline/normalizer.py` — já importado.

### Playwright — captura da fixture
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(user_agent="Mozilla/5.0 ...")
    page.goto("https://www.superantigo.com.br/veiculos?brand=volkswagen&model=fusca&vehicleType=car&page=1&limit=12")
    page.wait_for_selector("a[href*='/veiculos/carro/']", timeout=15000)
    html = page.content()
    browser.close()
```
Salvar `html` em `tests/fixtures/superantigo_sample.html`.

### Seletores CSS esperados (a validar no snapshot real)
O site usa Tailwind CSS com classes utilitárias (não semânticas). Preferir:
- `a[href*='/veiculos/carro/']` — cada card é um link para a página de detalhe
- Extrair texto do card completo e parsear com regex (mais resiliente que seletores CSS com Tailwind)

### Regressão — NÃO quebrar Maxicar
- `tests/test_maxicar_parser.py` deve continuar passando
- Não modificar `src/pipeline/schema.py`, `src/pipeline/normalizer.py` sem necessidade
- Se `app.py` for modificado, manter os 5 endpoints existentes funcionando

### Compliance
- `robots.txt` de 2026-05-30: `Allow: /veiculos/` ✅
- Rate limit recomendado: 2s entre páginas (browser é mais custoso)
- User-Agent realista obrigatório

### Project Structure Notes
```
src/connectors/superantigo.py       ← NOVO
tests/test_superantigo_parser.py    ← NOVO
tests/fixtures/superantigo_sample.html  ← NOVO (capturado via Playwright)
requirements.txt                    ← ATUALIZAR (adicionar playwright)
README.md                           ← ATUALIZAR (playwright install)
app.py                              ← ATUALIZAR (integrar conector)
_bmad-output/implementation-artifacts/spike-superantigo-findings.md ← NOVO
_bmad-output/implementation-artifacts/sprint-1-portal-first-plan.md ← ATUALIZAR
```

### References
- [Source: src/connectors/maxicar.py] — blueprint do conector
- [Source: tests/test_maxicar_parser.py] — padrão de testes de snapshot
- [Source: src/pipeline/schema.py] — contrato canônico `Anuncio`
- [Source: src/pipeline/normalizer.py] — `normalizar_preco()`, `normalizar_texto()`
- [Source: _bmad-output/planning-artifacts/briefs/brief-valor-classico-2026-05-29/connectors-backlog.md#C05]
- [Source: _bmad-output/planning-artifacts/briefs/brief-valor-classico-2026-05-29/source-governance.md] — C05 Tier 3 (peso 1.0x)

## Dev Agent Record

### Agent Model Used
Claude Sonnet 4.6 (GitHub Copilot)

### Debug Log References

### Completion Notes List
- 2026-05-30: Story criada com spike ponta-a-ponta concluído. Achado crítico: site é SPA CSR — Playwright obrigatório.
- 2026-05-30: Implementação concluída. 95/95 testes passando. Integrado no app.py com degradação graçiosa.

### File List
- `src/connectors/superantigo.py` NEW
- `tests/test_superantigo_parser.py` NEW
- `tests/fixtures/superantigo_sample.html` NEW
- `requirements.txt` UPDATED
- `app.py` UPDATED
- `README.md` UPDATED
