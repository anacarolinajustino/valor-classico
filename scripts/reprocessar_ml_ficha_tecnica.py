"""
Reprocessamento retroativo de ficha técnica do Mercado Livre (2026-07-16).

Os 5.403 anúncios do ML no banco foram coletados em 2026-07-14 — um dia
ANTES do ajuste que passou a enriquecer marca/modelo/ano via ficha técnica
da página de detalhe (commit 391fce0, 2026-07-15). Na época, marca/modelo
vinham só de adivinhar o título, o que falha quando ele não começa pela
marca (ex.: "AP 2000..." é código de motor, não marca — a marca real só
aparece na ficha técnica). Este script busca a ficha técnica de cada
anúncio já salvo (via URL no banco) e atualiza marca/modelo/ano quando
disponível — mesma lógica usada na coleta ao vivo
(`_enriquecer_com_ficha_tecnica`).

Se a ficha revelar ano fora do corte de clássico (> ANO_CORTE_CLASSICO), o
anúncio é REMOVIDO do banco — mesma regra que `upsert_anuncios` aplica na
coleta (esse registro nunca teria sido salvo se a ficha tivesse sido
consultada na hora). Os removidos são salvos em CSV antes de apagar, para
auditoria.

Uso:
    python scripts/reprocessar_ml_ficha_tecnica.py                  # dry-run (só relatório)
    python scripts/reprocessar_ml_ficha_tecnica.py --limit 20       # amostra pequena, dry-run
    python scripts/reprocessar_ml_ficha_tecnica.py --apply          # aplica as mudanças
"""
from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.connectors.mercadolivre import _FICHA_RATE_LIMIT, _buscar_ficha_tecnica
from src.pipeline.persistence import ANO_CORTE_CLASSICO, _connect

_REMOVIDOS_CSV = Path(__file__).parent.parent / "scripts" / "ml_ficha_tecnica_removidos.csv"


def main() -> None:
    aplicar = "--apply" in sys.argv
    limite = None
    for arg in sys.argv:
        if arg.startswith("--limit="):
            limite = int(arg.split("=", 1)[1])

    with _connect() as conn:
        with conn.cursor() as cur:
            sql = "SELECT id, url, titulo, marca, modelo, ano FROM anuncios WHERE fonte = 'mercadolivre' ORDER BY id"
            if limite:
                sql += f" LIMIT {limite}"
            cur.execute(sql)
            rows = cur.fetchall()

    print(f"Total de anúncios ML a verificar: {len(rows)}")

    atualizacoes: list[tuple[int, str, str, str, str, object, object]] = []
    remover: list[tuple[int, str, str, int]] = []  # id, titulo, url, ano_novo
    sem_ficha = 0
    erros = 0

    inicio = time.monotonic()
    for i, r in enumerate(rows, 1):
        try:
            ficha = _buscar_ficha_tecnica(r["url"])
        except Exception as exc:
            print(f"  erro #{r['id']}: {exc}")
            erros += 1
            time.sleep(_FICHA_RATE_LIMIT)
            continue

        if not ficha or "MARCA" not in ficha or "MODELO" not in ficha:
            sem_ficha += 1
            time.sleep(_FICHA_RATE_LIMIT)
            continue

        marca_nova = ficha["MARCA"].upper()
        modelo_novo = ficha["MODELO"].upper()
        ano_novo = r["ano"]
        ano_raw = ficha.get("ANO", "")
        if re.fullmatch(r"(19|20)\d{2}", ano_raw):
            ano_novo = int(ano_raw)

        if ano_novo and ano_novo > ANO_CORTE_CLASSICO:
            remover.append((r["id"], r["titulo"], r["url"], ano_novo))
        elif (
            marca_nova != (r["marca"] or "")
            or modelo_novo != (r["modelo"] or "")
            or ano_novo != r["ano"]
        ):
            atualizacoes.append(
                (r["id"], r["marca"] or "", marca_nova, r["modelo"] or "", modelo_novo, r["ano"], ano_novo)
            )

        if i % 100 == 0:
            decorrido = time.monotonic() - inicio
            print(f"  progresso: {i}/{len(rows)} ({decorrido:.0f}s decorridos)")

        time.sleep(_FICHA_RATE_LIMIT)

    print(f"\nSem ficha técnica disponível (mantido como está): {sem_ficha}")
    print(f"Erros de requisição: {erros}")
    print(f"Atualizações de marca/modelo/ano: {len(atualizacoes)}")
    print(f"Remoções (ficha revelou ano > corte clássico {ANO_CORTE_CLASSICO}): {len(remover)}")

    print("\n--- Amostra de até 20 atualizações ---")
    for id_, mv, mn, modv, modn, av, an in atualizacoes[:20]:
        print(f"  #{id_} marca: {mv!r} -> {mn!r} | modelo: {modv!r} -> {modn!r} | ano: {av} -> {an}")

    print("\n--- Amostra de até 20 remoções ---")
    for id_, titulo, _url, ano in remover[:20]:
        print(f"  #{id_} {titulo!r} -> ano da ficha {ano} (fora do corte)")

    if not aplicar:
        print("\nDry-run — nada foi alterado. Rode com --apply pra gravar as mudanças.")
        return

    if remover:
        with open(_REMOVIDOS_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "titulo", "url", "ano_ficha"])
            writer.writerows(remover)
        print(f"\nBackup dos removidos salvo em {_REMOVIDOS_CSV}")

    print(f"\nAplicando {len(atualizacoes)} atualizações e {len(remover)} remoções...")
    with _connect() as conn:
        with conn.cursor() as cur:
            for id_, _mv, mn, _modv, modn, _av, an in atualizacoes:
                cur.execute(
                    "UPDATE anuncios SET marca = %s, modelo = %s, ano = %s WHERE id = %s",
                    (mn, modn, an, id_),
                )
            for id_, _titulo, _url, _ano in remover:
                cur.execute("DELETE FROM anuncios WHERE id = %s", (id_,))
    print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
