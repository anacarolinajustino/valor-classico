"""
Mede o que o fatiamento do ML alcança, comparando com o mês em que a fonte
ainda era coletável por paginação.

A pergunta não é "quantos anúncios vieram" - é se a fatia cobre a MESMA
população. Volume parecido com composição diferente seria pior que volume
menor, porque entraria na mediana sem avisar.

Julho é a régua: 5.345 anúncios coletados antes do muro de 17/08. Não dá pra
esperar reencontrar todos (metade morre por mês, medido em 42% de
sobrevivência), então o que importa é a FORMA - distribuição por ano, marca e
preço - e não a interseção.

Uso:
    python scripts/cobertura_ml_fatiado.py
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(RAIZ / ".env")

import psycopg2
import psycopg2.extras

ESTADO = RAIZ / "data" / ".ml_fatiado.json"


def _julho() -> list[dict]:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT url, marca, modelo, ano, preco FROM anuncios_snapshot
               WHERE competencia = '2026-07' AND fonte = 'mercadolivre'"""
        )
        return [dict(r) for r in cur.fetchall()]


def _perfil(linhas: list[dict], rotulo: str) -> dict:
    precos = [float(l["preco"]) for l in linhas if l.get("preco")]
    anos = [l["ano"] for l in linhas if l.get("ano")]
    marcas = Counter(l["marca"] for l in linhas if l.get("marca"))
    print(f"\n{rotulo}")
    print(f"   anúncios     {len(linhas):>7,}")
    if precos:
        print(f"   mediana      R$ {st.median(precos):>10,.0f}")
        print(f"   quartis      R$ {sorted(precos)[len(precos)//4]:>10,.0f}"
              f"  /  R$ {sorted(precos)[3*len(precos)//4]:,.0f}")
    if anos:
        print(f"   ano mediano  {int(st.median(anos))}")
    print(f"   marcas       {len(marcas)} distintas; "
          f"top: {', '.join(f'{m} {n}' for m, n in marcas.most_common(5))}")
    return {"precos": precos, "anos": anos, "marcas": marcas, "n": len(linhas)}


def main() -> int:
    if not ESTADO.exists():
        raise SystemExit(f"Nada em {ESTADO}. Rode antes o coletar_ml_fatiado.py.")
    novos = json.loads(ESTADO.read_text(encoding="utf-8"))
    julho = _julho()

    pj = _perfil(julho, "JULHO (paginação, antes do muro)")
    pn = _perfil(novos, "AGORA (fatiamento pelo Unlocker)")

    print("\n" + "=" * 62)
    print(f"volume: {pn['n'] / pj['n']:.0%} do que julho tinha")
    if pj["precos"] and pn["precos"]:
        dj, dn = st.median(pj["precos"]), st.median(pn["precos"])
        print(f"mediana: R$ {dj:,.0f} -> R$ {dn:,.0f}  ({(dn - dj) / dj:+.1%})")
        print("  (a mediana é o que entra na curva - desvio grande aqui")
        print("   significa que a fatia pegou outra população)")

    # Marca a marca: onde a composição mudou de fato.
    print("\ncomposição por marca (participação, julho -> agora):")
    for marca, nj in pj["marcas"].most_common(8):
        pj_pct = nj / pj["n"]
        pn_pct = pn["marcas"].get(marca, 0) / max(pn["n"], 1)
        print(f"   {marca:<16}{pj_pct:>6.1%} -> {pn_pct:>6.1%}"
              f"   ({pn['marcas'].get(marca, 0)} anúncios)")

    urls_julho = {l["url"] for l in julho}
    reencontrados = sum(1 for a in novos if a["url"] in urls_julho)
    print(f"\nreencontrados de julho: {reencontrados:,} "
          f"({reencontrados / max(len(novos), 1):.0%} do que veio agora)")
    print("  (baixo é esperado: 42% de sobrevivência ao mês, medido em 18/08)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
