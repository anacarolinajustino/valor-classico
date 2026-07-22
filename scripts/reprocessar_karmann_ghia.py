"""
Correção pontual do Karmann Ghia + grafia "Guia"/"Ghia" (auditoria 2026-07-22,
continuação da 3ª passada de grafia — a usuária apontou "caso semelhante no
Karmann Ghia").

O mapeamento de MODELO já existia (_MODELO_ABREVIACAO: KARMANN-GUIA/KARMANN
GHIA -> KARMANN-GHIA); o que sobrou foram parses quebrados que fragmentavam o
grupo, todos curados por id lendo o título original:

  - modelo='KARMANN' solto com o resto do nome jogado na versão (título com o
    nome duplicado/colado: "Karmann GhiaKarmann Ghia", "Karmann GhiaType 34");
  - versão repetindo o nome do modelo ("Karmann Ghia");
  - "TC 71" (o 71 é o ano) fragmentando o grupo do TC;
  - Karmann Ghia "Type 34" cujo "34" virou ANO (1934, impossível: o carro é de
    1961+), quando é a designação da linha (Type 34, o "Razão").

Bônus da mesma grafia: Ford Del Rey "Guia" -> "Ghia" (trim, não Karmann, mas é
a mesma variação de grafia Guia/Ghia).

Fora de escopo de propósito: Kombi "Karmann"/"Karmanguia" (é a conversão
camper da Karmann, não o Karmann Ghia — modelo KOMBI está certo).

Uso:
    python scripts/reprocessar_karmann_ghia.py            # dry-run
    python scripts/reprocessar_karmann_ghia.py --apply    # backup + aplica
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.persistence import _connect

# Sentinela: campo não muda (só mexe no que o override declara).
_MANTER = object()


def _ov(modelo=_MANTER, versao=_MANTER, ano=_MANTER):
    return {"modelo": modelo, "versao": versao, "ano": ano}


OVERRIDES: dict[int, dict] = {
    # "Volkswagen Karmann GhiaKarmann Ghia 1600" — nome duplicado/colado.
    27: _ov(modelo="KARMANN-GHIA", versao=None),
    # "Karmann GhiaType 34" — Karmann Ghia Type 34; o "34" virou ano=1934.
    20: _ov(modelo="KARMANN-GHIA", versao="TYPE 34", ano=None),
    # "Karmann-guia 1969 Karmann Ghia" — versão repete o modelo.
    36662: _ov(versao=None),
    # "Karmann-ghia Tc 1971/71" — o "71" na versão é o ano.
    35106: _ov(versao="TC"),
    # Ford Del Rey "Guia" -> "Ghia" (mesma grafia Guia/Ghia).
    35457: _ov(versao="GHIA"),
    37540: _ov(versao="GHIA"),
}


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, marca, modelo, versao, ano FROM anuncios WHERE id = ANY(%s) ORDER BY id",
                (list(OVERRIDES),),
            )
            rows = {r["id"]: r for r in cur.fetchall()}

        mudancas = []  # (id, campo, de, para)
        finais = {}    # id -> (modelo, versao, ano)
        for id_, ov in OVERRIDES.items():
            r = rows.get(id_)
            if r is None:
                print(f"AVISO: id {id_} não encontrado — pulando.")
                continue
            modelo_n = r["modelo"] if ov["modelo"] is _MANTER else ov["modelo"]
            versao_n = r["versao"] if ov["versao"] is _MANTER else ov["versao"]
            ano_n = r["ano"] if ov["ano"] is _MANTER else ov["ano"]
            finais[id_] = (modelo_n, versao_n, ano_n)
            for campo, atual, novo in (
                ("modelo", r["modelo"], modelo_n),
                ("versao", r["versao"], versao_n),
                ("ano", r["ano"], ano_n),
            ):
                if atual != novo:
                    mudancas.append((id_, campo, atual, novo))

        print(f"Anúncios afetados: {len(finais)}  |  campos alterados: {len(mudancas)}")
        for id_, campo, de, para in mudancas:
            print(f"  #{id_} {campo}: {de!r} -> {para!r}")

        if not aplicar:
            print("\nDry-run — nada foi alterado. Rode com --apply pra gravar.")
            return

        print("\nGerando backup antes de aplicar...")
        caminho = fazer_backup()
        if caminho is None:
            print("ERRO: backup falhou — abortando.")
            sys.exit(1)
        print(f"Backup criado: {caminho}")

        with conn.cursor() as cur:
            for id_, (modelo_n, versao_n, ano_n) in finais.items():
                cur.execute(
                    "UPDATE anuncios SET modelo = %s, versao = %s, ano = %s WHERE id = %s",
                    (modelo_n, versao_n, ano_n, id_),
                )
        print(f"Concluído: {len(finais)} anúncios atualizados (commit ao sair do bloco).")


if __name__ == "__main__":
    main()
