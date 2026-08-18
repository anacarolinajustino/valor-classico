"""
Exporta uma competência do snapshot pra um CSV.gz autônomo, fora do banco.

O snapshot já é imutável dentro do Postgres, e o pg_dump noturno o inclui.
Isto é a terceira cópia, e existe por um motivo específico: um dump do banco
inteiro só se lê restaurando o banco inteiro. Um CSV rotulado por competência
se abre em qualquer lugar, daqui a anos, sem depender do esquema atual - e é
esse o ponto de guardar um mês que talvez precise voltar.

Uso:
    python scripts/exportar_snapshot.py 2026-07
    python scripts/exportar_snapshot.py 2026-07 --destino outra/pasta
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(RAIZ / ".env")

from src.pipeline.persistence import _connect

COLUNAS = ["competencia", "fonte", "url", "titulo", "marca", "modelo", "versao",
           "geracao", "motor", "obs", "ano", "preco", "primeira_vista", "ultima_vista"]


def exportar(competencia: str, destino: Path) -> dict:
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / f"snapshot_{competencia}.csv.gz"
    manifesto = destino / f"snapshot_{competencia}.manifesto.json"

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(COLUNAS)} FROM anuncios_snapshot "
            "WHERE competencia = %s ORDER BY fonte, url",
            (competencia,),
        )
        linhas = cur.fetchall()

    if not linhas:
        raise SystemExit(f"Nada no snapshot de {competencia}.")

    # newline="" é obrigatório: sem isso o csv do Windows grava \r\r\n e o
    # arquivo lido em outro sistema ganha uma linha em branco por registro.
    with gzip.open(arquivo, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        for r in linhas:
            w.writerow({c: r[c] for c in COLUNAS})

    h = hashlib.sha256(arquivo.read_bytes()).hexdigest()
    por_fonte: dict[str, int] = {}
    for r in linhas:
        por_fonte[r["fonte"]] = por_fonte.get(r["fonte"], 0) + 1

    info = {
        "competencia": competencia,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "anuncios": len(linhas),
        "arquivo": arquivo.name,
        "sha256": h,
        "bytes": arquivo.stat().st_size,
        "por_fonte": dict(sorted(por_fonte.items(), key=lambda kv: -kv[1])),
    }
    manifesto.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return info


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("competencia", help="AAAA-MM")
    p.add_argument("--destino", default=str(RAIZ / "backups" / "snapshots"))
    args = p.parse_args()

    info = exportar(args.competencia, Path(args.destino))
    print(f"{info['anuncios']:,} anúncios -> {info['arquivo']}  "
          f"({info['bytes'] / 1e6:.1f} MB)")
    print(f"sha256 {info['sha256'][:16]}...")
    print("por fonte:", ", ".join(f"{k} {v:,}" for k, v in
                                  list(info["por_fonte"].items())[:6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
