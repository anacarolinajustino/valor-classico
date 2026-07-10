# Valor Clássico — Referência de Preço para Carros Antigos

Portal web que estima o preço médio de mercado de carros antigos por marca, modelo e ano, com
base em anúncios coletados de fontes especializadas.

## Estado atual (2026-07)

- **Operação 100% local.** O projeto não é mais implantado em nenhum serviço de nuvem — site,
  painel admin e coleta rodam no mesmo processo Flask, na máquina do usuário.
- **31 conectores** cadastrados em `CONNECTOR_MODULES` (`app.py`), a maioria via requisições
  HTTP + BeautifulSoup, alguns via Playwright (sites SPA/JS: `superantigo`, `socarrao`,
  `mercadolivre`, `reginaldodecampinas`, `ggworld`, entre outros — usam `src/connectors/_browser.py`).
- **Persistência em PostgreSQL** (não SQLite) — banco `valorclassicodb` rodando localmente.

## Estrutura

```
app.py                    # Servidor Flask — site público + painel admin + disparo de coleta
index.html, resultado.html, admin.html, anuncios.html
static/
  app.js, resultado.js, admin.js, anuncios.js, styles.css
src/
  connectors/              # Um módulo por fonte; cada um expõe coletar_completo()
    _browser.py            # Helper Playwright compartilhado (contexto/stealth)
    _woocommerce.py        # Helper compartilhado p/ sites WooCommerce
    ... (31 conectores)
  pipeline/
    schema.py              # Contrato canônico (dataclass Anuncio + validador)
    normalizer.py          # Normalização de preço e texto
    deduplicator.py        # Deduplicação por URL
    outlier_filter.py      # Filtro IQR de preços
    stats.py               # Cálculo estatístico (média, mediana, faixa)
    persistence.py         # Acesso ao PostgreSQL (histórico, anúncios, ranking)
  catalog/
    loader.py              # Carrega data/base_marcamodelo.csv em memória + matching fuzzy
tests/
scripts/
  demo_busca.py            # Demo CLI: --marca VOLKSWAGEN --modelo KOMBI
  ingest_*.py              # Scripts pontuais de ingestão manual
data/
  base_marcamodelo.csv     # Catálogo canônico marca/modelo/ano usado pelo loader
requirements.txt
```

## Pré-requisitos

- Python 3.10+
- PostgreSQL rodando localmente (ou acessível via `DATABASE_URL`)
- Playwright + Chromium (para os conectores que dependem de navegador)

## Instalação

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

Crie um `.env` na raiz do projeto (nunca committado — está no `.gitignore`) com:

```
DATABASE_URL=postgresql://usuario:senha@localhost:5432/nome_do_banco
ML_CLIENT_ID=...
ML_CLIENT_SECRET=...
DATAIMPULSE_HOST=...
DATAIMPULSE_PORT=...
DATAIMPULSE_USER=...
DATAIMPULSE_PASS=...
```

`ML_*` são credenciais da API do Mercado Livre (usadas pelo conector `mercadolivre`).
`DATAIMPULSE_*` são credenciais de proxy residencial (usadas pelos conectores que enfrentam
bloqueio antibot, ex.: `mercadolivre`, `reginaldodecampinas`).

## Como rodar o servidor web

```bash
python app.py
```

Acesse em: `http://127.0.0.1:5001/`
Painel admin em: `http://127.0.0.1:5001/admin`

## API pública

| Método | Endpoint | Parâmetros | Descrição |
|--------|----------|------------|-----------|
| GET | `/` | — | Serve o portal (`index.html`) |
| GET | `/api/marcas` | — | Lista marcas presentes no banco |
| GET | `/api/modelos` | `marca` | Lista modelos disponíveis para a marca |
| GET | `/api/anos` | `marca`, `modelo` | Lista anos disponíveis para marca+modelo |
| GET | `/api/buscar` | `marca`, `modelo`, `ano?` | Busca anúncios no banco e retorna estatísticas por ano |
| GET | `/api/historico` | `marca`, `modelo` | Série histórica de preços já persistida |
| GET | `/api/mais-pesquisados` | `limit?` | Ranking de modelos mais buscados |

### Exemplo de resposta — `/api/buscar`

```json
{
  "consulta": { "marca": "VOLKSWAGEN", "modelo": "FUSCA", "ano": null },
  "linhas": [
    { "ano": 1982, "media": 38500, "mediana": 37000, "minimo": 28000, "maximo": 52000, "amostra": 4 }
  ],
  "total_amostra": 4,
  "fontes_ativas": ["superantigo"]
}
```

## Painel admin e coleta

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/admin` | Painel de status e disparo manual de coleta |
| GET | `/admin/anuncios` | Lista/filtra anúncios brutos no banco |
| GET | `/admin/api/status` | Total de anúncios por fonte + lista de conectores |
| POST | `/admin/api/coletar` | Dispara coleta assíncrona de uma fonte (`{"fonte": "..."}`) |
| GET | `/admin/api/coletar-status/<task_id>` | Consulta status/resultado de uma coleta em andamento |

## Como rodar os testes

```bash
pytest tests/ -v
```

## Demo CLI de busca

```bash
python scripts/demo_busca.py --marca VOLKSWAGEN --modelo KOMBI
```

## Compliance

- `robots.txt` respeitado por conector: caminhos administrativos bloqueados.
- Rate limit conservador entre requisições.
- User-Agent realista definido em cada conector.
- Fonte identificada (campo `fonte`) em todos os anúncios persistidos.
