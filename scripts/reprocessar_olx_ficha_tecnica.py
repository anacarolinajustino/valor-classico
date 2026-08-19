"""
Reprocessamento retroativo de ficha técnica da OLX — amostra (2026-07-16).

Mesma motivação do reprocessamento do ML (`reprocessar_ml_ficha_tecnica.py`):
marca/modelo hoje vêm só de adivinhar o título, e a ficha técnica da página
de detalhe dá um valor estruturado mais confiável. Diferente do ML, porém,
a ficha da OLX exige Playwright + proxy residencial, e mede-se (2026-07-16)
que cada ficha consome sua PRÓPRIA sessão aquecida — a 2ª página de detalhe
navegada numa sessão já aquecida é bloqueada pela Cloudflare (ver docstring
de `buscar_ficha_tecnica` em `src/connectors/olx.py`). Isso torna o
reprocessamento completo (21.138 anúncios) uma tarefa de mais de um dia
rodando; por isso este script trabalha sobre uma AMOSTRA fixa, não a base
inteira.

Dois modos bem separados (não misture — ver por quê no código):
  - Dry-run (sem --apply): teste rápido e descartável, amostra aleatória
    ad-hoc de `--limit` anúncios (default 15), sem tocar no banco nem
    salvar nada em disco. Uso: validar a qualidade do parser antes de
    comprometer horas de execução.
  - --apply: roda sobre uma amostra FIXA e RETOMÁVEL de `--limit` anúncios
    (default 3000, sorteada uma vez e salva em `scratch_olx_amostra_reprocessamento.csv`).
    Cada anúncio é commitado no banco assim que processado (não no fim do
    script) e registrado em `scratch_olx_reprocessamento_progresso.csv` —
    se o processo for interrompido (o próprio motivo deste script existir:
    2026-07-16 perdemos um cálculo de custo por causa de um restart do
    VSCode), rodar de novo retoma de onde parou em vez de refazer tudo.

Uso:
    python scripts/reprocessar_olx_ficha_tecnica.py                  # smoke test dry-run, 15 anúncios ad-hoc
    python scripts/reprocessar_olx_ficha_tecnica.py --limit=30       # smoke test dry-run, N anúncios ad-hoc
    python scripts/reprocessar_olx_ficha_tecnica.py --apply          # amostra fixa de 3000, retomável, aplica no banco
    python scripts/reprocessar_olx_ficha_tecnica.py --apply --limit=500   # amostra fixa menor (só na 1ª vez que criar o arquivo)
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.connectors.olx import buscar_ficha_tecnica, _modelo_da_ficha
from src.pipeline.persistence import ANO_CORTE_CLASSICO, _connect

_LIMITE_DRYRUN_PADRAO = 15
_LIMITE_APPLY_PADRAO = 3000
_ARQUIVO_AMOSTRA = Path(__file__).parent.parent / "scratch_olx_amostra_reprocessamento.csv"
_ARQUIVO_PROGRESSO = Path(__file__).parent.parent / "scratch_olx_reprocessamento_progresso.csv"
_ARQUIVO_REMOVIDOS = Path(__file__).parent.parent / "scripts" / "olx_ficha_tecnica_removidos.csv"
_RATE_LIMIT_SEGUNDOS = 1.0


def _amostra_ad_hoc(n: int) -> list[dict]:
    """Amostra aleatória descartável — usada só no modo dry-run (smoke test)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, url, titulo, marca, modelo, ano FROM anuncios "
                "WHERE fonte = 'olx' ORDER BY RANDOM() LIMIT %s",
                (n,),
            )
            return cur.fetchall()


def _amostra_fixa(n: int) -> list[dict]:
    """Amostra fixa e retomável — sorteada uma vez, salva em disco, reusada em toda execução seguinte."""
    if _ARQUIVO_AMOSTRA.exists():
        with open(_ARQUIVO_AMOSTRA, encoding="utf-8") as f:
            ids = [int(linha.strip()) for linha in f if linha.strip()]
        print(f"Usando amostra fixa salva: {_ARQUIVO_AMOSTRA.name} ({len(ids)} ids)")
    else:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM anuncios WHERE fonte = 'olx' ORDER BY RANDOM() LIMIT %s", (n,)
                )
                ids = [r["id"] for r in cur.fetchall()]
        _ARQUIVO_AMOSTRA.write_text("\n".join(str(i) for i in ids) + "\n", encoding="utf-8")
        print(f"Nova amostra fixa sorteada e salva em {_ARQUIVO_AMOSTRA.name} ({len(ids)} ids)")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, url, titulo, marca, modelo, ano FROM anuncios WHERE id = ANY(%s) ORDER BY id",
                (ids,),
            )
            return cur.fetchall()


def _ids_ja_processados() -> set[int]:
    if not _ARQUIVO_PROGRESSO.exists():
        return set()
    with open(_ARQUIVO_PROGRESSO, encoding="utf-8") as f:
        return {int(row["id"]) for row in csv.DictReader(f)}


def _registrar_progresso(id_: int, resultado: str) -> None:
    novo = not _ARQUIVO_PROGRESSO.exists()
    with open(_ARQUIVO_PROGRESSO, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if novo:
            writer.writerow(["id", "resultado"])
        writer.writerow([id_, resultado])


def _decidir(r: dict, ficha: dict[str, str]) -> tuple[str, str, int]:
    """A partir da ficha técnica, decide (marca_nova, modelo_novo, ano_novo)."""
    marca_nova = ficha["MARCA"].upper()
    modelo_novo = _modelo_da_ficha(ficha) or (r["modelo"] or "")
    ano_novo = r["ano"]
    ano_raw = ficha.get("ANO", "")
    if ano_raw.isdigit() and len(ano_raw) == 4:
        ano_novo = int(ano_raw)
    return marca_nova, modelo_novo, ano_novo


def main() -> None:
    aplicar = "--apply" in sys.argv
    limite = _LIMITE_APPLY_PADRAO if aplicar else _LIMITE_DRYRUN_PADRAO
    for arg in sys.argv:
        if arg.startswith("--limit="):
            limite = int(arg.split("=", 1)[1])

    rows = _amostra_fixa(limite) if aplicar else _amostra_ad_hoc(limite)
    ja_processados = _ids_ja_processados() if aplicar else set()
    pendentes = [r for r in rows if r["id"] not in ja_processados]

    print(
        f"Modo: {'APLICAR (amostra fixa retomável)' if aplicar else 'dry-run (smoke test ad-hoc)'} | "
        f"amostra: {len(rows)} | já processados: {len(rows) - len(pendentes)} | pendentes: {len(pendentes)}\n"
    )

    atualizacoes = 0
    removidos = 0
    sem_ficha = 0
    sem_mudanca = 0
    removidos_csv_rows: list[list] = []

    with _connect() as conn:
        with conn.cursor() as cur:
            for i, r in enumerate(pendentes, 1):
                ficha = buscar_ficha_tecnica(r["url"])

                if not ficha or "MARCA" not in ficha:
                    sem_ficha += 1
                    if aplicar:
                        _registrar_progresso(r["id"], "sem_ficha")
                    print(f"  [{i}/{len(pendentes)}] #{r['id']} sem ficha técnica")
                    time.sleep(_RATE_LIMIT_SEGUNDOS)
                    continue

                marca_nova, modelo_novo, ano_novo = _decidir(r, ficha)

                if ano_novo and ano_novo > ANO_CORTE_CLASSICO:
                    removidos_csv_rows.append([r["id"], r["titulo"], r["url"], ano_novo])
                    if aplicar:
                        cur.execute("DELETE FROM anuncios WHERE id = %s", (r["id"],))
                        conn.commit()
                        _registrar_progresso(r["id"], "removido")
                    removidos += 1
                    print(f"  [{i}/{len(pendentes)}] #{r['id']} REMOVIDO (ficha revela ano {ano_novo} > corte {ANO_CORTE_CLASSICO})")
                elif (
                    marca_nova != (r["marca"] or "")
                    or modelo_novo != (r["modelo"] or "")
                    or ano_novo != r["ano"]
                ):
                    if aplicar:
                        cur.execute(
                            "UPDATE anuncios SET marca = %s, modelo = %s, ano = %s WHERE id = %s",
                            (marca_nova, modelo_novo, ano_novo, r["id"]),
                        )
                        conn.commit()
                        _registrar_progresso(r["id"], "atualizado")
                    atualizacoes += 1
                    print(
                        f"  [{i}/{len(pendentes)}] #{r['id']} marca: {r['marca']!r} -> {marca_nova!r} | "
                        f"modelo: {r['modelo']!r} -> {modelo_novo!r} | ano: {r['ano']} -> {ano_novo}"
                    )
                else:
                    sem_mudanca += 1
                    if aplicar:
                        _registrar_progresso(r["id"], "sem_mudanca")

                time.sleep(_RATE_LIMIT_SEGUNDOS)

    if removidos_csv_rows:
        novo = not _ARQUIVO_REMOVIDOS.exists()
        with open(_ARQUIVO_REMOVIDOS, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if novo:
                writer.writerow(["id", "titulo", "url", "ano_ficha"])
            writer.writerows(removidos_csv_rows)

    print(f"\nProcessados nesta rodada: {len(pendentes)}")
    print(f"Atualizações: {atualizacoes} | Removidos: {removidos} | Sem ficha: {sem_ficha} | Sem mudança: {sem_mudanca}")
    if not aplicar:
        print("\nDry-run — nada foi alterado no banco.")


if __name__ == "__main__":
    main()
