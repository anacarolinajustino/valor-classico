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
    # Versão/trim (GLX, SS, "Geração I CL"...) separada do modelo, e obs
    # residual (carroceria/tração: "Cabine Estendida", "Pick-Up") que não é
    # trim mas também não pode ser descartada (usuária pediu 2026-07-20).
    # ALTER ADD COLUMN IF NOT EXISTS é aditivo/idempotente — não afeta as
    # colunas existentes nem os 28 mil anúncios já gravados.
    "ALTER TABLE anuncios ADD COLUMN IF NOT EXISTS versao TEXT",
    "ALTER TABLE anuncios ADD COLUMN IF NOT EXISTS obs TEXT",
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

    Descarta também os BUGGY (contados em "descartados_buggy"): a usuária baniu
    buggy do escopo (2026-07-22), então nem entram no banco — ver `_e_buggy`.
    Idem para HOT ROD (contados em "descartados_hot_rod"; banido em 2026-07-23,
    identificado pelo título/versão/modelo — ver `_e_hot_rod`).
    """
    data = hoje or date.today().isoformat()
    sql_select = "SELECT 1 FROM anuncios WHERE fonte = %s AND url = %s"
    sql_upsert = """
        INSERT INTO anuncios
            (fonte, url, titulo, marca, modelo, ano, preco, primeira_vista, ultima_vista, versao, obs)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (fonte, url)
        DO UPDATE SET
            titulo       = EXCLUDED.titulo,
            marca        = EXCLUDED.marca,
            modelo       = EXCLUDED.modelo,
            ano          = EXCLUDED.ano,
            preco        = EXCLUDED.preco,
            ultima_vista = EXCLUDED.ultima_vista,
            versao       = EXCLUDED.versao,
            obs          = EXCLUDED.obs
    """
    novos = 0
    atualizados = 0
    descartados_ano = 0
    descartados_buggy = 0
    descartados_hot_rod = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for a in anuncios:
                if a.ano is not None and a.ano > ANO_CORTE_CLASSICO:
                    descartados_ano += 1
                    continue
                if _e_buggy(a.marca or "", a.modelo or ""):
                    descartados_buggy += 1
                    continue
                if _e_hot_rod(a.titulo or "", a.modelo or "", a.versao or ""):
                    descartados_hot_rod += 1
                    continue
                cur.execute(sql_select, (a.fonte, a.url))
                existe = cur.fetchone()
                cur.execute(sql_upsert, (
                    a.fonte, a.url, a.titulo,
                    (a.marca or "").upper() or None,
                    (a.modelo or "").upper() or None,
                    a.ano, a.preco, data, data,
                    (a.versao or "").upper() or None,
                    (a.obs or "").upper() or None,
                ))
                if existe:
                    atualizados += 1
                else:
                    novos += 1
    return {
        "novos": novos,
        "atualizados": atualizados,
        "descartados_ano": descartados_ano,
        "descartados_buggy": descartados_buggy,
        "descartados_hot_rod": descartados_hot_rod,
    }


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
        SELECT fonte, url, titulo, marca, modelo, ano, preco, ultima_vista, versao, obs
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
            versao=r["versao"],
            obs=r["obs"],
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


def _opcoes_marca_modelo_ano(
    cur, fonte: str | None, marca: str | None, modelo: str | None, ano: int | None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Opções pros dropdowns de marca/modelo/ano (dashboard e /admin/anuncios),
    no estilo faceta: cada dimensão é contada sob os OUTROS filtros ativos,
    nunca sob ela mesma (senão só sobraria a opção já escolhida). Modelo é
    uma cascata de marca (5,5 mil modelos distintos no banco todo — só faz
    sentido listar depois que uma marca reduz o universo).
    """
    filtros: dict[str, Any] = {
        "fonte": fonte,
        "marca": marca.strip().upper() if marca else None,
        "modelo": modelo.strip().upper() if modelo else None,
        "ano": ano,
    }

    def _where(excluir: tuple[str, ...] = (), *extra: str) -> tuple[str, list]:
        conds, params = [], []
        for campo, valor in filtros.items():
            if valor is not None and campo not in excluir:
                conds.append(f"{campo} = %s")
                params.append(valor)
        conds.extend(extra)
        sql = ("WHERE " + " AND ".join(conds)) if conds else ""
        return sql, params

    # Marca exclui também "modelo" do facetamento (não só "marca" de si
    # mesma) — modelo é subordinado à marca, não o contrário. Sem isso, um
    # link que chega com marca+modelo já setados (ex.: "ver anúncios" do
    # dashboard) mostraria só a própria marca de origem no dropdown —
    # qualquer outra marca não tem esse modelo específico, então sumiria.
    cond_op_marca, params_op_marca = _where(("marca", "modelo"), "marca IS NOT NULL")
    cur.execute(
        f"SELECT marca, COUNT(*) AS qtd FROM anuncios {cond_op_marca} "
        "GROUP BY marca ORDER BY marca",
        params_op_marca,
    )
    opcoes_marca = [dict(r) for r in cur.fetchall()]

    opcoes_modelo: list[dict[str, Any]] = []
    if filtros["marca"]:
        cond_op_modelo, params_op_modelo = _where(("modelo",), "modelo IS NOT NULL")
        cur.execute(
            f"SELECT modelo, COUNT(*) AS qtd FROM anuncios {cond_op_modelo} "
            "GROUP BY modelo ORDER BY modelo",
            params_op_modelo,
        )
        opcoes_modelo = [dict(r) for r in cur.fetchall()]

    cond_op_ano, params_op_ano = _where(("ano",), "ano IS NOT NULL")
    cur.execute(
        f"SELECT ano, COUNT(*) AS qtd FROM anuncios {cond_op_ano} "
        "GROUP BY ano ORDER BY ano DESC",
        params_op_ano,
    )
    opcoes_ano = [dict(r) for r in cur.fetchall()]

    return {"marca": opcoes_marca, "modelo": opcoes_modelo, "ano": opcoes_ano}


def get_dashboard_stats(
    fonte: str | None = None,
    marca: str | None = None,
    modelo: str | None = None,
    ano: int | None = None,
    min_anuncios: int | None = None,
) -> dict[str, Any]:
    """
    Agregados pro dashboard do painel admin, opcionalmente recortados por
    fonte/marca/modelo/ano. Uma chamada devolve todos os blocos que a página
    consome, pra manter os números consistentes entre si (mesma foto do
    banco) — incluindo as opções de cada filtro com a contagem de anúncios,
    no estilo faceta (ver `_opcoes_marca_modelo_ano`).

    `min_anuncios` é um recorte por VOLUME: restringe tudo aos veículos (pares
    marca+modelo) que têm pelo menos essa quantidade de anúncios coletados
    (dentro dos outros filtros ativos) — pra focar nos modelos bem representados
    e tirar o ruído dos que aparecem só uma ou duas vezes.
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

    # Recorte por volume: só os pares (marca, modelo) com COUNT(*) >= min_anuncios
    # (sob os mesmos filtros). Aplicado a todos os blocos via a condição comum.
    if min_anuncios and min_anuncios > 1:
        sub_sql, sub_params = _where()
        sub_cond = (f"{sub_sql} AND " if sub_sql else "WHERE ") + "marca IS NOT NULL AND modelo IS NOT NULL"
        pair_sql = (
            "(marca, modelo) IN (SELECT marca, modelo FROM anuncios "
            f"{sub_cond} GROUP BY marca, modelo HAVING COUNT(*) >= %s)"
        )
        cond = f"{cond} AND {pair_sql}" if cond else f"WHERE {pair_sql}"
        params = params + sub_params + [min_anuncios]

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

            opcoes = _opcoes_marca_modelo_ano(cur, fonte, marca, modelo, ano)

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
        "opcoes": opcoes,
    }


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

    fonte/marca/modelo/ano são dropdowns (valores exatos do catálogo — ver
    `opcoes` no retorno, no estilo faceta de `_opcoes_marca_modelo_ano`); `q`
    é a única busca livre (LIKE em título/marca/modelo).
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
        conditions.append("UPPER(modelo) = %s")
        params.append(modelo.strip().upper())
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
        SELECT id, fonte, url, titulo, marca, modelo, ano, preco, ultima_vista, versao, obs
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

            cur.execute("SELECT DISTINCT fonte FROM anuncios ORDER BY fonte")
            fontes = [r["fonte"] for r in cur.fetchall()]

            opcoes = _opcoes_marca_modelo_ano(cur, fonte, marca, modelo, ano)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
        "rows": rows,
        "fontes_disponiveis": fontes,
        "opcoes": opcoes,
    }


def listar_marca_modelo_pares() -> list[dict[str, Any]]:
    """
    Retorna todos os pares (marca, modelo) distintos com contagem de
    anúncios, SEM cascata (marca e modelo juntos numa lista plana) — usado
    pra revisão manual de qualidade de dado no painel: acha grafias
    fragmentadas do mesmo modelo (ex.: "BAND" ao lado de "BANDEIRANTE") que
    a busca em cascata esconde, porque cada marca só mostra os modelos dela
    por vez.
    """
    # COALESCE trata modelo NULL e '' como o mesmo balde "sem modelo" — senão
    # os anúncios com modelo NULL some da lista (não apareciam na quarentena
    # nem batiam com o detalhe do par, que casa por COALESCE).
    sql = """
        SELECT marca, COALESCE(modelo, '') AS modelo, COUNT(*) AS qtd
        FROM anuncios
        WHERE marca IS NOT NULL
        GROUP BY marca, COALESCE(modelo, '')
        ORDER BY marca, COALESCE(modelo, '')
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]


def _e_buggy(marca: str, modelo: str) -> bool:
    """
    Buggy — BANIDO do projeto (decisão da usuária 2026-07-22): descartado já na
    coleta (`upsert_anuncios`) e nunca aparece na quarentena. Cobre as marcas de
    buggy (ver `BUGGY_MARCAS`: BUGGY, BUGWAY, BRM, BUGRE, FYBER...) e qualquer
    modelo que contenha "BUGGY" (ex.: "GLASPACBUGGY").
    """
    from src.pipeline.normalizer import BUGGY_MARCAS

    return (marca or "").upper() in BUGGY_MARCAS or "BUGGY" in (modelo or "").upper()


def _e_hot_rod(titulo: str, modelo: str, versao: str) -> bool:
    """
    Hot rod — BANIDO do projeto (decisão da usuária 2026-07-23): descartado já na
    coleta (`upsert_anuncios`). Diferente do buggy, hot rod não é marca (são
    Fords dos anos 30, Chevrolets... reais), então é identificado pela palavra
    "hot rod"/"hotrod"/"hot-rod" no título (onde quase sempre aparece), na versão
    ou no modelo. Ver `contem_hot_rod` (normalizer) e scripts/remover_hot_rods.py.
    """
    from src.pipeline.normalizer import contem_hot_rod

    return contem_hot_rod(titulo, modelo, versao)


def listar_anuncios_a_verificar() -> dict[str, Any]:
    """
    "Quarentena": pares (marca, modelo) do banco que NÃO estão no catálogo
    consagrado (base_marcamodelo.csv + suplemento). São os anúncios a
    verificar manualmente no painel — dali a usuária indica a marca/modelo
    corretos (via `corrigir_marca_modelo`) pra integrá-los ao grupo principal.

    Buggies ficam de fora por decisão da usuária (ver `_e_buggy_quarentena`).

    Retorna:
      - `pares`: lista {marca, modelo, qtd}, ordenada por marca/modelo;
      - `total_pares` / `total_anuncios`: totais da quarentena;
      - `marcas_catalogo`: marcas distintas do catálogo (pra datalist do
        campo de correção, evitando typo de marca na hora de corrigir);
      - `modelos_catalogo`: mapa {marca: [modelos]} do catálogo consagrado, pra
        a usuária SELECIONAR um modelo já cadastrado da marca (garante casar com
        um par existente em vez de digitar e arriscar grafia divergente).
    """
    # Import tardio: loader importa normalizer/schema, não persistence (sem
    # ciclo), mas mantido local por consistência com os outros usos do catálogo.
    from src.catalog.loader import carregar_catalogo
    from src.pipeline.normalizer import normalizar_texto

    catalogo = carregar_catalogo()
    pares = listar_marca_modelo_pares()
    fora = [
        p for p in pares
        if (normalizar_texto(p["marca"] or ""), normalizar_texto(p["modelo"] or "")) not in catalogo
        and not _e_buggy(p["marca"] or "", p["modelo"] or "")
    ]
    marcas_catalogo = sorted({mk for mk, _ in catalogo})
    modelos_catalogo: dict[str, list[str]] = {}
    for mk, md in catalogo:
        if md:
            modelos_catalogo.setdefault(mk, []).append(md)
    for mk in modelos_catalogo:
        modelos_catalogo[mk] = sorted(modelos_catalogo[mk])
    return {
        "pares": fora,
        "total_pares": len(fora),
        "total_anuncios": sum(p["qtd"] for p in fora),
        "marcas_catalogo": marcas_catalogo,
        "modelos_catalogo": modelos_catalogo,
    }


def corrigir_marca_modelo(
    marca_atual: str, modelo_atual: str, marca_nova: str, modelo_nova: str
) -> dict[str, Any]:
    """
    Reatribui TODOS os anúncios do par (marca_atual, modelo_atual) pro par
    corrigido (marca_nova, modelo_nova) — o mecanismo de "sair da quarentena"
    do painel. Os valores novos são normalizados (maiúsculo, sem acento) pra
    bater com a convenção de armazenamento.

    Retorna {atualizados, marca, modelo, no_catalogo}: `no_catalogo` diz se o
    par corrigido está no catálogo consagrado (ou seja, se de fato saiu da
    quarentena) — senão, continuará aparecendo na lista a verificar.

    NB: correção de uso interativo (curadoria manual) — não gera backup por
    edição (seria lento demais pra triagem de centenas de pares); cada correção
    é pequena e fica registrada no log da rota chamadora. Os backups pós-coleta
    seguem cobrindo o banco.
    """
    from src.catalog.loader import carregar_catalogo
    from src.pipeline.normalizer import normalizar_texto

    mk_a = normalizar_texto(marca_atual or "")
    md_a = normalizar_texto(modelo_atual or "")
    mk_n = normalizar_texto(marca_nova or "")
    md_n = normalizar_texto(modelo_nova or "")
    if not mk_n:
        raise ValueError("Marca nova não pode ser vazia.")
    if (mk_a, md_a) == (mk_n, md_n):
        raise ValueError("O par corrigido é igual ao atual — nada a fazer.")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE anuncios SET marca = %s, modelo = %s "
                "WHERE UPPER(marca) = %s AND UPPER(modelo) = %s",
                (mk_n, md_n, mk_a, md_a),
            )
            atualizados = cur.rowcount

    no_catalogo = (mk_n, md_n) in carregar_catalogo()
    return {
        "atualizados": atualizados,
        "marca": mk_n,
        "modelo": md_n,
        "no_catalogo": no_catalogo,
    }


def excluir_marca_modelo(marca: str, modelo: str) -> dict[str, Any]:
    """
    Apaga TODOS os anúncios de um par (marca, modelo) da quarentena — pro caso
    em que o veículo simplesmente não pertence ao acervo (ex.: um VW T-Cross que
    entrou por ano forjado no título "…1.0 TSI … 1972"). Casa modelo vazio/NULL
    via COALESCE, igual `listar_anuncios_do_par`.

    NB: ação de curadoria interativa, irreversível. Como `corrigir_marca_modelo`,
    NÃO gera backup por clique (seria lento demais na triagem) — a rota chamadora
    loga o que foi apagado e a UI confirma antes; os backups pós-coleta cobrem o
    banco. Retorna {excluidos}.
    """
    from src.pipeline.normalizer import normalizar_texto

    mk = normalizar_texto(marca or "")
    md = normalizar_texto(modelo or "")
    if not mk:
        raise ValueError("Marca é obrigatória.")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM anuncios "
                "WHERE UPPER(marca) = %s AND COALESCE(UPPER(modelo), '') = %s",
                (mk, md),
            )
            excluidos = cur.rowcount
    return {"excluidos": excluidos}


def listar_anuncios_do_par(marca: str, modelo: str, limite: int = 300) -> list[dict[str, Any]]:
    """
    Anúncios de um par (marca, modelo) EXATO — pra inspecionar um item da
    quarentena no painel antes de corrigir/cadastrar. Casa modelo vazio/NULL
    via COALESCE (os pares "sem modelo" também precisam ser inspecionáveis).
    Lista enxuta (sem paginação — um par de quarentena tem poucos anúncios).
    """
    from src.pipeline.normalizer import normalizar_texto

    mk = normalizar_texto(marca or "")
    md = normalizar_texto(modelo or "")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, fonte, url, titulo, ano, preco, versao, obs "
                "FROM anuncios "
                "WHERE UPPER(marca) = %s AND COALESCE(UPPER(modelo), '') = %s "
                "ORDER BY ano NULLS LAST, id "
                "LIMIT %s",
                (mk, md, limite),
            )
            return [dict(r) for r in cur.fetchall()]


def adicionar_ao_catalogo(marca: str, modelo: str) -> dict[str, Any]:
    """
    Adiciona um par (marca, modelo) ao catálogo, pro caso em que o anúncio já
    está com marca/modelo corretos e o que faltava era cadastrar o modelo
    (ele estava na quarentena só por ausência do catálogo). Grava no
    suplemento manual (data/suplemento_manual.csv), que o loader lê junto com
    o CSV base — persiste entre reinícios sem mexer no código.

    A faixa de anos é derivada dos próprios anúncios desse par (min/max do ano
    presente no banco); sem ano, fica vazia (a chave existe mesmo assim, que é
    o que tira o par da quarentena). Reseta o cache do catálogo pra a mudança
    valer já na próxima consulta.

    Retorna {ja_existia, marca, modelo, ano_min, ano_max}.
    """
    import csv as _csv

    from src.catalog.loader import (
        SUPLEMENTO_MANUAL_CSV,
        carregar_catalogo,
        resetar_cache,
    )
    from src.pipeline.normalizer import normalizar_texto

    mk = normalizar_texto(marca or "")
    md = normalizar_texto(modelo or "")
    if not mk or not md:
        raise ValueError("Marca e modelo são obrigatórios pra adicionar ao catálogo.")

    if (mk, md) in carregar_catalogo():
        return {"ja_existia": True, "marca": mk, "modelo": md, "ano_min": None, "ano_max": None}

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MIN(ano) AS mn, MAX(ano) AS mx FROM anuncios "
                "WHERE UPPER(marca) = %s AND UPPER(modelo) = %s AND ano IS NOT NULL",
                (mk, md),
            )
            r = cur.fetchone()
    ano_min, ano_max = (r["mn"], r["mx"]) if r else (None, None)

    novo = not SUPLEMENTO_MANUAL_CSV.exists()
    SUPLEMENTO_MANUAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(SUPLEMENTO_MANUAL_CSV, "a", encoding="utf-8", newline="") as f:
        w = _csv.writer(f)
        if novo:
            w.writerow(["marca", "modelo", "ano_min", "ano_max"])
        w.writerow([mk, md, ano_min if ano_min is not None else "", ano_max if ano_max is not None else ""])

    resetar_cache()  # próxima carregar_catalogo() já enxerga o novo par
    return {"ja_existia": False, "marca": mk, "modelo": md, "ano_min": ano_min, "ano_max": ano_max}


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
