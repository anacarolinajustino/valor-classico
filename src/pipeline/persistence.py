"""
Persistência histórica de preços — PostgreSQL.

Responsabilidades:
  - Inicializar o banco e as tabelas (idempotente).
  - Registrar snapshot de preço por busca (upsert diário por marca/modelo/ano).
  - Registrar log de buscas para ranking "mais pesquisados".
  - Consultar série histórica de preços para um modelo.
  - Consultar ranking de modelos mais pesquisados.
  - Armazenar anúncios brutos coletados em batch (upsert por fonte+url).

Configuração: variável de ambiente DATABASE_URL (PostgreSQL connection string).
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any

import psycopg2
import psycopg2.extras

# ── Thresholds de negócio ─────────────────────────────────────────────────────

CHART_MIN_DIAS = 5
CHART_MAX_PONTOS = 10
ANO_CORTE_CLASSICO = 2000

# ── DDL ───────────────────────────────────────────────────────────────────────

_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS historico_precos (
        id            SERIAL PRIMARY KEY,
        marca         TEXT    NOT NULL,
        modelo        TEXT    NOT NULL,
        ano           INTEGER NOT NULL,
        preco_medio   REAL    NOT NULL,
        preco_mediano REAL,
        preco_min     REAL,
        preco_max     REAL,
        amostra       INTEGER NOT NULL,
        fonte         TEXT    NOT NULL DEFAULT 'maxicar',
        data          TEXT    NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_historico_dia
        ON historico_precos (marca, modelo, ano, data, fonte)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_historico_lookup
        ON historico_precos (marca, modelo, ano)
    """,
    """
    CREATE TABLE IF NOT EXISTS search_log (
        id        SERIAL PRIMARY KEY,
        marca     TEXT NOT NULL,
        modelo    TEXT NOT NULL,
        timestamp TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_search_log
        ON search_log (marca, modelo)
    """,
    """
    CREATE TABLE IF NOT EXISTS anuncios (
        id             SERIAL PRIMARY KEY,
        fonte          TEXT    NOT NULL,
        url            TEXT    NOT NULL,
        titulo         TEXT    NOT NULL,
        marca          TEXT,
        modelo         TEXT,
        ano            INTEGER,
        preco          REAL,
        primeira_vista TEXT    NOT NULL,
        ultima_vista   TEXT    NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_anuncios_fonte_url
        ON anuncios (fonte, url)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_anuncios_lookup
        ON anuncios (marca, modelo, ano)
    """,
]

# ── Conexão ───────────────────────────────────────────────────────────────────

def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL não configurada")
    # Render fornece URLs com prefixo 'postgres://', psycopg2 requer 'postgresql://'
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


@contextmanager
def _connect():
    conn = psycopg2.connect(
        _database_url(),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Cria tabelas e índices se não existirem. Idempotente."""
    with _connect() as conn:
        with conn.cursor() as cur:
            for stmt in _DDL_STATEMENTS:
                cur.execute(stmt)


# ── Escrita ───────────────────────────────────────────────────────────────────

def upsert_preco(
    marca: str,
    modelo: str,
    ano: int,
    preco_medio: float,
    amostra: int,
    preco_mediano: float | None = None,
    preco_min: float | None = None,
    preco_max: float | None = None,
    fonte: str = "maxicar",
    hoje: str | None = None,
) -> None:
    """Insere ou atualiza o snapshot diário de preço para marca/modelo/ano/fonte."""
    data = hoje or date.today().isoformat()
    sql = """
        INSERT INTO historico_precos
            (marca, modelo, ano, preco_medio, preco_mediano, preco_min, preco_max, amostra, fonte, data)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (marca, modelo, ano, data, fonte)
        DO UPDATE SET
            preco_medio   = EXCLUDED.preco_medio,
            preco_mediano = EXCLUDED.preco_mediano,
            preco_min     = EXCLUDED.preco_min,
            preco_max     = EXCLUDED.preco_max,
            amostra       = EXCLUDED.amostra
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (
                marca.upper(), modelo.upper(), ano,
                preco_medio, preco_mediano, preco_min, preco_max,
                amostra, fonte, data,
            ))


def upsert_anuncios(
    anuncios: list[Any],
    hoje: str | None = None,
) -> dict[str, int]:
    """
    Insere ou atualiza anúncios brutos coletados em batch.
    Chave de identidade: (fonte, url).
    """
    data = hoje or date.today().isoformat()
    sql_select = "SELECT 1 FROM anuncios WHERE fonte = %s AND url = %s"
    sql_upsert = """
        INSERT INTO anuncios
            (fonte, url, titulo, marca, modelo, ano, preco, primeira_vista, ultima_vista)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (fonte, url)
        DO UPDATE SET
            titulo       = EXCLUDED.titulo,
            marca        = EXCLUDED.marca,
            modelo       = EXCLUDED.modelo,
            ano          = EXCLUDED.ano,
            preco        = EXCLUDED.preco,
            ultima_vista = EXCLUDED.ultima_vista
    """
    novos = 0
    atualizados = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for a in anuncios:
                cur.execute(sql_select, (a.fonte, a.url))
                existe = cur.fetchone()
                cur.execute(sql_upsert, (
                    a.fonte, a.url, a.titulo,
                    (a.marca or "").upper() or None,
                    (a.modelo or "").upper() or None,
                    a.ano, a.preco, data, data,
                ))
                if existe:
                    atualizados += 1
                else:
                    novos += 1
    return {"novos": novos, "atualizados": atualizados}


def log_search(
    marca: str,
    modelo: str,
) -> None:
    """Registra um evento de busca no search_log."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO search_log (marca, modelo, timestamp) VALUES (%s, %s, %s)",
                (marca.upper(), modelo.upper(), ts),
            )


# ── Leitura ───────────────────────────────────────────────────────────────────

def get_historico(
    marca: str,
    modelo: str,
) -> dict[str, Any]:
    """Retorna a série histórica de preços para um modelo."""
    sql = """
        SELECT ano, data, preco_medio, preco_mediano, preco_min, preco_max, amostra
        FROM historico_precos
        WHERE marca = %s AND modelo = %s
        ORDER BY ano DESC, data DESC
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (marca.upper(), modelo.upper()))
            rows = cur.fetchall()

    por_ano: dict[int, list[dict]] = {}
    for r in rows:
        por_ano.setdefault(r["ano"], []).append(dict(r))

    series = []
    dias_distintos_max = 0

    for ano in sorted(por_ano, reverse=True):
        pontos_todos = por_ano[ano]
        dias_distintos = len({p["data"] for p in pontos_todos})
        dias_distintos_max = max(dias_distintos_max, dias_distintos)
        pontos = pontos_todos[:CHART_MAX_PONTOS]
        series.append({
            "ano": ano,
            "dias_distintos": dias_distintos,
            "pontos": [
                {
                    "data": p["data"],
                    "media": p["preco_medio"],
                    "mediana": p["preco_mediano"],
                    "minimo": p["preco_min"],
                    "maximo": p["preco_max"],
                    "amostra": p["amostra"],
                }
                for p in pontos
            ],
        })

    return {
        "marca": marca.upper(),
        "modelo": modelo.upper(),
        "chart_ready": dias_distintos_max >= CHART_MIN_DIAS,
        "chart_min_dias": CHART_MIN_DIAS,
        "series": series,
    }


def buscar_anuncios(
    marca: str,
    modelo: str,
    ano: int | None = None,
) -> list:
    """
    Consulta anúncios do banco por marca e modelo.
    Matching de modelo é fuzzy (LIKE bilateral).
    """
    from src.pipeline.schema import Anuncio

    marca_upper = marca.strip().upper()
    modelo_upper = modelo.strip().upper()

    sql = """
        SELECT fonte, url, titulo, marca, modelo, ano, preco, ultima_vista
        FROM anuncios
        WHERE UPPER(marca) = %s
          AND (
              UPPER(modelo) = %s
              OR UPPER(modelo) LIKE %s
              OR %s LIKE '%%' || UPPER(modelo) || '%%'
          )
          AND (%s IS NULL OR ano = %s)
          AND (ano IS NULL OR ano <= %s)
        ORDER BY ano DESC, preco ASC
    """
    params = (
        marca_upper,
        modelo_upper,
        f"%{modelo_upper}%",
        modelo_upper,
        ano,
        ano,
        ANO_CORTE_CLASSICO,
    )

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    return [
        Anuncio(
            titulo=r["titulo"] or "",
            preco=r["preco"],
            marca=r["marca"] or "",
            modelo=r["modelo"] or "",
            ano=r["ano"],
            versao=None,
            url=r["url"] or "",
            fonte=r["fonte"] or "",
            data_coleta=r["ultima_vista"] or date.today().isoformat(),
        )
        for r in rows
        if r["preco"] and r["preco"] > 0
    ]


def get_db_stats() -> dict[str, Any]:
    """Retorna estatísticas gerais do banco para o painel admin."""
    sql_total = "SELECT COUNT(*) AS total FROM anuncios"
    sql_fontes = """
        SELECT fonte, COUNT(*) AS count, MAX(ultima_vista) AS last_update
        FROM anuncios
        GROUP BY fonte
        ORDER BY count DESC
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_total)
            total = cur.fetchone()["total"]
            cur.execute(sql_fontes)
            por_fonte = [dict(r) for r in cur.fetchall()]

    return {"total_anuncios": total, "por_fonte": por_fonte}


def listar_anuncios(
    fonte: str | None = None,
    marca: str | None = None,
    modelo: str | None = None,
    ano: int | None = None,
    q: str | None = None,
    order_by: str = "ultima_vista",
    order_dir: str = "desc",
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """
    Retorna anúncios paginados com filtros opcionais.
    Usado pelo painel /admin/anuncios.
    """
    allowed_order = {"ultima_vista", "preco", "ano", "marca", "modelo", "fonte", "titulo"}
    if order_by not in allowed_order:
        order_by = "ultima_vista"
    direction = "DESC" if order_dir.lower() == "desc" else "ASC"

    conditions = ["1=1"]
    params: list[Any] = []

    if fonte:
        conditions.append("fonte = %s")
        params.append(fonte)
    if marca:
        conditions.append("UPPER(marca) = %s")
        params.append(marca.strip().upper())
    if modelo:
        conditions.append("UPPER(modelo) LIKE %s")
        params.append(f"%{modelo.strip().upper()}%")
    if ano:
        conditions.append("ano = %s")
        params.append(ano)
    if q:
        conditions.append("(UPPER(titulo) LIKE %s OR UPPER(marca) LIKE %s OR UPPER(modelo) LIKE %s)")
        like = f"%{q.strip().upper()}%"
        params.extend([like, like, like])

    where = " AND ".join(conditions)
    offset = (page - 1) * page_size

    sql_count = f"SELECT COUNT(*) AS total FROM anuncios WHERE {where}"
    sql_rows  = f"""
        SELECT id, fonte, url, titulo, marca, modelo, ano, preco, ultima_vista
        FROM anuncios
        WHERE {where}
        ORDER BY {order_by} {direction} NULLS LAST
        LIMIT %s OFFSET %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_count, params)
            total = cur.fetchone()["total"]
            cur.execute(sql_rows, params + [page_size, offset])
            rows = [dict(r) for r in cur.fetchall()]

    fontes_sql = "SELECT DISTINCT fonte FROM anuncios ORDER BY fonte"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(fontes_sql)
            fontes = [r["fonte"] for r in cur.fetchall()]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
        "rows": rows,
        "fontes_disponiveis": fontes,
    }


def get_marcas_db() -> list[str]:
    """Retorna lista de marcas distintas presentes na tabela anuncios."""
    sql = "SELECT DISTINCT UPPER(marca) AS marca FROM anuncios WHERE marca IS NOT NULL ORDER BY 1"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [r["marca"] for r in cur.fetchall() if r["marca"]]


def get_modelos_db(marca: str) -> list[str]:
    """Retorna lista de modelos distintos para uma marca na tabela anuncios."""
    sql = """
        SELECT DISTINCT UPPER(modelo) AS modelo
        FROM anuncios
        WHERE UPPER(marca) = %s AND modelo IS NOT NULL
        ORDER BY 1
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (marca.strip().upper(),))
            return [r["modelo"] for r in cur.fetchall() if r["modelo"]]


def get_anos_db(marca: str, modelo: str) -> list[int]:
    """Retorna lista de anos distintos para marca+modelo na tabela anuncios."""
    sql = """
        SELECT DISTINCT ano
        FROM anuncios
        WHERE UPPER(marca) = %s
          AND UPPER(modelo) = %s
          AND ano IS NOT NULL
          AND ano <= %s
        ORDER BY ano DESC
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (marca.strip().upper(), modelo.strip().upper(), ANO_CORTE_CLASSICO))
            return [r["ano"] for r in cur.fetchall()]


def get_mais_pesquisados(
    limit: int = 10,
) -> dict[str, Any]:
    """Retorna ranking de modelos mais pesquisados."""
    sql = """
        SELECT marca, modelo, COUNT(*) AS buscas
        FROM search_log
        GROUP BY marca, modelo
        ORDER BY buscas DESC
        LIMIT %s
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()

    return {
        "ranking": [
            {"marca": r["marca"], "modelo": r["modelo"], "buscas": r["buscas"]}
            for r in rows
        ]
    }
