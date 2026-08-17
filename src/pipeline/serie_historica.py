"""
Série histórica mensal: fechar uma competência antes que a coleta seguinte
apague o mês anterior.

O PROBLEMA QUE ISTO RESOLVE
---------------------------
`anuncios` é o retrato do mercado AGORA, e o upsert é destrutivo por
natureza: `ON CONFLICT (fonte, url) DO UPDATE SET preco = EXCLUDED.preco`.
Todo anúncio que continuar no ar no mês seguinte tem o preço substituído, sem
cópia. Rodar a coleta de agosto sem fechar julho torna o índice de julho
irreproduzível.

Há um segundo problema, menos óbvio e pior: a coleta nunca APAGA. Anúncio que
saiu do ar fica na base com a `ultima_vista` velha e continua entrando nas
estatísticas do mês seguinte como se estivesse vivo. Quando isto foi escrito
havia ~1.100 anúncios de junho ainda pesando nos números publicados como
julho.

O QUE "FECHAR" FAZ
------------------
1. Copia pro `anuncios_snapshot` os anúncios VISTOS na competência, com o
   anúncio cru - preço, título, url, tudo. É o que permite recalcular o
   índice daquele mês depois, com curva nova ou catálogo mais curado.
2. Apaga da base ativa os anúncios que NÃO foram vistos. Eles continuam nos
   snapshots dos meses em que existiram; o que sai é o retrato do agora.

A COMPETÊNCIA DE UM ANÚNCIO É A `ultima_vista`
----------------------------------------------
Não é a data em que o script rodou. Uma coleta atravessa dias (julho teve
lote em 14 e em 23) e pode ser refeita semanas depois; o que define o mês é
quando o anúncio foi visto pela última vez.

A TRAVA DA FONTE NÃO COLETADA
-----------------------------
Apagar "tudo que não foi visto" destruiria uma fonte inteira que simplesmente
não foi coletada naquele mês - coletar só a OLX em agosto varreria os 5 mil
anúncios da Webmotors. Por isso a purga é restrita às fontes que TÊM anúncio
na competência: fonte sem nenhum não foi coletada, fica intacta e é
reportada.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from src.pipeline.persistence import _connect

logger = logging.getLogger(__name__)

FORMATO_COMPETENCIA = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validar_competencia(competencia: str) -> str:
    comp = (competencia or "").strip()
    if not FORMATO_COMPETENCIA.match(comp):
        raise ValueError(f"Competência {competencia!r} fora do formato AAAA-MM.")
    return comp


def competencias_na_base() -> list[dict[str, Any]]:
    """
    Que meses existem na base ATIVA, pela `ultima_vista`.

    Serve pra escolher o que fechar e pra enxergar sobra de mês anterior - o
    mês minoritário na lista é, quase sempre, anúncio morto ainda contando.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT SUBSTRING(ultima_vista, 1, 7) AS competencia,
                       COUNT(*) AS anuncios,
                       COUNT(DISTINCT fonte) AS fontes
                FROM anuncios
                WHERE ultima_vista IS NOT NULL AND ultima_vista != ''
                GROUP BY 1 ORDER BY 1 DESC
                """
            )
            return [dict(r) for r in cur.fetchall()]


def competencias_fechadas() -> list[dict[str, Any]]:
    """O que já virou série histórica."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT competencia, COUNT(*) AS anuncios,
                       COUNT(DISTINCT fonte) AS fontes,
                       COUNT(*) FILTER (WHERE preco > 0) AS com_preco,
                       MIN(ultima_vista) AS visto_de,
                       MAX(ultima_vista) AS visto_ate
                FROM anuncios_snapshot
                GROUP BY 1 ORDER BY 1 DESC
                """
            )
            return [dict(r) for r in cur.fetchall()]


def _diagnostico(cur, competencia: str) -> dict[str, Any]:
    """Quem entra, quem sai e quem fica intocado - antes de mexer em nada."""
    like = f"{competencia}-%"

    cur.execute(
        "SELECT COUNT(*) AS n FROM anuncios WHERE ultima_vista LIKE %s", (like,)
    )
    vistos = cur.fetchone()["n"]

    cur.execute(
        "SELECT DISTINCT fonte FROM anuncios WHERE ultima_vista LIKE %s", (like,)
    )
    fontes_coletadas = sorted(r["fonte"] for r in cur.fetchall())

    if fontes_coletadas:
        cur.execute(
            """
            SELECT fonte, COUNT(*) AS n, MAX(ultima_vista) AS visto_ate
            FROM anuncios
            WHERE fonte = ANY(%s) AND ultima_vista NOT LIKE %s
            GROUP BY fonte ORDER BY n DESC
            """,
            (fontes_coletadas, like),
        )
        mortos = [dict(r) for r in cur.fetchall()]
    else:
        mortos = []

    cur.execute(
        """
        SELECT fonte, COUNT(*) AS n, MAX(ultima_vista) AS visto_ate
        FROM anuncios
        WHERE NOT (fonte = ANY(%s))
        GROUP BY fonte ORDER BY n DESC
        """,
        (fontes_coletadas or [""],),
    )
    nao_coletadas = [dict(r) for r in cur.fetchall()]

    cur.execute(
        "SELECT COUNT(*) AS n FROM anuncios_snapshot WHERE competencia = %s",
        (competencia,),
    )
    ja_no_snapshot = cur.fetchone()["n"]

    return {
        "competencia": competencia,
        "vistos": vistos,
        "fontes_coletadas": fontes_coletadas,
        "mortos": mortos,
        "mortos_total": sum(m["n"] for m in mortos),
        # Fonte sem NENHUM anúncio na competência não foi coletada. Não é
        # anúncio morto, e apagar seria varrer uma fonte inteira.
        "nao_coletadas": nao_coletadas,
        "nao_coletadas_total": sum(f["n"] for f in nao_coletadas),
        "ja_no_snapshot": ja_no_snapshot,
    }


def diagnosticar(competencia: str) -> dict[str, Any]:
    """O que `fechar` faria, sem fazer."""
    comp = validar_competencia(competencia)
    with _connect() as conn:
        with conn.cursor() as cur:
            return _diagnostico(cur, comp)


def fechar(
    competencia: str,
    purgar: bool = True,
    refazer: bool = False,
) -> dict[str, Any]:
    """
    Fecha a competência: copia pro snapshot e limpa a base ativa.

    `purgar=False` grava o snapshot sem apagar nada - útil pra fechar um mês
    e só depois decidir sobre os mortos.

    `refazer=True` reescreve um snapshot já existente. Sem isso, fechar duas
    vezes é um erro: a segunda passada aconteceria depois de uma coleta nova
    ter mexido nos preços, e sobrescreveria o mês em silêncio com números que
    não são mais os daquele mês.

    Tudo numa transação só. Um snapshot gravado pela metade com a base ativa
    já purgada seria perda de dado irrecuperável.
    """
    comp = validar_competencia(competencia)
    like = f"{comp}-%"

    with _connect() as conn:
        with conn.cursor() as cur:
            diag = _diagnostico(cur, comp)

            if not diag["vistos"]:
                raise ValueError(
                    f"Nenhum anúncio visto em {comp} - nada a fechar. "
                    "Confira a competência (as disponíveis saem em "
                    "competencias_na_base())."
                )
            if diag["ja_no_snapshot"] and not refazer:
                raise ValueError(
                    f"{comp} já foi fechada ({diag['ja_no_snapshot']:,} anúncios). "
                    "Use refazer=True se a intenção é sobrescrever."
                )

            if refazer:
                cur.execute(
                    "DELETE FROM anuncios_snapshot WHERE competencia = %s", (comp,)
                )

            cur.execute(
                """
                INSERT INTO anuncios_snapshot
                    (competencia, fonte, url, titulo, marca, modelo, versao,
                     geracao, motor, obs, ano, preco, primeira_vista, ultima_vista)
                SELECT %s, fonte, url, titulo, marca, modelo, versao,
                       geracao, motor, obs, ano, preco, primeira_vista, ultima_vista
                FROM anuncios
                WHERE ultima_vista LIKE %s
                """,
                (comp, like),
            )
            gravados = cur.rowcount

            purgados = 0
            if purgar and diag["fontes_coletadas"]:
                cur.execute(
                    """
                    DELETE FROM anuncios
                    WHERE fonte = ANY(%s) AND ultima_vista NOT LIKE %s
                    """,
                    (diag["fontes_coletadas"], like),
                )
                purgados = cur.rowcount

    logger.info("Competência %s fechada: %d gravados, %d purgados",
                comp, gravados, purgados)
    return {**diag, "gravados": gravados, "purgados": purgados, "purgou": purgar}


def reabrir(competencia: str) -> dict[str, Any]:
    """
    Apaga o snapshot de uma competência.

    NÃO devolve à base ativa o que foi purgado - aquilo era anúncio morto e
    voltar a contá-lo seria refazer o problema. Serve pra corrigir um
    fechamento feito com a competência errada, logo depois, antes de a base
    seguir em frente.
    """
    comp = validar_competencia(competencia)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM anuncios_snapshot WHERE competencia = %s", (comp,)
            )
            return {"competencia": comp, "removidos": cur.rowcount}
