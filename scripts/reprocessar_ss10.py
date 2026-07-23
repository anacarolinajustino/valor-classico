"""
Reprocessamento retroativo do "SS10" da Chevrolet (2026-07-23 — a usuária
apontou que "SS10" na verdade é a S10 com acabamento SS: modelo S10, versão SS).

A raiz já foi corrigida em `_MODELO_EXPANSAO` (normalizer.py): o token "SS10"
passa a expandir pra "S10 SS" na tokenização, então a âncora acha S10 no
catálogo e "SS" vira versão. Este script aplica a mesma separação aos anúncios
JÁ no banco cujo modelo é "SS10".

Diferente do reprocessamento de grafia (que só renomeia o modelo e mantém a
versão), aqui o "SS" precisa SAIR do modelo e ir pra versão — então
recombinamos `modelo + versao` e re-separamos com `separar_modelo_versao_obs`.
Assim o registro do ML que já tinha versao="AMERICANA" vira versao="SS AMERICANA"
(e não perde o "Americana"), e os do OLX (versao vazia) viram versao="SS".
Cirúrgico: só toca em (CHEVROLET, SS10).

Uso:
    python scripts/reprocessar_ss10.py            # dry-run
    python scripts/reprocessar_ss10.py --apply    # backup + aplica
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

ALVO = ("CHEVROLET", "SS10")


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, marca, modelo, versao, obs FROM anuncios "
                "WHERE UPPER(marca) = %s AND UPPER(modelo) = %s ORDER BY id",
                ALVO,
            )
            rows = cur.fetchall()

        print(f"Anúncios (CHEVROLET, SS10): {len(rows)}")

        mudancas = []
        for r in rows:
            marca = r["marca"] or ""
            modelo_v = r["modelo"] or ""
            versao_v = r["versao"]
            # Recombina modelo+versao e re-separa: o "SS" sai do modelo pra versão,
            # sem perder trim que já estava na versão (ex.: "AMERICANA").
            combinado = f"{modelo_v} {versao_v}".strip() if versao_v else modelo_v
            modelo_n, versao_n, obs_n = separar_modelo_versao_obs(marca, combinado)
            # obs só é sobrescrita se a re-separação produzir uma (não apaga a atual).
            obs_final = obs_n if obs_n else r["obs"]
            if (modelo_n, versao_n, obs_final) != (modelo_v, versao_v, r["obs"]):
                mudancas.append((r["id"], modelo_v, versao_v, modelo_n, versao_n, obs_final))

        print(f"Linhas a alterar: {len(mudancas)}")
        for id_, mdv, vsv, mdn, vsn, obn in mudancas:
            print(f"  #{id_}  modelo {mdv!r} versao {vsv!r}  ->  modelo {mdn!r} versao {vsn!r} obs {obn!r}")

        if not aplicar:
            print("\nDry-run — nada foi alterado. Rode com --apply pra gravar.")
            return

        print("\nGerando backup antes de aplicar...")
        caminho = fazer_backup()
        if caminho is None:
            print("ERRO: backup falhou — abortando.")
            sys.exit(1)
        print(f"Backup criado: {caminho}")

        print(f"\nAplicando {len(mudancas)} atualizações...")
        with conn.cursor() as cur:
            for id_, _mdv, _vsv, mdn, vsn, obn in mudancas:
                cur.execute(
                    "UPDATE anuncios SET modelo = %s, versao = %s, obs = %s WHERE id = %s",
                    (mdn, vsn, obn, id_),
                )
        print("Concluído (commit ao sair do bloco).")


if __name__ == "__main__":
    main()
