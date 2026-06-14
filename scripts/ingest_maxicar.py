#!/usr/bin/env python3
"""
Ingestão batch completa do Maxicar → SQLite.

Passe único: o WooCommerce exibe preço+título na listagem, sem necessidade
de buscar páginas de detalhe. Mais rápido que ateliedocarro.

Uso:
    python scripts/ingest_maxicar.py
    python scripts/ingest_maxicar.py --max-paginas 5   # rodada parcial
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.connectors.maxicar import coletar_completo
from src.pipeline import persistence

LOG_CSV = Path(__file__).parent.parent / "data" / "coletas_log.csv"


def _gravar_csv(metricas: dict) -> None:
    escrever_cabecalho = not LOG_CSV.exists()
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=metricas.keys())
        if escrever_cabecalho:
            writer.writeheader()
        writer.writerow(metricas)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingestão batch do Maxicar")
    parser.add_argument(
        "--max-paginas", type=int, default=100,
        help="Teto de páginas da listagem a percorrer (default: 100)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    persistence.init_db()
    anuncios, metricas = coletar_completo(max_paginas=args.max_paginas)
    resultado = persistence.upsert_anuncios(anuncios)

    metricas["banco_novos"] = resultado["novos"]
    metricas["banco_atualizados"] = resultado["atualizados"]

    _gravar_csv(metricas)
    print(json.dumps(metricas, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
