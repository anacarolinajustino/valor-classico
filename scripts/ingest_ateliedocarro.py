#!/usr/bin/env python3
"""
Ingestão batch completa do Ateliê do Carro → SQLite.

Spike do modelo "1 fonte/dia, revisita mensal": coleta TODOS os anúncios do
site, salva na tabela `anuncios` (upsert por fonte+url) e imprime as métricas
de custo da coleta (tempo total, latências, erros) em JSON.

Uso:
    python scripts/ingest_ateliedocarro.py
    python scripts/ingest_ateliedocarro.py --max-paginas 5   # rodada parcial
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

# Suprimir avisos de SSL (aceitável para spike/demo local)
warnings.filterwarnings("ignore")

# Adicionar raiz do projeto ao path para imports relativos funcionarem
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.connectors.ateliedocarro import coletar_completo
from src.pipeline import persistence


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingestão batch do Ateliê do Carro")
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

    metricas["banco"] = resultado
    print(json.dumps(metricas, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
