"""
Remoção dos anúncios de HOT ROD do banco (2026-07-23 — a usuária decidiu que
hot rod, assim como o buggy, está fora do escopo: é carro fortemente
customizado, não um clássico de fábrica).

Diferente do buggy, hot rod NÃO é marca (são Fords dos anos 30, Chevrolets,
Oldsmobiles, Hudsons... reais), então é identificado pela palavra-chave no
TÍTULO (onde quase sempre aparece), na versão ou no modelo. Cobre as grafias
"hot rod", "hotrod" e "hot-rod". Auditado em 2026-07-23: 48 anúncios, nenhum
falso positivo. A partir de agora `upsert_anuncios` também descarta hot rod já
na coleta (ver `_e_hot_rod`), então nem voltam num scrape futuro.

Uso:
    python scripts/remover_hot_rods.py            # dry-run
    python scripts/remover_hot_rods.py --apply    # backup + DELETE
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.persistence import _connect

# Casa "hot rod" / "hotrod" / "hot-rod" no título, na versão ou no modelo.
_WHERE = """
    UPPER(titulo) LIKE '%HOT ROD%' OR UPPER(titulo) LIKE '%HOTROD%' OR UPPER(titulo) LIKE '%HOT-ROD%'
    OR UPPER(COALESCE(modelo,'')) LIKE '%HOT ROD%' OR UPPER(COALESCE(modelo,'')) LIKE '%HOTROD%' OR UPPER(COALESCE(modelo,'')) LIKE '%HOT-ROD%'
    OR UPPER(COALESCE(versao,'')) LIKE '%HOT ROD%' OR UPPER(COALESCE(versao,'')) LIKE '%HOTROD%' OR UPPER(COALESCE(versao,'')) LIKE '%HOT-ROD%'
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
