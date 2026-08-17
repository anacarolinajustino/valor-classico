"""
Roda a coleta mensal de todas as fontes, em sequência, com log.

O painel coleta uma fonte por vez, por botão. Pra a rodada mensal isso são 33
cliques e nenhum registro do conjunto - daí este script.

ANTES DE RODAR: fechar a competência anterior.
    python scripts/fechar_competencia.py AAAA-MM --aplicar
Sem isso a coleta sobrescreve os preços do mês passado sem deixar cópia (ver
docs/serie_historica.md).

Uma fonte que falha NÃO derruba a rodada: o erro é registrado e a próxima
começa. Fonte quebrada é rotina aqui - site sai do ar, muda o HTML, bloqueia
por um dia - e perder as outras 32 por causa de uma seria pior.

O backup sai UMA vez, no fim. O painel faz um por coleta, o que numa rodada
de 33 fontes daria 260 MB de dumps quase idênticos.

Uso:
    python scripts/coletar_todas.py                    # todas
    python scripts/coletar_todas.py --so olx,webmotors # algumas
    python scripts/coletar_todas.py --pular olx        # todas menos
    python scripts/coletar_todas.py --listar
"""
from __future__ import annotations

import argparse
import importlib
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from app import CONNECTOR_MODULES
from src.pipeline.backup import fazer_backup
from src.pipeline.persistence import upsert_anuncios

# As grandes por último: são as caras (a OLX passa por proxy pago) e as
# demoradas. Se algo estiver quebrado no ambiente, quebra numa loja pequena
# em segundos, e não depois de meia hora de scraping.
PESADAS = ["webmotors", "mercadolivre", "icarros", "olx"]


def ordem_de_coleta(fontes: list[str]) -> list[str]:
    leves = sorted(f for f in fontes if f not in PESADAS)
    return leves + [f for f in PESADAS if f in fontes]


def coletar_uma(fonte: str) -> dict:
    inicio = time.time()
    mod = importlib.import_module(CONNECTOR_MODULES[fonte])
    anuncios, metricas = mod.coletar_completo()
    resultado = upsert_anuncios(anuncios)
    return {
        "fonte": fonte,
        "coletados": len(anuncios),
        "novos": resultado.get("novos", 0),
        "atualizados": resultado.get("atualizados", 0),
        "descartados": sum(v for k, v in resultado.items() if k.startswith("descartados")),
        "segundos": time.time() - inicio,
        "metricas": metricas,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--so", help="lista separada por vírgula")
    p.add_argument("--pular", help="lista separada por vírgula")
    p.add_argument("--listar", action="store_true")
    args = p.parse_args()

    todas = sorted(CONNECTOR_MODULES)
    if args.listar:
        print(f"{len(todas)} fontes: {', '.join(todas)}")
        return 0

    fontes = todas
    if args.so:
        pedidas = [f.strip() for f in args.so.split(",") if f.strip()]
        desconhecidas = [f for f in pedidas if f not in CONNECTOR_MODULES]
        if desconhecidas:
            print(f"Fonte desconhecida: {', '.join(desconhecidas)}")
            return 1
        fontes = pedidas
    if args.pular:
        fora = {f.strip() for f in args.pular.split(",")}
        fontes = [f for f in fontes if f not in fora]

    fontes = ordem_de_coleta(fontes)
    print(f"COLETA MENSAL — {len(fontes)} fontes — início {datetime.now():%H:%M:%S}")
    print(f"ordem: leves primeiro, pesadas por último ({', '.join(PESADAS)})\n")

    ok, falhas = [], []
    t0 = time.time()
    for i, fonte in enumerate(fontes, 1):
        print(f"[{i}/{len(fontes)}] {fonte} ...", end=" ", flush=True)
        try:
            r = coletar_uma(fonte)
            ok.append(r)
            print(f"{r['coletados']:>5} coletados  "
                  f"{r['novos']:>4} novos  {r['atualizados']:>5} atualizados  "
                  f"{r['segundos']:>6.0f}s")
        except Exception as exc:
            falhas.append({"fonte": fonte, "erro": str(exc),
                           "trace": traceback.format_exc()})
            print(f"FALHOU — {type(exc).__name__}: {str(exc)[:90]}")

    print("\n" + "=" * 72)
    print(f"FIM — {time.time() - t0:.0f}s  ({(time.time() - t0) / 60:.0f} min)")
    print(f"  {len(ok)} fontes ok, {sum(r['coletados'] for r in ok):,} anúncios coletados")
    print(f"  {sum(r['novos'] for r in ok):,} novos, "
          f"{sum(r['atualizados'] for r in ok):,} atualizados")

    if falhas:
        print(f"\n  {len(falhas)} FALHARAM:")
        for f in falhas:
            print(f"     {f['fonte']:<26}{f['erro'][:70]}")
        print("\n  Uma fonte que falhou fica com os anúncios do mês passado na")
        print("  base, e eles serão purgados ao fechar a competência — o que é")
        print("  certo se ela morreu, e errado se foi só um erro passageiro.")
        print("  Rode de novo com --so <fonte> antes de fechar o mês.")

    try:
        caminho = fazer_backup()
        print(f"\nBackup: {caminho}")
    except Exception as exc:
        print(f"\nBackup falhou: {exc}")

    print("\nPróximo passo: conferir o painel e fechar a competência quando "
          "a rodada estiver completa.")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
