"""
Fecha um mês da série histórica antes que a coleta seguinte o apague.

RODAR ANTES DE TODA COLETA NOVA. O upsert sobrescreve o preço de quem
continua no ar, então coletar agosto sem ter fechado julho torna o índice de
julho irreproduzível - ver o cabeçalho de src/pipeline/serie_historica.py.

O padrão é DIAGNOSTICAR, não fechar: mostra o que aconteceria e sai. Fechar
de verdade exige --aplicar.

Uso:
    python scripts/fechar_competencia.py                      # o que há na base
    python scripts/fechar_competencia.py 2026-07              # diagnóstico
    python scripts/fechar_competencia.py 2026-07 --aplicar    # fecha
    python scripts/fechar_competencia.py 2026-07 --aplicar --sem-purga
    python scripts/fechar_competencia.py 2026-07 --aplicar --refazer
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.serie_historica import (
    competencias_fechadas,
    competencias_na_base,
    diagnosticar,
    fechar,
)


def _panorama() -> None:
    print("NA BASE ATIVA (por mês da última vista)")
    linhas = competencias_na_base()
    if not linhas:
        print("   (vazia)")
    for l in linhas:
        print(f"   {l['competencia']}   {l['anuncios']:>7,} anúncios   "
              f"{l['fontes']:>2} fontes")

    print("\nJÁ FECHADAS (série histórica)")
    fechadas = competencias_fechadas()
    if not fechadas:
        print("   (nenhuma)")
    for l in fechadas:
        print(f"   {l['competencia']}   {l['anuncios']:>7,} anúncios   "
              f"{l['com_preco']:>7,} com preço   "
              f"visto de {l['visto_de']} a {l['visto_ate']}")

    if len(linhas) > 1:
        print("\n  Mais de um mês na base ativa: o minoritário é quase sempre")
        print("  anúncio morto que ainda conta nas estatísticas.")


def _mostrar(diag: dict) -> None:
    print(f"COMPETÊNCIA {diag['competencia']}\n")
    print(f"  entram no snapshot : {diag['vistos']:>7,} anúncios")
    print(f"  fontes coletadas   : {len(diag['fontes_coletadas'])}"
          f"  ({', '.join(diag['fontes_coletadas'][:6])}"
          f"{'...' if len(diag['fontes_coletadas']) > 6 else ''})")

    if diag["mortos"]:
        print(f"\n  SAEM da base ativa : {diag['mortos_total']:>7,} anúncios")
        print("  (fontes coletadas neste mês, mas estes anúncios não foram vistos)")
        for m in diag["mortos"][:10]:
            print(f"     {m['fonte']:<24}{m['n']:>6,}   última vista {m['visto_ate']}")
        if len(diag["mortos"]) > 10:
            print(f"     ... mais {len(diag['mortos']) - 10} fonte(s)")
    else:
        print("\n  SAEM da base ativa :       0")

    if diag["nao_coletadas"]:
        print(f"\n  INTOCADAS          : {diag['nao_coletadas_total']:>7,} anúncios")
        print("  (fontes sem nenhum anúncio neste mês - não foram coletadas, e")
        print("   apagá-las seria varrer a fonte inteira)")
        for f in diag["nao_coletadas"][:10]:
            print(f"     {f['fonte']:<24}{f['n']:>6,}   última vista {f['visto_ate']}")
        if len(diag["nao_coletadas"]) > 10:
            print(f"     ... mais {len(diag['nao_coletadas']) - 10} fonte(s)")

    if diag["ja_no_snapshot"]:
        print(f"\n  ATENÇÃO: {diag['competencia']} já tem "
              f"{diag['ja_no_snapshot']:,} anúncios no snapshot. "
              "Fechar de novo exige --refazer.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("competencia", nargs="?", help="AAAA-MM (sem isto, mostra o panorama)")
    p.add_argument("--aplicar", action="store_true",
                   help="fecha de verdade (sem isto, só diagnostica)")
    p.add_argument("--sem-purga", action="store_true",
                   help="grava o snapshot sem apagar os anúncios mortos")
    p.add_argument("--refazer", action="store_true",
                   help="sobrescreve um snapshot já existente")
    args = p.parse_args()

    if not args.competencia:
        _panorama()
        print("\nPasse a competência pra ver o diagnóstico dela.")
        return 0

    try:
        diag = diagnosticar(args.competencia)
    except ValueError as exc:
        print(f"Erro: {exc}")
        return 1

    _mostrar(diag)

    if not args.aplicar:
        print("\n" + "-" * 66)
        print("Diagnóstico - nada foi alterado. Use --aplicar pra fechar.")
        return 0

    if not diag["vistos"]:
        print("\nNada a fechar.")
        return 1

    try:
        r = fechar(args.competencia, purgar=not args.sem_purga, refazer=args.refazer)
    except ValueError as exc:
        print(f"\nErro: {exc}")
        return 1

    print("\n" + "-" * 66)
    print(f"FECHADA. {r['gravados']:,} anúncios no snapshot de {r['competencia']}, "
          f"{r['purgados']:,} removidos da base ativa.")
    if not r["purgou"]:
        print("Purga desligada: os anúncios mortos continuam contando nas "
              "estatísticas.")
    print("\nAgora a coleta nova pode rodar sem apagar este mês.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
