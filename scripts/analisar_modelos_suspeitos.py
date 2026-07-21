"""
Análise fina de modelos suspeitos (auditoria 2026-07-21, 2ª passada).

A 1ª passada da auditoria de existência só tratou os grupos com 3+ anúncios.
Restaram erros em pares de 1-2 anúncios: ano vazado pro modelo, modelo='0',
typos de Willys, grafia feia (VW-FUSCA-1300), marca repetida no modelo.

Este script classifica CADA par (marca, modelo) do banco por tipo provável de
problema e imprime todos os títulos distintos, pra revisão par a par. Não
altera nada.

Uso:
    python scripts/analisar_modelos_suspeitos.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.catalog.loader import carregar_catalogo, _melhor_fuzzy, canonizar_modelo
from src.pipeline.normalizer import normalizar_texto, _ALIASES_MARCA
from src.pipeline.persistence import _connect

# Typos/variações de marca que, se aparecem como MODELO, denunciam marca
# duplicada mal parseada.
_MARCAS_CONHECIDAS_NORM = set()


def classificar(marca: str, modelo: str, anos: set[int], catalogo, marcas_catalogo) -> str:
    m = (modelo or "").strip()
    marca_norm = normalizar_texto(marca)
    # aplica canonização de grafia (simula o pós-reprocessamento)
    modelo_norm = canonizar_modelo(marca_norm, normalizar_texto(m))

    if not m:
        return "VAZIO"
    if m == "0":
        return "ZERO"
    # Match exato no catálogo/suplemento -> provavelmente OK
    if (marca_norm, modelo_norm) in catalogo:
        return "OK_CATALOGO"
    # modelo == ano de algum anúncio do par -> ano vazou
    if re.fullmatch(r"\d{1,4}", m):
        val = int(m)
        # ano de 4 dígitos que coincide com ano do anúncio
        if val in anos:
            return "ANO_VAZADO"
        # ano de 2 dígitos (34, 37...) que corresponde a 19xx do anúncio
        if val < 100 and (1900 + val) in anos:
            return "ANO_VAZADO"
        # número puro que não bate em ano nem catálogo: pode ser modelo real
        # (147, 911) ou lixo — marca pra revisão
        return "NUMERO_REVISAR"
    # modelo é uma marca conhecida (typo ou não) -> marca duplicada/errada
    if modelo_norm in marcas_catalogo or modelo_norm in _ALIASES_MARCA:
        return "MODELO_EH_MARCA"
    # typo de willys
    if re.search(r"WI?LL?I?Y?S|WYLL?IS", modelo_norm) and modelo_norm not in ("WILLYS",):
        return "TYPO_WILLYS"
    # grafia feia: hífens múltiplos ou marca colada com hífen
    if modelo_norm.count("-") >= 2 or modelo_norm.startswith("VW-"):
        return "GRAFIA_FEIA"
    # marca aparece dentro do modelo
    if marca_norm and marca_norm.split()[0] in modelo_norm.split():
        return "MARCA_NO_MODELO"
    # fuzzy bom -> provável só grafia
    melhor = _melhor_fuzzy(marca_norm, marcas_catalogo, 0.80)
    if melhor:
        modelos_marca = sorted({c[1] for c in catalogo if c[0] == melhor})
        if _melhor_fuzzy(modelo_norm, modelos_marca, 0.82):
            return "FUZZY_OK"
    return "SEM_MATCH"


def main() -> None:
    catalogo = carregar_catalogo()
    marcas_catalogo = sorted({c[0] for c in catalogo})

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT marca, modelo,
                       COUNT(*) AS n,
                       array_agg(DISTINCT ano) AS anos,
                       array_agg(DISTINCT titulo) AS titulos
                FROM anuncios
                GROUP BY marca, modelo
                """
            )
            rows = cur.fetchall()

    grupos: dict[str, list] = {}
    for r in rows:
        anos = {a for a in (r["anos"] or []) if a}
        cat = classificar(r["marca"], r["modelo"], anos, catalogo, marcas_catalogo)
        grupos.setdefault(cat, []).append(r)

    # Ordem de exibição: os problemáticos primeiro
    ordem = [
        "ZERO", "VAZIO", "ANO_VAZADO", "TYPO_WILLYS", "GRAFIA_FEIA",
        "MODELO_EH_MARCA", "MARCA_NO_MODELO", "NUMERO_REVISAR",
        "SEM_MATCH", "FUZZY_OK", "OK_CATALOGO",
    ]
    for cat in ordem:
        gs = grupos.get(cat, [])
        total = sum(g["n"] for g in gs)
        print(f"\n{'='*70}\n### {cat}  ({len(gs)} pares, {total} anúncios)\n{'='*70}")
        if cat in ("OK_CATALOGO", "FUZZY_OK"):
            continue  # não precisa listar título dos ok
        for g in sorted(gs, key=lambda x: -x["n"]):
            print(f"\n  [{g['n']}] marca={g['marca']!r} modelo={g['modelo']!r} anos={sorted(a for a in (g['anos'] or []) if a)}")
            for t in sorted(g["titulos"] or [])[:6]:
                print(f"       {t!r}")


if __name__ == "__main__":
    main()
