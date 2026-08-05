"""
Mede quanto as fontes externas cobrem da lacuna do catálogo canônico, e gera
candidatos revisáveis pro suplemento manual.

Cruza os pares (marca, modelo) do banco que NÃO estão no catálogo canônico
contra base_marcamodelo_intl.csv e vocabulario_geracao_trim.csv, usando três
estratégias em ordem decrescente de confiança:

    1. literal    — o par existe igual na fonte externa
    2. alias      — existe sob o nome em inglês (via aliases_intl.csv)
    3. prefixo    — o modelo do banco começa com um modelo da fonte, ou
                    vice-versa ('GALAXIE 500' <-> 'GALAXIE',
                    'SPRINTER 310' <-> 'SPRINTER')

Não altera nada no banco nem no catálogo. A saída `--candidatos` é um CSV no
formato de data/suplemento_manual.csv (marca,modelo,ano_min,ano_max) pra ser
TRIADO pela usuária — só a faixa de ano vem da fonte externa, e ela é a
faixa de produção MUNDIAL, que costuma ser mais larga que a brasileira.

Uso:
    python scripts/auditar_cobertura_externa.py
    python scripts/auditar_cobertura_externa.py --candidatos data/candidatos_intl.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.catalog.externo import evidencia_externa
from src.catalog.loader import carregar_catalogo
from src.pipeline.normalizer import normalizar_texto
from src.pipeline.persistence import _connect


def _pares_orfaos() -> list[tuple[str, str, int]]:
    """Pares do banco ausentes do catálogo canônico, do mais comum ao menos."""
    catalogo = carregar_catalogo()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT marca, modelo, COUNT(*) AS n
                FROM anuncios
                WHERE marca IS NOT NULL AND marca <> ''
                  AND modelo IS NOT NULL AND modelo <> ''
                GROUP BY marca, modelo
                ORDER BY n DESC
                """
            )
            rows = cur.fetchall()

    orfaos = []
    for r in rows:
        marca = normalizar_texto(r["marca"])
        modelo = normalizar_texto(r["modelo"])
        if (marca, modelo) not in catalogo:
            orfaos.append((marca, modelo, r["n"]))
    return orfaos


def auditar() -> tuple[list[dict], list[tuple[str, str, int]]]:
    """
    O cruzamento em si mora em `externo.evidencia_externa` — a mesma função
    que o painel de pendências usa, pra auditoria e tela nunca divergirem
    sobre o mesmo par.
    """
    cobertos: list[dict] = []
    descobertos: list[tuple[str, str, int]] = []

    for marca, modelo, n in _pares_orfaos():
        ev = evidencia_externa(marca, modelo)
        if not ev:
            descobertos.append((marca, modelo, n))
            continue
        cobertos.append(
            {
                "marca": marca,
                "modelo": modelo,
                "modelo_fonte": ev["modelo_fonte"],
                "estrategia": ev["estrategia"],
                "fonte": ev["fonte"],
                "ano_min": ev["ano_min"] if ev["ano_min"] is not None else "",
                "ano_max": ev["ano_max"] if ev["ano_max"] is not None else "",
                "n_anuncios": n,
                "suspeita": ev["suspeita"],
            }
        )

    return cobertos, descobertos


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidatos", type=Path, default=None,
                        help="grava os pares cobertos COM faixa de ano no formato "
                             "de suplemento_manual.csv (pra triagem manual)")
    args = parser.parse_args()

    cobertos, descobertos = auditar()
    total = len(cobertos) + len(descobertos)
    anuncios_cobertos = sum(c["n_anuncios"] for c in cobertos)
    anuncios_total = anuncios_cobertos + sum(n for _, _, n in descobertos)

    print(f"Pares órfãos do catálogo canônico: {total} ({anuncios_total} anúncios)")
    pct = 100 * len(cobertos) / total if total else 0
    print(f"Cobertos pelas fontes externas:    {len(cobertos)} ({pct:.0f}%) "
          f"— {anuncios_cobertos} anúncios")

    por_estrategia: dict[str, int] = defaultdict(int)
    for c in cobertos:
        por_estrategia[c["estrategia"]] += 1
    print("  por estratégia: " + ", ".join(
        f"{k}={v}" for k, v in sorted(por_estrategia.items())))

    com_ano = [c for c in cobertos if c["ano_min"] != ""]
    suspeitos = [c for c in com_ano if c["suspeita"]]
    print(f"  com faixa de ano utilizável:     {len(com_ano)} "
          f"({len(suspeitos)} marcados como suspeita de modelo truncado/curto)")

    print(f"\nSem cobertura: {len(descobertos)} pares — top 20:")
    for marca, modelo, n in sorted(descobertos, key=lambda x: -x[2])[:20]:
        print(f"  n={n:<4} {marca} {modelo}")

    if args.candidatos:
        args.candidatos.parent.mkdir(parents=True, exist_ok=True)
        with open(args.candidatos, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["marca", "modelo", "ano_min", "ano_max",
                               "modelo_fonte", "estrategia", "fonte", "n_anuncios",
                               "suspeita"])
            writer.writeheader()
            # Limpos primeiro; os suspeitos no fim, que é a ordem de revisão.
            writer.writerows(sorted(com_ano, key=lambda c: (bool(c["suspeita"]),
                                                            -c["n_anuncios"])))
        print(f"\ncandidatos gravados: {args.candidatos} ({len(com_ano)} linhas, "
              f"{len(suspeitos)} suspeitas no fim do arquivo)")
        print("REVISAR antes de mover pro suplemento_manual.csv — a faixa de ano é "
              "de produção mundial, não brasileira, e as linhas com `suspeita` "
              "indicam modelo truncado no BANCO (corrigir lá, não suplementar).")


if __name__ == "__main__":
    main()
