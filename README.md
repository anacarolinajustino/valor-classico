# Valor Clássico — Referência de Preço para Carros Antigos

Portal web que estima o preço médio de mercado de carros antigos por marca, modelo e ano, com base em anúncios coletados de fontes especializadas.

## Estado atual (Sprint 1 — em andamento)

- **Portal web MVP** operacional com busca encadeada Marca → Modelo → Ano.
- **Conectores ativos:** Maxicar (C04) + Super Antigo (C05).
- **Pendente:** Atelie do Carro (C06).

## Estrutura

```
app.py                  # Servidor Flask — ponto de entrada principal
index.html              # Frontend do portal (SPA simples)
static/
  app.js                # Lógica de busca encadeada no front-end
  styles.css            # Estilos (tokens de marca: verde-lima, tipografia Teko/Playfair)
src/
  connectors/
    maxicar.py          # Conector Maxicar (WooCommerce scraper — requests + BS4)
    superantigo.py      # Conector Super Antigo (SPA React — Playwright headless)
  pipeline/
    schema.py           # Contrato canônico (dataclass Anuncio + validador)
    normalizer.py       # Normalização de preço e texto
    deduplicator.py     # Deduplicação por URL
    outlier_filter.py   # Filtro IQR de preços
    stats.py            # Cálculo estatístico (média, mediana, faixa)
  catalog/
    loader.py           # Carregamento do CSV catálogo em memória + matching
tests/
  fixtures/
    maxicar_sample.html    # Snapshot HTML real do Maxicar (regressão)
    superantigo_sample.html # Snapshot HTML real do Super Antigo (regressão)
  test_schema.py
  test_normalizer.py
  test_stats.py
  test_catalog_loader.py
  test_maxicar_parser.py
  test_superantigo_parser.py
scripts/
  demo_busca.py         # Demo CLI: --marca VOLKSWAGEN --modelo KOMBI
requirements.txt
```

## Pré-requisitos

- Python 3.10+
- Acesso à internet (para coletar do Maxicar)
- CSV do catálogo: `/Users/ana.justino/Downloads/base_dados_webmotors.csv`

## Instalação

```bash
pip install -r requirements.txt
python3 -m playwright install chromium   # necessário para o conector Super Antigo
```

## Como rodar o servidor web

```bash
python3 -m flask run --port 5001 --no-debugger --no-reload
```

Acesse em: `http://127.0.0.1:5001/`

## API

| Método | Endpoint | Parâmetros | Descrição |
|--------|----------|------------|-----------|
| GET | `/` | — | Serve o portal (`index.html`) |
| GET | `/api/marcas` | — | Lista todas as marcas do catálogo |
| GET | `/api/modelos` | `marca` | Lista modelos disponíveis para a marca |
| GET | `/api/anos` | `marca`, `modelo` | Lista anos disponíveis para marca+modelo |
| GET | `/api/buscar` | `marca`, `modelo`, `ano?`, `paginas?` (1–5, default 2) | Busca anúncios e retorna estatísticas por ano |

### Exemplo de resposta — `/api/buscar`

```json
{
  "consulta": { "marca": "VOLKSWAGEN", "modelo": "FUSCA", "ano": null },
  "linhas": [
    { "ano": 1982, "media": 38500, "mediana": 37000, "minimo": 28000, "maximo": 52000, "amostra": 4 }
  ],
  "total_amostra": 4,
  "fontes_ativas": ["Maxicar"]
}
```

## Como rodar os testes

```bash
pytest tests/ -v
```

## Demo CLI de busca

```bash
python scripts/demo_busca.py --marca VOLKSWAGEN --modelo KOMBI
python scripts/demo_busca.py --marca FORD --modelo MUSTANG
```

## Compliance

- `robots.txt` respeitado: apenas `/wp-admin/` e caminhos administrativos bloqueados.
- Rate limit: ≤ 1 requisição/segundo.
- User-Agent realista definido no conector.
- Fonte identificada como `maxicar` em todos os anúncios.

## Referências

- Achados técnicos do spike: [`_bmad-output/implementation-artifacts/spike-maxicar-findings.md`](_bmad-output/implementation-artifacts/spike-maxicar-findings.md)
- Planejamento de sprints: [`_bmad-output/implementation-artifacts/sprint-1-portal-first-plan.md`](_bmad-output/implementation-artifacts/sprint-1-portal-first-plan.md)
- Épicos e roadmap: [`_bmad-output/planning-artifacts/epics.md`](_bmad-output/planning-artifacts/epics.md)
