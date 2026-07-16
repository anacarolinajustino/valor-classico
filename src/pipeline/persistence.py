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

    Aplica o corte de ano centralmente: anúncio com ano > ANO_CORTE_CLASSICO
    é descartado (contado em "descartados_ano"), venha de qual conector vier —
    auditoria de 2026-07-14 achou 130 carros modernos (até 2026) gravados por
    13 conectores de lojas que não aplicavam o corte por conta própria.
    Anúncios com ano None entram normalmente (clássico com parser falho não
    é carro moderno).
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
    descartados_ano = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for a in anuncios:
                if a.ano is not None and a.ano > ANO_CORTE_CLASSICO:
                    descartados_ano += 1
                    continue
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
    return {"novos": novos, "atualizados": atualizados, "descartados_ano": descartados_ano}


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


def get_dashboard_stats(
    fonte: str | None = None,
    marca: str | None = None,
    modelo: str | None = None,
    ano: int | None = None,
) -> dict[str, Any]:
    """
    Agregados pro dashboard do painel admin, opcionalmente recortados por
    fonte/marca/modelo/ano. Uma chamada devolve todos os blocos que a página
    consome, pra manter os números consistentes entre si (mesma foto do
    banco) — incluindo as opções de cada filtro com a contagem de anúncios,
    no estilo faceta: as opções de uma dimensão são contadas sob os OUTROS
    filtros ativos (nunca sob ela mesma, senão só sobraria a opção escolhida).
    """
    filtros: dict[str, Any] = {
        "fonte": fonte,
        "marca": marca.strip().upper() if marca else None,
        "modelo": modelo.strip().upper() if modelo else None,
        "ano": ano,
    }

    def _where(excluir: str | None = None, *extra: str) -> tuple[str, list]:
        conds, params = [], []
        for campo, valor in filtros.items():
            if valor is not None and campo != excluir:
                conds.append(f"{campo} = %s")
                params.append(valor)
        conds.extend(extra)
        sql = ("WHERE " + " AND ".join(conds)) if conds else ""
        return sql, params

    cond, params = _where()
    cond_e = f"{cond} AND" if cond else "WHERE"

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)                                            AS total,
                       COUNT(ano)                                          AS com_ano,
                       COUNT(DISTINCT fonte)                               AS fontes,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY preco)  AS preco_mediano
                FROM anuncios {cond}
                """,
                params,
            )
            k = cur.fetchone()

            cur.execute(
                f"SELECT fonte, COUNT(*) AS qtd FROM anuncios {cond} "
                "GROUP BY fonte ORDER BY qtd DESC",
                params,
            )
            por_fonte = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"""
                SELECT CASE WHEN ano < 1950 THEN 1949 ELSE (ano / 10) * 10 END AS decada,
                       COUNT(*)                                                AS qtd,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY preco)      AS preco_mediano
                FROM anuncios {cond_e} ano IS NOT NULL
                GROUP BY 1 ORDER BY 1
                """,
                params,
            )
            por_decada = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"SELECT marca, COUNT(*) AS qtd FROM anuncios {cond_e} marca IS NOT NULL "
                "GROUP BY marca ORDER BY qtd DESC LIMIT 10",
                params,
            )
            top_marcas = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"""
                SELECT CASE
                         WHEN preco <  25000  THEN 0
                         WHEN preco <  50000  THEN 1
                         WHEN preco <  100000 THEN 2
                         WHEN preco <  200000 THEN 3
                         WHEN preco <  500000 THEN 4
                         ELSE 5
                       END      AS faixa,
                       COUNT(*) AS qtd
                FROM anuncios {cond_e} preco IS NOT NULL AND preco > 0
                GROUP BY 1 ORDER BY 1
                """,
                params,
            )
            faixas_preco = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"""
                SELECT marca, modelo, COUNT(*) AS qtd,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY preco) AS preco_mediano
                FROM anuncios {cond_e} marca IS NOT NULL AND modelo IS NOT NULL
                GROUP BY marca, modelo ORDER BY qtd DESC LIMIT 15
                """,
                params,
            )
            top_modelos = [dict(r) for r in cur.fetchall()]

            # Opções dos filtros de recorte, no estilo faceta: contadas sob os
            # OUTROS filtros ativos, nunca sob elas mesmas. Modelo é uma cascata
            # de marca (5,5 mil modelos distintos no banco todo — só faz sentido
            # listar depois que uma marca reduz o universo).
            cond_op_marca, params_op_marca = _where("marca", "marca IS NOT NULL")
            cur.execute(
                f"SELECT marca, COUNT(*) AS qtd FROM anuncios {cond_op_marca} "
                "GROUP BY marca ORDER BY marca",
                params_op_marca,
            )
            opcoes_marca = [dict(r) for r in cur.fetchall()]

            opcoes_modelo: list[dict[str, Any]] = []
            if filtros["marca"]:
                cond_op_modelo, params_op_modelo = _where("modelo", "modelo IS NOT NULL")
                cur.execute(
                    f"SELECT modelo, COUNT(*) AS qtd FROM anuncios {cond_op_modelo} "
                    "GROUP BY modelo ORDER BY modelo",
                    params_op_modelo,
                )
                opcoes_modelo = [dict(r) for r in cur.fetchall()]

            cond_op_ano, params_op_ano = _where("ano", "ano IS NOT NULL")
            cur.execute(
                f"SELECT ano, COUNT(*) AS qtd FROM anuncios {cond_op_ano} "
                "GROUP BY ano ORDER BY ano DESC",
                params_op_ano,
            )
            opcoes_ano = [dict(r) for r in cur.fetchall()]

    return {
        "kpis": {
            "total": k["total"],
            "com_ano": k["com_ano"],
            "fontes": k["fontes"],
            "preco_mediano": k["preco_mediano"],
        },
        "por_fonte": por_fonte,
        "por_decada": por_decada,
        "top_marcas": top_marcas,
        "faixas_preco": faixas_preco,
        "top_modelos": top_modelos,
        "opcoes": {
            "marca": opcoes_marca,
            "modelo": opcoes_modelo,
            "ano": opcoes_ano,
        },
    }


def listar_anuncios(
    fonte: str | None = None,
    marca: str | None = None,
    modelo: str | None = None,
    modelo_exato: bool = False,
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

    `modelo` por padrão é busca livre (LIKE, pro campo de filtro manual da
    tela). `modelo_exato=True` usa igualdade — necessário quando o modelo
    vem de um agrupamento exato (ex.: link "ver anúncios" da tabela de
    modelos mais anunciados do dashboard, que usa GROUP BY marca, modelo):
    sem isso, "Fusca 1300" também traria "Fusca 1300 Standard"/"1300L" e a
    contagem não bateria com a do dashboard.
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
        if modelo_exato:
            conditions.append("UPPER(modelo) = %s")
            params.append(modelo.strip().upper())
        else:
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
