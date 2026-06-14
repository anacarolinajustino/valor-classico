"""
Persistência histórica de preços — SQLite.

Responsabilidades:
  - Inicializar o banco e as tabelas (idempotente).
  - Registrar snapshot de preço por busca (upsert diário por marca/modelo/ano).
  - Registrar log de buscas para ranking "mais pesquisados".
  - Consultar série histórica de preços para um modelo.
  - Consultar ranking de modelos mais pesquisados.
  - Armazenar anúncios brutos coletados em batch (upsert por fonte+url).

Localização do banco: instance/valor_classico.db
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# ── Caminho do banco ──────────────────────────────────────────────────────────

_INSTANCE_DIR = Path(__file__).parent.parent.parent / "instance"
_DB_PATH = _INSTANCE_DIR / "valor_classico.db"

# ── Thresholds de negócio ─────────────────────────────────────────────────────

CHART_MIN_DIAS = 5    # mínimo de dias distintos para exibir gráfico
CHART_MAX_PONTOS = 10  # máximo de pontos retornados por série
ANO_CORTE_CLASSICO = 2000  # apenas veículos até este ano são exibidos

# ── DDL ───────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS historico_precos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
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
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_historico_dia
    ON historico_precos (marca, modelo, ano, data, fonte);

CREATE INDEX IF NOT EXISTS idx_historico_lookup
    ON historico_precos (marca, modelo, ano);

CREATE TABLE IF NOT EXISTS search_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    marca     TEXT NOT NULL,
    modelo    TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_search_log
    ON search_log (marca, modelo);

CREATE TABLE IF NOT EXISTS anuncios (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte          TEXT    NOT NULL,
    url            TEXT    NOT NULL,
    titulo         TEXT    NOT NULL,
    marca          TEXT,
    modelo         TEXT,
    ano            INTEGER,
    preco          REAL,
    primeira_vista TEXT    NOT NULL,
    ultima_vista   TEXT    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_anuncios_fonte_url
    ON anuncios (fonte, url);

CREATE INDEX IF NOT EXISTS idx_anuncios_lookup
    ON anuncios (marca, modelo, ano);
"""


# ── Conexão ───────────────────────────────────────────────────────────────────

def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Cria tabelas e índices se não existirem. Idempotente."""
    with _connect(db_path) as conn:
        conn.executescript(_DDL)


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
    db_path: Path | None = None,
) -> None:
    """
    Insere ou atualiza o snapshot diário de preço para marca/modelo/ano/fonte.
    Segunda busca no mesmo dia atualiza os valores (média mais fresca).
    """
    data = hoje or date.today().isoformat()
    sql = """
        INSERT INTO historico_precos
            (marca, modelo, ano, preco_medio, preco_mediano, preco_min, preco_max, amostra, fonte, data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (marca, modelo, ano, data, fonte)
        DO UPDATE SET
            preco_medio   = excluded.preco_medio,
            preco_mediano = excluded.preco_mediano,
            preco_min     = excluded.preco_min,
            preco_max     = excluded.preco_max,
            amostra       = excluded.amostra
    """
    with _connect(db_path) as conn:
        conn.execute(sql, (
            marca.upper(), modelo.upper(), ano,
            preco_medio, preco_mediano, preco_min, preco_max,
            amostra, fonte, data,
        ))


def upsert_anuncios(
    anuncios: list[Any],
    hoje: str | None = None,
    db_path: Path | None = None,
) -> dict[str, int]:
    """
    Insere ou atualiza anúncios brutos coletados em batch.

    Chave de identidade: (fonte, url). Anúncio já conhecido tem preço, título
    e demais campos atualizados e `ultima_vista` renovada — `primeira_vista`
    é preservada. Isso permite detectar anúncios que saíram do ar (ultima_vista
    antiga) e variação de preço por anúncio entre coletas.

    Args:
        anuncios: objetos com atributos do contrato canônico (Anuncio).
        hoje:     data ISO da coleta (default: hoje).

    Returns:
        {"novos": N, "atualizados": M}
    """
    data = hoje or date.today().isoformat()
    sql = """
        INSERT INTO anuncios
            (fonte, url, titulo, marca, modelo, ano, preco, primeira_vista, ultima_vista)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (fonte, url)
        DO UPDATE SET
            titulo       = excluded.titulo,
            marca        = excluded.marca,
            modelo       = excluded.modelo,
            ano          = excluded.ano,
            preco        = excluded.preco,
            ultima_vista = excluded.ultima_vista
    """
    novos = 0
    atualizados = 0
    with _connect(db_path) as conn:
        for a in anuncios:
            existe = conn.execute(
                "SELECT 1 FROM anuncios WHERE fonte = ? AND url = ?",
                (a.fonte, a.url),
            ).fetchone()
            conn.execute(sql, (
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
    db_path: Path | None = None,
) -> None:
    """Registra um evento de busca no search_log."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO search_log (marca, modelo, timestamp) VALUES (?, ?, ?)",
            (marca.upper(), modelo.upper(), ts),
        )


# ── Leitura ───────────────────────────────────────────────────────────────────

def get_historico(
    marca: str,
    modelo: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """
    Retorna a série histórica de preços para um modelo.

    Regras de negócio (backend):
      - chart_ready=True apenas se existirem >= CHART_MIN_DIAS dias distintos
        em pelo menos uma série de ano.
      - Cada série retorna no máximo CHART_MAX_PONTOS pontos (os mais recentes).
    """
    sql = """
        SELECT ano, data, preco_medio, preco_mediano, preco_min, preco_max, amostra
        FROM historico_precos
        WHERE marca = ? AND modelo = ?
        ORDER BY ano DESC, data DESC
    """
    with _connect(db_path) as conn:
        rows = conn.execute(sql, (marca.upper(), modelo.upper())).fetchall()

    # Agrupa por ano
    por_ano: dict[int, list[dict]] = {}
    for r in rows:
        por_ano.setdefault(r["ano"], []).append(dict(r))

    series = []
    dias_distintos_max = 0

    for ano in sorted(por_ano, reverse=True):
        pontos_todos = por_ano[ano]          # já ordenados por data DESC
        dias_distintos = len({p["data"] for p in pontos_todos})
        dias_distintos_max = max(dias_distintos_max, dias_distintos)

        # Últimos CHART_MAX_PONTOS pontos (mais recentes primeiro)
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

    chart_ready = dias_distintos_max >= CHART_MIN_DIAS

    return {
        "marca": marca.upper(),
        "modelo": modelo.upper(),
        "chart_ready": chart_ready,
        "chart_min_dias": CHART_MIN_DIAS,
        "series": series,
    }


def buscar_anuncios(
    marca: str,
    modelo: str,
    ano: int | None = None,
    db_path: Path | None = None,
) -> list:
    """
    Consulta anúncios do banco local por marca e modelo.

    Matching de modelo é fuzzy (LIKE bilateral): casa "KOMBI" com "KOMBI LUXO"
    e vice-versa. Retorna objetos Anuncio prontos para o pipeline de stats.
    """
    from src.pipeline.schema import Anuncio

    marca_upper = marca.strip().upper()
    modelo_upper = modelo.strip().upper()

    sql = """
        SELECT fonte, url, titulo, marca, modelo, ano, preco, ultima_vista
        FROM anuncios
        WHERE UPPER(marca) = ?
          AND (
              UPPER(modelo) = ?
              OR UPPER(modelo) LIKE ?
              OR ? LIKE '%' || UPPER(modelo) || '%'
          )
          AND (? IS NULL OR ano = ?)
          AND (ano IS NULL OR ano <= ?)
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

    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()

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


def get_mais_pesquisados(
    limit: int = 10,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Retorna ranking de modelos mais pesquisados (por contagem total de buscas)."""
    sql = """
        SELECT marca, modelo, COUNT(*) AS buscas
        FROM search_log
        GROUP BY marca, modelo
        ORDER BY buscas DESC
        LIMIT ?
    """
    with _connect(db_path) as conn:
        rows = conn.execute(sql, (limit,)).fetchall()

    return {
        "ranking": [
            {"marca": r["marca"], "modelo": r["modelo"], "buscas": r["buscas"]}
            for r in rows
        ]
    }
