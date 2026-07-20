"""
Reprocessamento retroativo: move "lista agregada" de VERSAO pra OBS
(auditoria 2026-07-20, rodada 2).

Alguns anúncios (majoritariamente OLX) têm versão com vários trims que o
próprio vendedor listou juntos no título como alternativas ("Opala L/SL/SS",
"Chevette L / SL / SL/e / DL / SE") — confirmado comparando com a URL
original do OLX, que já reflete o título tal como o vendedor digitou. Não há
"versão real" pra extrair do título porque o título JÁ É a lista; buscar lá
não ajuda (hipótese original descartada após investigação).

Critério pra identificar lista (vs. trim composto legítimo, tipo "Custom
Deluxe" ou "Geração I GTS"):versão com 3+ tokens onde TODOS os tokens já
aparecem, em algum outro anúncio do MESMO (marca, modelo), como versão de
UM token só. Isso é forte evidência de que cada token é um trim real e
independente sendo listado junto, não um nome composto. "GERACAO" nunca
entra aqui (decisão da usuária 2026-07-20: geração é parte da versão).

Esse critério é deliberadamente conservador: uma primeira tentativa
estatística mais frouxa (exigindo só 2+ tokens atestados) confundiu trims
compostos reais ("Gol GTI Turbo", "Gol Geração I GTS", "Veraneio Custom
Deluxe") com listas — o critério final evita esse falso positivo aceitando
capturar menos casos com confiança maior.

Uso:
    python scripts/reprocessar_lista_agregada.py            # dry-run (relatório)
    python scripts/reprocessar_lista_agregada.py --apply    # backup + aplica
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.persistence import _connect


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, marca, modelo, versao, obs FROM anuncios WHERE versao IS NOT NULL"
            )
            rows = cur.fetchall()

        print(f"Anúncios com versão preenchida: {len(rows)}")

        atestados: dict[tuple[str, str], set[str]] = defaultdict(set)
        for r in rows:
            toks = r["versao"].split()
            if len(toks) == 1:
                atestados[(r["marca"], r["modelo"])].add(toks[0])

        mudancas: list[tuple[int, str, str, str, str, str | None]] = []
        for r in rows:
            versao = r["versao"]
            toks = versao.split()
            if "GERACAO" in toks or len(toks) < 3:
                continue
            at = atestados[(r["marca"], r["modelo"])]
            if all(t in at for t in toks):
                obs_novo = f"{r['obs']} {versao}".strip() if r["obs"] else versao
                mudancas.append((r["id"], r["marca"], r["modelo"], versao, obs_novo, r["obs"]))

        print(f"Anúncios reclassificados (versão -> obs): {len(mudancas)}")

        grupos: dict[tuple[str, str, str], int] = defaultdict(int)
        for _id, marca, modelo, versao, _obs_novo, _obs_velho in mudancas:
            grupos[(marca, modelo, versao)] += 1
        print(f"Grupos distintos: {len(grupos)}")
        for (marca, modelo, versao), n in sorted(grupos.items(), key=lambda kv: -kv[1]):
            print(f"  {n:4d}x  [{marca}] {modelo} versao={versao!r}")

        print("\n--- Amostra de 10 mudanças ---")
        for id_, marca, modelo, versao, obs_novo, obs_velho in mudancas[:10]:
            print(f"  #{id_} [{marca}] {modelo} versao={versao!r} -> obs={obs_novo!r} (obs antes: {obs_velho!r})")

        if not aplicar:
            print("\nDry-run — nada foi alterado. Rode com --apply pra gravar.")
            return

        print("\nGerando backup antes de aplicar...")
        caminho = fazer_backup()
        if caminho is None:
            print("ERRO: backup falhou — abortando pra não gravar sem rede de segurança.")
            sys.exit(1)
        print(f"Backup criado: {caminho}")

        print(f"\nAplicando {len(mudancas)} atualizações...")
        with conn.cursor() as cur:
            for id_, _marca, _modelo, _versao, obs_novo, _obs_velho in mudancas:
                cur.execute(
                    "UPDATE anuncios SET versao = NULL, obs = %s WHERE id = %s",
                    (obs_novo, id_),
                )
        print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
