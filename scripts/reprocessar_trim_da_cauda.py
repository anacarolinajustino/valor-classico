"""
Reprocessamento retroativo do TRIM QUE FICOU NA CAUDA DA SPEC (2026-08-05).

O corte de spec (`_indice_corte_spec`) para no primeiro token de spec, porque
é ali que o NOME do modelo acaba. Mas em muitos títulos o trim vem depois da
cilindrada, e nesses casos ele nunca era visto:

    Chevrolet Blazer 1997 4.3 V6 Dlx 5p   -> corta em "4.3", perde o DLX
    Volkswagen Gol 1.8 Mi Gl 8v Gasolina  -> corta em "1.8", perde o GL

`_trims_na_cauda` passou a pescar de volta o que o catálogo avaliza como trim
daquele carro. Como a correção mora em `separar_modelo_versao_obs`, que roda
nos CONECTORES e não no upsert, o reprocessamento da decomposição
(`reprocessar_decomposicao_versao.py`) não a alcança: ele parte do campo
`versao` já gravado, e nesses anúncios ele está vazio. Daí este script, que
parte do TÍTULO.

ESCOPO DELIBERADAMENTE ESTREITO — duas travas:

  1. só anúncios com `versao` vazia. Onde já há versão, não há o que recuperar
     e mexer só criaria risco;
  2. só quando a marca/modelo re-inferidos do título BATEM com os gravados.
     Se divergirem, o anúncio é pulado e contado à parte: re-decidir
     marca/modelo é outra auditoria, com outro risco, e misturar as duas
     tornaria impossível saber o que causou cada mudança.

Uso:
    python scripts/reprocessar_trim_da_cauda.py            # dry-run
    python scripts/reprocessar_trim_da_cauda.py --limite 500   # amostra
    python scripts/reprocessar_trim_da_cauda.py --apply     # backup + aplica
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import (
    decompor_versao,
    inferir_marca_modelo_versao_obs_ano,
    normalizar_texto,
)
from src.pipeline.persistence import _connect


def _arg_limite() -> int | None:
    if "--limite" not in sys.argv:
        return None
    i = sys.argv.index("--limite")
    try:
        return int(sys.argv[i + 1])
    except (IndexError, ValueError):
        print("ERRO: --limite exige um número (ex.: --limite 500)")
        sys.exit(1)


def main() -> None:
    aplicar = "--apply" in sys.argv
    limite = _arg_limite()

    with _connect() as conn:
        with conn.cursor() as cur:
            sql = (
                "SELECT id, marca, modelo, versao, obs, geracao, motor, titulo, fonte "
                "FROM anuncios WHERE versao IS NULL OR versao = '' ORDER BY id"
            )
            if limite:
                sql += f" LIMIT {int(limite)}"
            cur.execute(sql)
            rows = cur.fetchall()

        print(f"Anúncios sem versão lidos: {len(rows)}")

        mudancas: list[tuple[int, tuple, tuple]] = []
        pulados_par_diferente: Counter = Counter()
        sem_ganho = 0

        for r in rows:
            mk_banco = normalizar_texto(r["marca"] or "")
            md_banco = normalizar_texto(r["modelo"] or "")

            mk_novo, md_novo, versao_nova, obs_nova, _ano = (
                inferir_marca_modelo_versao_obs_ano(r["titulo"] or "")
            )

            # Trava 2: par re-inferido tem que bater com o gravado.
            if (mk_novo, md_novo) != (mk_banco, md_banco):
                if versao_nova:
                    pulados_par_diferente[
                        (mk_banco, md_banco, mk_novo, md_novo)
                    ] += 1
                continue

            if not versao_nova and not obs_nova:
                sem_ganho += 1
                continue

            # Mesma decomposição que o upsert aplica, realimentando os eixos
            # que já estão gravados (senão o UPDATE os apagaria).
            novo = decompor_versao(
                mk_banco, md_banco, versao_nova,
                obs_nova or r["obs"], r["titulo"], r["geracao"], r["motor"],
            )
            velho = (r["versao"], r["geracao"], r["motor"], r["obs"])
            if novo != velho:
                mudancas.append((r["id"], velho, novo))

        print(f"Linhas que mudam: {len(mudancas)}")
        ganham_versao = sum(1 for _i, v, n in mudancas if not v[0] and n[0])
        ganham_obs = sum(1 for _i, v, n in mudancas if not v[3] and n[3])
        print(f"  ganham VERSÃO: {ganham_versao}")
        print(f"  ganham OBS:    {ganham_obs}")
        print(f"  sem ganho (título não tinha trim): {sem_ganho}")
        print(f"  pulados por par divergente: {sum(pulados_par_diferente.values())}")

        if pulados_par_diferente:
            print("\n--- Top 10 pulados (marca/modelo do banco != re-inferido) ---")
            for (mkb, mdb, mkn, mdn), n in pulados_par_diferente.most_common(10):
                print(f"  {n:4d}x  banco={mkb} {mdb!r}  ->  título dá {mkn} {mdn!r}")

        # Quais trims foram recuperados, e quanto cada um rende
        recuperados: Counter = Counter()
        for _i, velho, novo in mudancas:
            if not velho[0] and novo[0]:
                recuperados[novo[0]] += 1
        print("\n--- Top 25 versões recuperadas ---")
        for versao, n in recuperados.most_common(25):
            print(f"  {n:5d}  {versao}")

        print("\n--- Amostra de 25 mudanças ---")
        for id_, velho, novo in mudancas[:25]:
            print(f"  #{id_}: versao {velho[0]!r} -> {novo[0]!r} | "
                  f"obs {velho[3]!r} -> {novo[3]!r}")

        if not aplicar:
            print("\nDry-run — nada foi alterado. Rode com --apply pra gravar.")
            return

        if limite:
            print("\nERRO: --apply com --limite gravaria só parte da base. "
                  "Rode o dry-run com --limite e o --apply sem ele.")
            sys.exit(1)

        print("\nGerando backup antes de aplicar...")
        caminho = fazer_backup()
        if caminho is None:
            print("ERRO: backup falhou — nada foi alterado.")
            sys.exit(1)
        print(f"Backup criado: {caminho}")

        print(f"\nAplicando {len(mudancas)} atualizações...")
        with conn.cursor() as cur:
            for id_, _velho, novo in mudancas:
                cur.execute(
                    "UPDATE anuncios SET versao = %s, geracao = %s, motor = %s, obs = %s "
                    "WHERE id = %s",
                    (novo[0], novo[1], novo[2], novo[3], id_),
                )
        print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
