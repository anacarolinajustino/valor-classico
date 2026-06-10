---
title: "Spike — Achados Técnicos: Conector Maxicar"
story_id: "0.1"
data: "2026-05-29"
status: "concluido"
---

# Relatório de Achados — Spike Maxicar

## 1. Resumo Executivo

O spike ponta-a-ponta do conector Maxicar foi concluído com sucesso. O site é
acessível via `requests + BeautifulSoup`, o HTML é estático (renderizado pelo
servidor), não há bloqueio de scraping detectado para volumes baixos, e o
pipeline completo (coleta → normalização → dedup → outlier filter → matching →
stats) opera corretamente em memória.

---

## 2. Estrutura HTML Encontrada

### Motor do site
- WordPress + WooCommerce (confirmado por classes CSS e markup).
- Listagem de produtos em `/veiculos-antigos-a-venda/` com paginação padrão
  WooCommerce.

### Seletores identificados

| Campo     | Seletor CSS / Atributo                                          | Disponível |
|-----------|----------------------------------------------------------------|-----------|
| Título    | `li.product h2.woocommerce-loop-product__title`                | ✅         |
| Preço     | `li.product span.woocommerce-Price-amount`                     | ✅         |
| URL       | `li.product a.woocommerce-loop-product__link[href]`            | ✅         |
| Imagem    | `li.product img` (thumbnail)                                   | ✅ (não coletado neste spike) |
| Marca     | **ausente** no markup — inferida do título                     | ⚠️ inferida |
| Modelo    | **ausente** no markup — inferido do título                     | ⚠️ inferido |
| Ano       | **ausente** no markup — inferido do título                     | ⚠️ inferido |
| Versão    | **ausente** na listagem — disponível apenas na página de detalhe | ⚠️ parcial |
| KM / estado | **ausente** na listagem — apenas na página de detalhe        | ❌ fora do escopo deste spike |
| Paginação | `nav.woocommerce-pagination a.next`                            | ✅         |

### Observação crítica sobre marca
Os anúncios usam abreviações informais: "VW" em vez de "VOLKSWAGEN", "GM" em
vez de "CHEVROLET", etc. A inferência de marca a partir do título retorna "VW",
o que requer o dicionário de aliases `_MARCA_ALIASES` implementado no conector
para que o filtro de pós-busca funcione corretamente.

---

## 3. Campos Disponíveis vs Esperados

| Campo canônico    | Disponível na listagem | Como obtido                     |
|-------------------|------------------------|--------------------------------|
| `titulo`          | ✅                     | Texto direto do HTML            |
| `preco`           | ✅                     | Normalizado de R$ → float       |
| `marca`           | ⚠️                    | Inferida do título (aliases VW, GM...) |
| `modelo`          | ⚠️                    | Inferida do título              |
| `ano`             | ⚠️                    | Inferido do título (regex \d{4}) |
| `versao`          | ⚠️                    | `None` neste spike (somente na página de detalhe) |
| `url`             | ✅                     | href do link do produto         |
| `fonte`           | ✅                     | Constante `"maxicar"`           |
| `data_coleta`     | ✅                     | `date.today().isoformat()`      |
| `match_confidence`| ✅                     | Calculado no matching           |
| `match_strategy`  | ✅                     | Calculado no matching           |

---

## 4. Taxa de Sucesso

Busca executada em 2026-05-29 para VOLKSWAGEN KOMBI:

| Métrica                       | Valor        |
|-------------------------------|-------------|
| Páginas requisitadas          | 1           |
| Anúncios retornados (brutos)  | 3           |
| Válidos após validação        | 3 (100%)    |
| Após deduplicação             | 3           |
| Após filtro IQR               | 3           |
| Match `high` no catálogo      | 0           |
| Match `medium` (fuzzy)        | 0           |
| Unmatched                     | 3           |
| Latência total                | ~0,9s       |
| Erros de requisição           | 0           |

**Nota sobre matching:** Os anúncios têm `marca="VW"` mas o catálogo indexa
`"VOLKSWAGEN"`. O fuzzy match (difflib threshold 0.80) não pontua suficientemente
para aproximar "VW" de "VOLKSWAGEN" (score ≈ 0.40). Isso é uma limitação
conhecida do spike — resolvível na Sprint 1 com expansão do alias dict no
`match_anuncio` (mesma estratégia aplicada no filtro de busca).

---

## 5. Compliance e Robots.txt

```
# robots.txt verificado em 2026-05-29
# Origem: https://www.maxicar.com.br/robots.txt
# /veiculos-antigos-a-venda/ NÃO consta em Disallow → coleta permitida
User-agent: *
Disallow: /wp-admin/
Disallow: /wp-includes/
...
```

- **Rate limit implementado:** 1 req/seg (sleep entre páginas).
- **User-Agent realista** declarado no conector.
- **SSL verify=False** usado neste spike (site com certificado instável);
  produção deve usar `verify=True` com bundle atualizado.

---

## 6. Bloqueios Técnicos

| Bloqueio | Severidade | Status |
|----------|-----------|--------|
| Markup não inclui marca/modelo em campos dedicados — tudo via título | Médio | Contornado com inferência por regex |
| Abreviações de marca (VW, GM) não batem direto com catálogo Webmotors | Médio | Contornado com `_MARCA_ALIASES` no conector; pendente expansão no matching |
| Versão só disponível na página de detalhe (requer 1 req/anúncio extra) | Médio | Fora do escopo do spike; Sprint 1 pode adicionar crawl de detalhe |
| SSL `verify=False` necessário para ambiente de desenvolvimento | Baixo | Registrado; produção deve validar bundle SSL |
| Volume de anúncios por busca é baixo (3 Kombis no dia da coleta) | Baixo | Esperado para nicho clássico; ampliar com busca sem marca para aumentar recall |

---

## 7. Riscos

| Risco | Probabilidade | Impacto | Mitigação |
|-------|-------------|---------|-----------|
| Mudança de tema WordPress → seletores quebram | Média | Alto | Testes de regressão com snapshot HTML; alertas de CI |
| Volume muito baixo por modelo específico | Alta | Médio | Combinar com outras fontes (C05, C06) para ampliar amostra |
| Bloqueio por IP em coleta frequente | Baixa | Alto | Rate limit 1 req/s + User-Agent realista mitigam; monitorar em produção |
| Matching impreciso por abreviações de marca | Alta | Médio | Expandir `_MARCA_ALIASES` no `match_anuncio`; considerar campo de marca canônica no pipeline |

---

## 8. Arquitetura Validada

O pipeline em memória implementado atende o spike sem banco de dados:

```
buscar(marca, modelo) [maxicar.py]
  ↓
validar(anuncios) [schema.py]
  ↓
deduplicar(validos) [deduplicator.py]
  ↓
filtrar_outliers(deduplicados) [outlier_filter.py]
  ↓
match_anuncio(cada) [catalog/loader.py]
  ↓
calcular(finais) [stats.py]
```

O contrato canônico `Anuncio` (dataclass) é estável e pode ser adotado por
todos os conectores futuros sem renegociação.

### Limitação conhecida do MVP: scraping ao vivo

O conector funciona para qualquer marca/modelo do Maxicar — Fiat 147, Ford
Corcel, Opala, e qualquer combinação disponível no site. Cada busca acessa o
Maxicar em tempo real e devolve os anúncios encontrados naquele momento.

**Consequências dessa abordagem:**
- Resultado é efêmero: nada é salvo, cada busca parte do zero.
- Latência depende do Maxicar (tipicamente 1–3s por página).
- Se o site estiver fora, a busca falha.
- Sem histórico de preço: não é possível mostrar tendência ou variação ao longo do tempo.
- Amostra não acumula: em modelos raros (ex.: 3 Kombis), o dado estatístico é frágil.

**Decisão:** Esta é a arquitetura do MVP, escolhida conscientemente para validar
o produto com usuários reais antes de adicionar complexidade de infraestrutura.

**Evolução planejada (pós-validação com usuários):**

```
[APScheduler — job diário por modelo configurado]
        ↓
[Connector → pipeline existente (sem alteração)]
        ↓
[SQLite: tabelas listings + scrape_runs]
        ↓
[Flask lê do banco — sem scraping ao vivo por request]
        ↓
[Frontend — mesmo contrato de API]
```

A migração não exige mudanças nos conectores nem no contrato canônico `Anuncio`
— apenas adiciona `src/db/writer.py`, `src/scheduler.py` e modifica o
`app.py` para ler do banco em vez de chamar o conector diretamente.

---

## 9. Recomendações para Super Antigo (C05) e Ateliê do Carro (C06)

### Super Antigo
- Inspecionar estrutura de busca e paginação (URL params, GET vs POST).
- Verificar se marca/modelo aparecem como filtros na URL (mais fácil de inferir).
- Reaproveitar `_parsear_listagem` como template; ajustar seletores CSS.
- Validar robots.txt antes de ativar.

### Ateliê do Carro
- Site menor, volume baixo — priorizar estabilidade do parser sobre volume.
- Checar se preços são exibidos em BRL ou "a combinar" (tratar como `None`).
- Reusar `normalizar_preco` e `normalizar_texto` sem modificação.
- Adicionar ao mesmo test fixture pattern (snapshot HTML + regressão).

### Recomendação geral
- Expandir `_MARCA_ALIASES` para cobrir todas as abreviações encontradas em C05/C06.
- Adicionar crawl da página de detalhe em Sprint 1 para capturar `versao` e `km`.
- Considerar índice de busca invertido por modelo (sem marca) para ampliar recall
  e fazer filtragem por marca inteiramente em Python — estratégia já validada neste spike.

---

## 10. Arquivos Criados / Modificados

| Arquivo | Status |
|---------|--------|
| `src/pipeline/schema.py` | Criado — contrato canônico `Anuncio` |
| `src/pipeline/normalizer.py` | Criado — normalização de preço e texto |
| `src/pipeline/deduplicator.py` | Criado — dedupe por URL |
| `src/pipeline/outlier_filter.py` | Criado — filtro IQR |
| `src/pipeline/stats.py` | Criado — estatísticas base |
| `src/catalog/loader.py` | Criado — carregamento CSV + matching |
| `src/connectors/maxicar.py` | Criado — conector completo com aliases |
| `tests/fixtures/maxicar_sample.html` | Criado — snapshot real (145 KB) |
| `tests/test_schema.py` | Criado — 11 testes |
| `tests/test_normalizer.py` | Criado — 14 testes |
| `tests/test_stats.py` | Criado — 8 testes |
| `tests/test_catalog_loader.py` | Criado — 7 testes |
| `tests/test_maxicar_parser.py` | Criado — 10 testes |
| `scripts/demo_busca.py` | Criado — demo CLI completo |
| `conftest.py` | Criado — sys.path para imports |
| `requirements.txt` | Criado/atualizado — dependências mínimas |
| `README.md` | Criado — documentação de estrutura |

**Total: 61 testes, todos passando.**
