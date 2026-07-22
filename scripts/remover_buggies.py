"""
Remoção dos anúncios de BUGGY do banco (2026-07-22 — a usuária decidiu que
buggy tem variedade demais e nem é automóvel de verdade; tirados antes da
quarentena de verificação, agora apagados do banco de vez).

Escopo confirmado pela usuária ("Todos os buggies"):
  - marca == 'BUGGY' (marca-balde sem fabricante real);
  - qualquer modelo que contenha 'BUGGY' (VW/BUGGY, BUGRE, BRM, FYBER, EMIS,
    GLASPACBUGGY...);
  - os poucos anúncios de fabricante de buggy com outro modelo:
    BRM/M-11, BUGRE/V, FYBER/STAR.

Uso:
    python scripts/remover_buggies.py            # dry-run
    python scripts/remover_buggies.py --apply    # backup + DELETE
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.persistence import _connect

# Fabricantes de buggy com anúncio de modelo que não contém "Buggy".
_PARES_EXTRA = [("BRM", "M-11"), ("BUGRE", "V"), ("FYBER", "STAR")]

_WHERE = """
    UPPER(marca) = 'BUGGY'
    OR UPPER(modelo) LIKE '%BUGGY%'
    OR (UPPER(marca) = 'BRM'   AND UPPER(modelo) = 'M-11')
    OR (UPPER(marca) = 'BUGRE' AND UPPER(modelo) = 'V')
    OR (UPPER(marca) = 'FYBER' AND UPPER(modelo) = 'STAR')
"""


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT marca, COALESCE(modelo,'') AS modelo, COUNT(*) AS n "
                f"FROM anuncios WHERE {_WHERE} GROUP BY marca, COALESCE(modelo,'') "
                f"ORDER BY marca, modelo"
            )
            pares = cur.fetchall()

        total = sum(r["n"] for r in pares)
        print(f"Pares a apagar: {len(pares)}  |  anúncios: {total}")
        for r in pares:
            print(f"  {r['n']:>3}  {r['marca']}/{r['modelo']!r}")

        if not aplicar:
            print("\nDry-run — nada foi apagado. Rode com --apply pra remover.")
            return

        print("\nGerando backup antes de apagar...")
        caminho = fazer_backup()
        if caminho is None:
            print("ERRO: backup falhou — abortando.")
            sys.exit(1)
        print(f"Backup criado: {caminho}")

        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM anuncios WHERE {_WHERE}")
            apagados = cur.rowcount
        print(f"\nApagados: {apagados} anúncios (commit ao sair do bloco).")


if __name__ == "__main__":
    main()
