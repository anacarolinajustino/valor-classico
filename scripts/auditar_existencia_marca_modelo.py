"""
Auditoria de EXISTÊNCIA de marca/modelo (2026-07-21).

Cruza cada par (marca, modelo) distinto do banco contra o catálogo de
referência (data/base_marcamodelo.csv + suplemento manual do loader), pra
achar pares que não têm nenhuma evidência de existir. Não altera nada —
só gera relatório, com títulos de amostra pros pares sem match (pra dar
contexto real de onde veio o dado, sem precisar consultar o banco de novo).

Uso:
    python scripts/auditar_existencia_marca_modelo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.catalog.loader import carregar_catalogo, _melhor_fuzzy
from src.pipeline.normalizer import normalizar_texto
from src.pipeline.persistence import _connect


def main() -> None:
    catalogo = carregar_catalogo()
    marcas_catalogo = sorted({chave[0] for chave in catalogo})

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT marca, modelo, COUNT(*) AS n
                FROM anuncios
                GROUP BY marca, modelo
                ORDER BY n DESC
                """
            )
            rows = cur.fetchall()

        exatos = 0
        fuzzy_marca_ok = []
        sem_match = []

        for r in rows:
            marca = r["marca"] or ""
            modelo = r["modelo"] or ""
            n = r["n"]
            marca_norm = normalizar_texto(marca)
            modelo_norm = normalizar_texto(modelo)

            if (marca_norm, modelo_norm) in catalogo:
                exatos += 1
                continue

            melhor_marca = _melhor_fuzzy(marca_norm, marcas_catalogo, threshold=0.80)
            if melhor_marca:
                modelos_da_marca = sorted({chave[1] for chave in catalogo if chave[0] == melhor_marca})
                melhor_modelo = _melhor_fuzzy(modelo_norm, modelos_da_marca, threshold=0.80)
                if melhor_modelo:
                    fuzzy_marca_ok.append((marca, modelo, n, melhor_marca, melhor_modelo))
                    continue

            sem_match.append((marca, modelo, n))

        print(f"Total de pares marca/modelo distintos: {len(rows)}", file=sys.stderr)
        print(f"Match exato: {exatos}  Fuzzy: {len(fuzzy_marca_ok)}  Sem match: {len(sem_match)}", file=sys.stderr)

        with conn.cursor() as cur:
            for marca, modelo, n in sorted(sem_match, key=lambda x: -x[2]):
                cur.execute(
                    "SELECT titulo, fonte FROM anuncios WHERE marca = %s AND modelo = %s LIMIT 3",
                    (marca, modelo),
                )
                titulos = cur.fetchall()
                print(f"\n### n={n} marca={marca!r} modelo={modelo!r}")
                for t in titulos:
                    print(f"    [{t['fonte']}] {t['titulo']}")


if __name__ == "__main__":
    main()
