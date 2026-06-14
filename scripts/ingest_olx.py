#!/usr/bin/env python3
"""
Ingestão batch da OLX → SQLite.

Modo default: navega a categoria /autos-e-pecas/carros-vans-e-utilitarios
com filtro de ano (sf=1&ae=2000) e persiste no SQLite.

Uso:
    python scripts/ingest_olx.py                              # categoria completa (default)
    python scripts/ingest_olx.py --max-paginas 10            # limite de páginas (teste)
    python scripts/ingest_olx.py --modo sweep                # sweep por termos (fallback)
    python scripts/ingest_olx.py --modo termo --termo fusca  # termo único
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

from src.connectors.olx import TERMOS_SWEEP, coletar_categoria, coletar_completo, coletar_sweep
from src.pipeline import persistence
from src.pipeline.persistence import ANO_CORTE_CLASSICO as _ANO

LOG_CSV = Path(__file__).parent.parent / "data" / "coletas_log.csv"


def _gravar_csv(metricas: dict) -> None:
    escrever_cabecalho = not LOG_CSV.exists()
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=metricas.keys())
        if escrever_cabecalho:
            writer.writeheader()
        writer.writerow(metricas)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingestão batch da OLX")
    parser.add_argument(
        "--modo", choices=["categoria", "sweep", "termo"], default="categoria",
        help="Estratégia de coleta (default: categoria).",
    )
    parser.add_argument(
        "--max-paginas", type=int, default=200,
        help="Teto de páginas no modo categoria ou termo (default: 200).",
    )
    parser.add_argument(
        "--max-paginas-por-termo", type=int, default=20,
        help="Teto de páginas por termo no modo sweep (default: 20).",
    )
    parser.add_argument(
        "--termo", type=str, default="carros antigos",
        help="Termo de busca (apenas para --modo termo).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    persistence.init_db()

    if args.modo == "categoria":
        logging.info(
            "Modo: categoria — até %d páginas, ano ≤ %d",
            args.max_paginas, _ANO,
        )
        anuncios, metricas = coletar_categoria(max_paginas=args.max_paginas)

    elif args.modo == "sweep":
        logging.info(
            "Modo: sweep — %d termos, até %d páginas/termo",
            len(TERMOS_SWEEP), args.max_paginas_por_termo,
        )
        anuncios, metricas = coletar_sweep(max_paginas_por_termo=args.max_paginas_por_termo)

    else:  # termo
        logging.info(
            "Modo: termo '%s' — até %d páginas",
            args.termo, args.max_paginas,
        )
        anuncios, metricas = coletar_completo(max_paginas=args.max_paginas, termo=args.termo)

    resultado = persistence.upsert_anuncios(anuncios)

    metricas["banco_novos"] = resultado["novos"]
    metricas["banco_atualizados"] = resultado["atualizados"]

    # csv não suporta list — serializa termos se presente
    if "termos" in metricas:
        metricas["termos"] = json.dumps(metricas["termos"], ensure_ascii=False)

    _gravar_csv(metricas)
    print(json.dumps(metricas, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
