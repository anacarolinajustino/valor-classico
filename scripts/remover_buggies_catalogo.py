"""
Purga os BUGGIES do catálogo consagrado data/base_marcamodelo.csv (2026-07-22
— a usuária decidiu que buggy está fora do escopo do projeto; os anúncios já
foram apagados do banco por scripts/remover_buggies.py, e as entradas de buggy
já saíram do _SUPLEMENTO em loader.py; falta o base CSV).

Remove toda linha cuja:
  - marca é de buggy (ver `BUGGY_MARCAS` no normalizer: BUGGY, BUGWAY, BRM,
    BUGRE, FYBER, EMIS, EMISUL, GIANTS, MENON, RENO, "WAY BRASIL"); ou
  - modelo contém "BUGGY" (pega VW/BUGGY e afins sob marca de carro de verdade).

Faz backup do CSV (.bak com timestamp) antes de reescrever.

Uso:
    python scripts/remover_buggies_catalogo.py            # dry-run
    python scripts/remover_buggies_catalogo.py --apply    # backup + reescreve
"""
from __future__ import annotations

import csv
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.catalog.loader import CSV_PADRAO
from src.pipeline.normalizer import BUGGY_MARCAS, normalizar_texto


def _e_buggy(marca: str, modelo: str) -> bool:
    return normalizar_texto(marca) in BUGGY_MARCAS or "BUGGY" in normalizar_texto(modelo)


def main() -> None:
    aplicar = "--apply" in sys.argv

    with open(CSV_PADRAO, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        linhas = list(reader)

    # Índices das colunas marca/modelo (o header pode variar de ordem).
    i_marca = header.index("nome_marca")
    i_modelo = header.index("nome_modelo")

    manter, remover = [], []
    for row in linhas:
        marca = row[i_marca] if len(row) > i_marca else ""
        modelo = row[i_modelo] if len(row) > i_modelo else ""
        (remover if _e_buggy(marca, modelo) else manter).append(row)

    pares = sorted({(r[i_marca], r[i_modelo]) for r in remover})
    print(f"Linhas totais: {len(linhas)}  |  a remover: {len(remover)}  |  manter: {len(manter)}")
    print(f"Pares de buggy removidos ({len(pares)}):")
    for mk, md in pares:
        print(f"  {mk}/{md!r}")

    if not aplicar:
        print("\nDry-run — CSV não foi alterado. Rode com --apply pra reescrever.")
        return

    bak = CSV_PADRAO.with_suffix(f".csv.bak-{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(CSV_PADRAO, bak)
    print(f"\nBackup do CSV: {bak.name}")

    with open(CSV_PADRAO, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(manter)
    print(f"CSV reescrito sem buggies: {len(manter)} linhas + header.")


if __name__ == "__main__":
    main()
