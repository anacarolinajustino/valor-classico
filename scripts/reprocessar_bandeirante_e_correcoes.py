"""
Reprocessamento retroativo: recombina modelo+versão+obs já gravados e roda
de novo por `separar_modelo_versao_obs` (auditoria 2026-07-20, rodada 4).

Motivação: a rodada 4 mudou o normalizer (canoniza "Band"/"Band."/
"Bandeirantes" pra "BANDEIRANTE" — usuária apontou o caso —, separa
abreviação com ponto colada tipo "Band.Picape"/"Cap.de", e adiciona
JIPE/PICAPE/CAP./CAPOTA/LONA/AÇO/SED./CHAS. à lista de carroceria). Nenhuma
informação nova é necessária: modelo/versão/obs já gravados contêm tudo,
só precisam ser reclassificados com as regras novas — não depende do
título original (diferente da rodada 3, que precisou disso pro "Classe E").

Cuidado: recombinar cegamente desfaria a correção da rodada 2 ("lista
agregada" — OPALA L SL SS etc., movida de versão pra obs por um critério
que NÃO é o de carroceria/tração). Esses ~382 anúncios têm obs com um dos 4
valores exatos abaixo — excluídos deste reprocessamento, tratados à parte
se precisarem de outro ajuste.

Uso:
    python scripts/reprocessar_bandeirante_e_correcoes.py            # dry-run
    python scripts/reprocessar_bandeirante_e_correcoes.py --apply    # aplica
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import separar_modelo_versao_obs
from src.pipeline.persistence import _connect

_OBS_LISTA_AGREGADA = frozenset({"L SL SS", "GL SL LITE TURIM", "PLUS LS S", "D20 CUSTOM S"})


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, marca, modelo, versao, obs FROM anuncios ORDER BY id")
            rows = cur.fetchall()

        print(f"Total de anúncios: {len(rows)}")

        excluidos = 0
        mudancas: dict[int, tuple[str, str | None, str | None]] = {}
        for r in rows:
            if not r["modelo"]:
                continue
            if r["obs"] in _OBS_LISTA_AGREGADA:
                excluidos += 1
                continue
            bruto = " ".join(p for p in [r["modelo"], r["versao"], r["obs"]] if p)
            modelo2, versao2, obs2 = separar_modelo_versao_obs(r["marca"] or "", bruto)
            if (modelo2, versao2, obs2) != (r["modelo"], r["versao"], r["obs"]):
                mudancas[r["id"]] = (modelo2, versao2, obs2)

        print(f"Excluídos (lista agregada da rodada 2, não recombinar): {excluidos}")
        print(f"Linhas alteradas: {len(mudancas)}")

        print("\n--- Amostra de 40 mudanças ---")
        by_id = {r["id"]: r for r in rows}
        for id_, (modelo2, versao2, obs2) in list(mudancas.items())[:40]:
            r = by_id[id_]
            print(
                f"  #{id_} [{r['marca']}] modelo {r['modelo']!r}->{modelo2!r} "
                f"versao {r['versao']!r}->{versao2!r} obs {r['obs']!r}->{obs2!r}"
            )

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
            for id_, (modelo2, versao2, obs2) in mudancas.items():
                cur.execute(
                    "UPDATE anuncios SET modelo = %s, versao = %s, obs = %s WHERE id = %s",
                    (modelo2, versao2, obs2, id_),
                )
        print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
