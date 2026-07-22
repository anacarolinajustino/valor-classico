"""
Reprocessamento retroativo de VARIAÇÕES DE GRAFIA do modelo (auditoria
2026-07-22, 3ª passada — a usuária apontou que a mesma linha aparecia com
grafias diferentes e ia fragmentada nas estatísticas: "Chevete"/"Chevette",
"Chevrolet Brasil"/"ChevroletBrasil", "Tornado"/"Toronado", "Grablazer"/
"Grand Blazer", "MG A"/"MGA"...).

Duas frentes:

  (1) GRAFIA canonizada pelo catálogo: as grafias cruas foram cadastradas em
      `_MODELO_ABREVIACAO` (normalizer.py), então basta re-sanear o CAMPO
      modelo dos anúncios cuja (marca, modelo) está no conjunto VARIANTES —
      `separar_modelo_versao_obs(marca, modelo)[0]` devolve a grafia canônica.
      NÃO mexe em marca/versao/obs (a rodada passada já os separou; recalcular
      arriscaria reverter). Restrito ao conjunto VARIANTES de propósito: não
      toca em nenhum outro anúncio.

  (2) OVERRIDES por id: casos onde o "modelo" no banco nem é modelo — é
      descritor ("Americano"/"Anericana" = o carro é um Bel Air; "Chevrolete"
      = "Chevrolet Sedã 1934" sem linha) ou o nome real está partido no título
      ("Ford del Rey Gl" virou modelo='DEL', versao='REI'). Não há grafia
      canônica pra onde canonizar — curados lendo o título original.

Uso:
    python scripts/reprocessar_grafia_variantes_modelo.py            # dry-run
    python scripts/reprocessar_grafia_variantes_modelo.py --apply    # backup + aplica
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

# --- (1) Variações de grafia: (marca, modelo_cru_no_banco) que devem passar
#     pela canonização do catálogo. A grafia canônica sai de _MODELO_ABREVIACAO
#     via separar_modelo_versao_obs — aqui só listamos QUAIS anúncios reprocessar
#     (mantém o script cirúrgico: nada fora desta lista é tocado).
VARIANTES: set[tuple[str, str]] = {
    ("CHEVROLET", "CHEVETE"),          # -> CHEVETTE
    ("CHEVROLET", "CHEYNNE"),          # -> CHEYENNE
    ("CHEVROLET", "GRABLAZER"),        # -> GRAND BLAZER
    ("CHEVROLET", "CHEVROLETBRASIL"),  # -> BRASIL
    ("CHEVROLET", "BISCAYNE2"),        # -> BISCAYNE
    ("FORD", "GALAXI"),                # -> GALAXIE
    ("FORD", "THUNDERBIR"),            # -> THUNDERBIRD
    ("FORD", "SCORT"),                 # -> ESCORT
    ("FORD", "PAMAPA"),                # -> PAMPA
    ("FORD", "RANCHEIRO"),             # -> RANCHERO
    ("FORD", "TBUCKET"),               # -> T-BUCKET
    ("FIAT", "PANAROMA"),              # -> PANORAMA
    ("MERCURY", "HEIGT"),              # -> EIGHT
    ("MG", "MIDJET"),                  # -> MIDGET
    ("MG", "A"),                       # -> MGA
    ("MG", "B"),                       # -> MGB
    ("MINI", "CUPER"),                 # -> COOPER
    ("OLDSMOBILE", "TORNADO"),         # -> TORONADO
    ("BUICK", "SKYLARC"),              # -> SKYLARK
    ("DKW", "VEMAGET"),                # -> VEMAGUET
    ("TOYOTA", "JIPEBANDEIRANTE"),     # -> BANDEIRANTE
    ("JEEP", "GRACHEROKEE"),           # -> GRAND CHEROKEE
    ("SUZUKI", "GRAVITARA"),           # -> GRAND VITARA
    ("GURGEL", "BRBR-800"),            # -> BR-800
    ("CADILLAC", "DEVILLESEDAN"),      # -> DE VILLE
}

# --- (2) Overrides por id (modelo, versao) — o "modelo" no banco não é modelo.
#     Curados lendo o título original de cada um. `versao=...` sobrescreve;
#     None limpa a versão.
_VAZIO = ""  # modelo vazio (honesto): título sem linha de modelo recuperável


def _ov(modelo, versao=None):
    return (modelo, versao)


OVERRIDES: dict[int, tuple[str, str | None]] = {
    # "Gm C10" — o carro é um C10, "Americana" era descritor solto.
    35063: _ov("C10", None),
    # "Chevrolet Belair 1957" — Bel Air; "Americano"/"Anericana" = descritor.
    35256: _ov("BEL AIR", None),
    35182: _ov("BEL AIR", None),
    # "Chevrolet Sedã 1934 2 Portas" — sem linha de modelo -> vazio honesto.
    34750: _ov(_VAZIO, None),
    # "Ford del Rey Gl" — DEL REY (o "Rey" tinha virado versao 'REI'); GL é a versão.
    34870: _ov("DEL REY", "GL"),
    # "MG Inglês Conversível" — "Inglês" não é modelo -> vazio honesto.
    35847: _ov(_VAZIO, None),
}


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, marca, modelo, versao, obs FROM anuncios ORDER BY id")
            rows = cur.fetchall()

        print(f"Total de anúncios: {len(rows)}")

        # (id, marca, modelo_v, modelo_n, versao_n, origem)
        mudancas = []
        for r in rows:
            id_ = r["id"]
            marca = r["marca"] or ""
            modelo_v = r["modelo"] or ""
            versao_v = r["versao"]

            if id_ in OVERRIDES:
                modelo_n, versao_n = OVERRIDES[id_]
                origem = "override"
            elif (marca, modelo_v) in VARIANTES:
                # Canoniza SÓ o nome do modelo; versao/obs ficam como estão.
                modelo_n = separar_modelo_versao_obs(marca, modelo_v)[0]
                versao_n = versao_v
                origem = "grafia"
            else:
                continue

            if (modelo_n, versao_n) != (modelo_v, versao_v):
                mudancas.append((id_, marca, modelo_v, modelo_n, versao_n, origem))

        por_origem: dict[str, int] = {}
        for m in mudancas:
            por_origem[m[5]] = por_origem.get(m[5], 0) + 1
        print(f"Linhas alteradas: {len(mudancas)}  (por origem: {por_origem})")

        print("\n--- Todas as mudanças ---")
        for id_, marca, mdv, mdn, vsn, org in mudancas:
            print(f"  #{id_} [{org}] {marca}: {mdv!r} -> modelo={mdn!r} versao={vsn!r}")

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
            for id_, _marca, _mdv, mdn, vsn, _org in mudancas:
                cur.execute(
                    "UPDATE anuncios SET modelo = %s, versao = %s WHERE id = %s",
                    (mdn, vsn, id_),
                )
        print("Concluído (commit ao sair do bloco).")


if __name__ == "__main__":
    main()
