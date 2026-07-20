"""
Reprocessamento retroativo: ajustes pontuais de marca/modelo/versão/obs
(auditoria 2026-07-20, rodada 3 — correções apontadas pela usuária).

Cobre 5 problemas achados numa revisão manual dos resultados da rodada 2:

1. Mercedes "Classe X": só "CLASSE A" estava no catálogo — as demais letras
   (C/E/S/CLK/SLK) caíam no fallback "CLASSE" sozinho, e "Classe E"
   especificamente perdia o "E" de vez (colidia com "E" como conectivo de
   enumeração — ver _SPEC_OBSERVACAO). Catálogo já foi curado com as formas
   compostas; aqui só reprocessa os anúncios que já perderam a letra.
2. Número colado a uma palavra sem espaço no título original ("156Elegant")
   — normalizer já sabe separar (_NUMERO_PALAVRA_COLADA), falta reaplicar.
3. "Asia Motors"/"Kia Motors": "Motors" vazava pro modelo. Pra Asia, a
   usuária pediu que "Motors" faça parte do nome da marca; pra Kia (mesmo
   bug, marca não citada) e demais, é só descartado.
4. Cores não são informação de versão (nem carroceria/tração) — descartadas,
   exceto "Série Prata"/"Série Ouro" (edições reais da VW).
5. Varredura geral: motor/aluguel/casamento/eventos/dono/restaurado/
   modificado/hotrod adicionados à lista de descarte.

Casos 1-2 perderam informação que só existe no título original (a rodada 2
já sobrescreveu modelo/versão) — reprocessados via inferir_marca_modelo_
versao_obs_ano(titulo). Casos 3-5 não perderam nada (a palavra ainda está
armazenada em marca/modelo/versao/obs) — corrigidos direto nas colunas
já gravadas, sem depender do título.

Uso:
    python scripts/reprocessar_ajustes_marca_versao.py            # dry-run
    python scripts/reprocessar_ajustes_marca_versao.py --apply    # aplica
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import (
    _CORES,
    _NUMERO_PALAVRA_COLADA,
    inferir_marca_modelo_versao_obs_ano,
)
from src.pipeline.persistence import _connect

_JUNK_STRIP = frozenset({
    "MOTOR", "MOTORS", "ALUGUEL", "ALUGA-SE", "CASAMENTO", "CASAMENTOS",
    "EVENTO", "EVENTOS", "DONO", "DONOS", "HOTROD", "HOT-ROD",
    "RESTAURADO", "RESTAURADA", "MODIFICADO", "MODIFICADA",
})


def _remover_tokens(texto: str | None, remover: frozenset, cores_com_serie: bool = False) -> str | None:
    """
    Remove tokens de `remover` (e, se `cores_com_serie`, cores — exceto
    logo depois de "SERIE") de uma string já pronta (versao/obs/modelo
    armazenados). Retorna None se nada sobrar.
    """
    if not texto:
        return texto
    tokens = texto.split()
    final: list[str] = []
    for i, t in enumerate(tokens):
        if t in remover:
            continue
        if cores_com_serie and t in _CORES:
            if i > 0 and tokens[i - 1] == "SERIE":
                final.append(t)
            continue
        final.append(t)
    return " ".join(final) or None


def _asia_kia_motors_fix(marca: str, modelo: str | None) -> tuple[str, str | None]:
    """"Motors" vazado pro modelo: absorve na marca (Asia) ou descarta (Kia/outras)."""
    if not modelo:
        return (marca, modelo)
    tokens = modelo.split()
    if not tokens or tokens[0] not in ("MOTORS", "MOTOR"):
        return (marca, modelo)
    resto = " ".join(tokens[1:]) or None
    if marca == "ASIA":
        return ("ASIA MOTORS", resto)
    return (marca, resto)


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, marca, modelo, versao, obs, titulo FROM anuncios ORDER BY id")
            rows = cur.fetchall()

        print(f"Total de anúncios: {len(rows)}")

        # id -> (marca, modelo, versao, obs)
        mudancas: dict[int, tuple[str, str | None, str | None, str | None]] = {}

        # --- Casos 1-2: reprocessa via título (informação já perdida na rodada 2) ---
        n_titulo = 0
        for r in rows:
            modelo = r["modelo"] or ""
            precisa_titulo = (
                (r["marca"] == "MERCEDES-BENZ" and modelo == "CLASSE")
                or bool(_NUMERO_PALAVRA_COLADA.search(modelo))
            )
            if not precisa_titulo or not r["titulo"]:
                continue
            marca2, modelo2, versao2, obs2, _ano2 = inferir_marca_modelo_versao_obs_ano(r["titulo"])
            if marca2 != r["marca"]:
                # Rede de segurança: só aceita se a marca bater com a já
                # gravada (evita regressão tipo "AP 2000" — marca errada
                # inferida do título quando a fonte tinha campo estruturado).
                continue
            if (modelo2, versao2, obs2) != (r["modelo"], r["versao"], r["obs"]):
                mudancas[r["id"]] = (marca2, modelo2, versao2, obs2)
                n_titulo += 1

        print(f"Reprocessados via título (Classe sem letra / número colado): {n_titulo}")

        # --- Casos 3-5: corrige direto nas colunas já gravadas ---
        n_direto = 0
        for r in rows:
            if r["id"] in mudancas:
                continue  # já tratado via título acima
            marca, modelo, versao, obs = r["marca"], r["modelo"], r["versao"], r["obs"]

            marca, modelo = _asia_kia_motors_fix(marca or "", modelo)
            modelo = _remover_tokens(modelo, _JUNK_STRIP, cores_com_serie=True)
            versao = _remover_tokens(versao, _JUNK_STRIP, cores_com_serie=True)
            obs = _remover_tokens(obs, _JUNK_STRIP, cores_com_serie=False)

            if (marca, modelo, versao, obs) != (r["marca"], r["modelo"], r["versao"], r["obs"]):
                mudancas[r["id"]] = (marca, modelo, versao, obs)
                n_direto += 1

        print(f"Corrigidos direto nas colunas (Asia/Kia Motors, cores, palavras-lixo): {n_direto}")
        print(f"Total de linhas alteradas: {len(mudancas)}")

        print("\n--- Amostra de 30 mudanças ---")
        by_id = {r["id"]: r for r in rows}
        for id_, (marca2, modelo2, versao2, obs2) in list(mudancas.items())[:30]:
            r = by_id[id_]
            print(
                f"  #{id_} [{r['marca']}->{marca2}] "
                f"modelo {r['modelo']!r}->{modelo2!r} "
                f"versao {r['versao']!r}->{versao2!r} "
                f"obs {r['obs']!r}->{obs2!r}"
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
            for id_, (marca2, modelo2, versao2, obs2) in mudancas.items():
                cur.execute(
                    "UPDATE anuncios SET marca = %s, modelo = %s, versao = %s, obs = %s WHERE id = %s",
                    (marca2, modelo2, versao2, obs2, id_),
                )
        print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
