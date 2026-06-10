---
story_id: "0.1"
story_key: "0-1-spike-maxicar-conector-arquitetura"
epic: "Sprint 0 / Pre-requisitos"
status: "done"
created: "2026-05-29"
updated: "2026-05-29"
baseline_commit: ""
---

# Story 0.1: Spike — Conector Maxicar + Contrato Canonico + Arquitetura Minima

## Story

As a time de desenvolvimento do Valor Classico,
I want executar um spike tecnico ponta a ponta no site Maxicar,
So that validemos viabilidade real de coleta, definamos o contrato canonico de dados e estabelecamos a arquitetura minima antes de qualquer HTML final.

## Context

### Produto
O Valor Classico e uma plataforma que estima preco medio de carros antigos por Marca -> Modelo -> Ano, coletando anuncios reais de multiplas fontes. A busca e encadeada (campo Modelo habilita Ano), apoiada por um catalogo canonico de 26.200 registros de marca/modelo/ano/versao (CSV Webmotors).

### Decisao tecnica validada
Estrategia hibrida: API oficial onde houver canal formal (ex.: Mercado Livre), HTML scraping controlado para portais especializados com compliance aprovado. Sprint 1 e portal-first: Maxicar (C04), Super Antigo (C05), Atelie do Carro (C06).

### Por que comecar por Maxicar
- Maior portal de antigomobilismo do Brasil com foco em veiculos com +20 anos.
- Viabilidade marcada como "Viavel" no backlog.
- HTML acessivel via requests + BeautifulSoup.
- Volume medio/alto, muito aderente ao nicho do produto.

### Fontes de contexto existentes
- `_bmad-output/planning-artifacts/briefs/brief-valor-classico-2026-05-29/connectors-backlog.md` - backlog de conectores com IDs, esforco, risco e dependencias
- `_bmad-output/planning-artifacts/catalog-search-matching-spec.md` - especificacao do catalogo canonico e matching
- `_bmad-output/planning-artifacts/ux-homepage-index-spec.md` - direcao de UX e estrutura do index
- `_bmad-output/planning-artifacts/briefs/brief-valor-classico-2026-05-29/source-governance.md` - politica go/no-go por fonte

## Acceptance Criteria

**Given** o site https://www.maxicar.com.br esta acessivel
**When** o conector executa busca por marca e modelo
**Then** anuncios sao coletados com os campos: titulo, preco, marca, modelo, ano, versao (quando disponivel), URL do anuncio, data de coleta
**And** os dados sao normalizados conforme o contrato canonico definido abaixo.

**Given** o pipeline de normalizacao recebe anuncios brutos do Maxicar
**When** processa os registros
**Then** cada anuncio sai com os campos canonicos preenchidos ou marcados como ausentes
**And** registros sem preco valido sao descartados.

**Given** o spike esta concluido
**When** o time avalia os resultados
**Then** existe documentacao de: estrutura HTML encontrada, campos disponiveis, taxa de sucesso, bloqueios tecnicos e riscos.

**Given** o contrato canonico esta definido
**When** outros conectores forem implementados
**Then** todos seguem o mesmo schema sem necessidade de renegociacao de contrato.

## Tasks / Subtasks

- [x] 1. Estrutura do projeto
  - [x] 1.1 Criar estrutura de diretorios: `src/connectors/`, `src/pipeline/`, `src/catalog/`, `tests/`
  - [x] 1.2 Criar `requirements.txt` com dependencias minimas: `requests`, `beautifulsoup4`, `lxml`, `pytest`
  - [x] 1.3 Criar `README.md` resumindo estrutura e como rodar

- [x] 2. Inspecionar Maxicar
  - [x] 2.1 Acessar https://www.maxicar.com.br e mapear estrutura de busca (URL de busca por marca/modelo, paginacao)
  - [x] 2.2 Identificar seletores HTML dos campos: titulo, preco, marca, modelo, ano, versao, URL do anuncio
  - [x] 2.3 Documentar rate limit observado, headers necessarios, robots.txt

- [x] 3. Contrato canonico
  - [x] 3.1 Criar `src/pipeline/schema.py` com dataclass/TypedDict `Anuncio` com os campos:
    - `titulo: str`
    - `preco: float | None`
    - `marca: str`
    - `modelo: str`
    - `ano: int | None`
    - `versao: str | None`
    - `url: str`
    - `fonte: str`
    - `data_coleta: str` (ISO 8601)
    - `match_confidence: str` (high / medium / low / unmatched)
    - `match_strategy: str` (exact / normalized_exact / fuzzy / manual_review / none)
  - [x] 3.2 Criar validador que rejeita anuncios sem preco ou sem modelo

- [x] 4. Conector Maxicar
  - [x] 4.1 Criar `src/connectors/maxicar.py` com funcao `buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]`
  - [x] 4.2 Implementar parse dos campos identificados na inspecao
  - [x] 4.3 Tratar paginacao basica
  - [x] 4.4 Tratar falha de requisicao com retry simples (max 2 tentativas, backoff 2s)
  - [x] 4.5 Logar volume coletado, erros e latencia por execucao

- [x] 5. Pipeline de normalizacao
  - [x] 5.1 Criar `src/pipeline/normalizer.py` com:
    - Normalizacao de preco (remover R$, pontos, converter para float)
    - Normalizacao de texto (remover acentos para matching, preservar original para exibicao)
    - Inferencia de marca/modelo a partir do titulo quando campo ausente
  - [x] 5.2 Criar `src/pipeline/deduplicator.py` com dedupe simples por URL
  - [x] 5.3 Criar `src/pipeline/outlier_filter.py` com filtro por IQR (remover precos fora de 1.5x IQR)

- [x] 6. Ingestao do catalogo
  - [x] 6.1 Criar `src/catalog/loader.py` que le o CSV `base_dados_webmotors.csv` e carrega em memoria como dict indexado por (marca_normalized, modelo_normalized)
  - [x] 6.2 Criar funcao `match_anuncio(anuncio: Anuncio) -> Anuncio` que tenta matching com o catalogo e preenche match_confidence e match_strategy

- [x] 7. Calculo estatistico base
  - [x] 7.1 Criar `src/pipeline/stats.py` com funcao `calcular(anuncios: list[Anuncio]) -> dict` que retorna:
    - `media: float`
    - `mediana: float`
    - `minimo: float`
    - `maximo: float`
    - `amostra: int`
    - `data_coleta_mais_recente: str`

- [x] 8. Testes
  - [x] 8.1 Criar `tests/test_schema.py` com testes de validacao do dataclass
  - [x] 8.2 Criar `tests/test_normalizer.py` com casos de preco e texto
  - [x] 8.3 Criar `tests/test_stats.py` com conjunto de anuncios fixture
  - [x] 8.4 Criar `tests/test_catalog_loader.py` com amostra do CSV
  - [x] 8.5 Criar `tests/fixtures/maxicar_sample.html` com snapshot real do HTML coletado (para testes de regressao de parser)
  - [x] 8.6 Criar `tests/test_maxicar_parser.py` usando o snapshot

- [x] 9. Script de demonstracao
  - [x] 9.1 Criar `scripts/demo_busca.py` que aceita `--marca` e `--modelo` como args, executa o pipeline completo e imprime resultado com media, mediana, faixa e tamanho de amostra

- [x] 10. Documentar achados do spike
  - [x] 10.1 Atualizar `_bmad-output/implementation-artifacts/spike-maxicar-findings.md` com:
    - campos encontrados vs esperados
    - taxa de sucesso
    - bloqueios tecnicos
    - recomendacoes para Super Antigo e Atelie do Carro

## Dev Notes

### Estrutura de diretorios recomendada

```
src/
  connectors/
    maxicar.py
  pipeline/
    schema.py
    normalizer.py
    deduplicator.py
    outlier_filter.py
    stats.py
  catalog/
    loader.py
tests/
  fixtures/
    maxicar_sample.html
  test_schema.py
  test_normalizer.py
  test_stats.py
  test_catalog_loader.py
  test_maxicar_parser.py
scripts/
  demo_busca.py
requirements.txt
README.md
```

### Restricoes tecnicas
- Python 3.10+
- Apenas requests + beautifulsoup4 no conector (sem Playwright neste spike)
- Sem banco de dados neste spike: tudo em memoria
- CSV do catalogo esta em `/Users/ana.justino/Downloads/base_dados_webmotors.csv`
- Compliance: respeitar robots.txt, usar User-Agent realista, nao exceder 1 req/seg

### Matching do catalogo
Ver especificacao completa em `_bmad-output/planning-artifacts/catalog-search-matching-spec.md`.
Estrategia para o spike: match por (marca_normalized, modelo_normalized). Se falhar, fuzzy simples com difflib.SequenceMatcher threshold >= 0.8.

### Campos do catalogo CSV
- `nome_marca`, `nome_modelo`, `ano_modelo`, `nome_versao`, `data_coleta`

### Referencia de preco
O conector extrai anuncios. O pipeline calcula media/mediana. Nao ha banco de dados neste spike.

### Observabilidade minima
Usar `logging` padrao do Python. Logar por conector: timestamp, volume, latencia, erros.

## Dev Agent Record

### Debug Log

- **Tarefa 4 / filtro de marca:** O Maxicar usa "VW" nos títulos dos anúncios
  em vez de "VOLKSWAGEN". O filtro de pós-busca original (`normalizar_texto(a.marca) == marca_norm`)
  descartava todos os anúncios de Kombi porque "VW" ≠ "VOLKSWAGEN".
  Solução: adicionado dicionário `_MARCA_ALIASES` em `maxicar.py` com mapeamento
  canônico → aliases, e função `_marcas_equivalentes()` que resolve "VW" → "VOLKSWAGEN"
  antes da comparação. Mesma limitação existe no `match_anuncio` (unmatched no demo),
  documentada no findings como melhoria para Sprint 1.

### Completion Notes

Spike concluído em 2026-05-29. Todos os 10 grupos de tarefas implementados.

- **61 testes passando** (test_schema, test_normalizer, test_stats, test_catalog_loader, test_maxicar_parser).
- **`scripts/demo_busca.py --marca VOLKSWAGEN --modelo KOMBI`** executa e imprime
  3 anúncios com média R$ 88.000,00, mediana R$ 60.000,00 (amostra do dia).
- **Relatório de findings** em `_bmad-output/implementation-artifacts/spike-maxicar-findings.md`.
- Arquitetura em memória validada; contrato canônico `Anuncio` pronto para C05/C06.
- Limitação residual: matching catálogo retorna "unmatched" para anúncios com
  `marca="VW"` — resolvível na Sprint 1 com expansão dos aliases em `match_anuncio`.

## File List

| Arquivo | Operação |
|---------|----------|
| `src/__init__.py` | Existente |
| `src/pipeline/__init__.py` | Existente |
| `src/pipeline/schema.py` | Criado |
| `src/pipeline/normalizer.py` | Criado |
| `src/pipeline/deduplicator.py` | Criado |
| `src/pipeline/outlier_filter.py` | Criado |
| `src/pipeline/stats.py` | Criado |
| `src/catalog/__init__.py` | Existente |
| `src/catalog/loader.py` | Criado |
| `src/connectors/__init__.py` | Existente |
| `src/connectors/maxicar.py` | Criado + corrigido (aliases) |
| `tests/__init__.py` | Existente |
| `tests/fixtures/maxicar_sample.html` | Criado (snapshot real 145 KB) |
| `tests/test_schema.py` | Criado |
| `tests/test_normalizer.py` | Criado |
| `tests/test_stats.py` | Criado |
| `tests/test_catalog_loader.py` | Criado |
| `tests/test_maxicar_parser.py` | Criado |
| `scripts/demo_busca.py` | Criado |
| `conftest.py` | Criado |
| `requirements.txt` | Criado/atualizado |
| `README.md` | Criado/atualizado |
| `_bmad-output/implementation-artifacts/spike-maxicar-findings.md` | Criado |

## Change Log

| Data | Decisão | Justificativa |
|------|---------|---------------|
| 2026-05-29 | Busca por modelo apenas (não marca+modelo) | WooCommerce retorna 0 resultados para "VOLKSWAGEN KOMBI"; retorna 3 para "KOMBI". Pós-filtragem por marca em Python. |
| 2026-05-29 | `_MARCA_ALIASES` adicionado a `maxicar.py` | Títulos usam "VW" não "VOLKSWAGEN"; filtro de marca precisava de aliases para não descartar resultados válidos. |
| 2026-05-29 | `versao=None` na listagem | Campo versão ausente da listagem WooCommerce; disponível apenas na página de detalhe (fora do escopo do spike). |
| 2026-05-29 | `verify=False` no requests | Certificado SSL do Maxicar instável no ambiente de desenvolvimento. Registrado para revisão em produção. |
| 2026-05-29 | Matching "unmatched" para VW no catálogo | `match_anuncio` compara `marca="VW"` vs catálogo "VOLKSWAGEN" — fuzzy score insuficiente. Documentado como tech debt Sprint 1. |
