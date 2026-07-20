"""
Reprocessamento retroativo: modelo em branco ou só motorização (auditoria
2026-07-20, rodada 5 — usuária pediu pra revisar os dois casos).

Duas causas raiz diferentes, duas estratégias:

1. "Puro lixo vira modelo" (ex.: modelo="V8", "Modelo Antigo", "Com..."):
   o normalizer agora reconhece isso e devolve modelo vazio em vez de
   manter a palavra de spec/observação (ver _localizar_modelo). Só que
   pra achar o nome REAL quando ele existe (ex.: "Puma 1.6 Gte" — a
   cilindrada vinha antes do nome cadastrado no catálogo "Gte"), a âncora
   agora também pula spec solto na frente. Catálogo ganhou 2CV/4CV/Jaguar
   3.4-3.8/Santa Matilde 4.1 (número que É o nome comercial, não
   motorização). Corrigido recombinando modelo+versão+obs já gravados e
   reclassificando — sem depender do título (mesma lógica da rodada 4).

2. "Asia Motors"/"Kia Motors" com modelo em branco: bug da rodada 3 — a
   correção de "Motors vazado pro modelo" (quando o modelo era só a
   palavra "MOTORS", nada mais) removeu "Motors" e não sobrou nada,
   jogando o modelo pra vazio — mas o nome real do modelo já estava em
   VERSÃO desde a rodada 2 (ex.: modelo="Motors", versão="Topic Luxo").
   A recombinação do item 1 já resolve isso também (versão="Topic Luxo"
   vira o bruto reprocessado, sem precisar do título).

Pra quem continuar em branco depois da recombinação (não tinha nada em
versão/obs pra recombinar — modelo já nasceu vazio), tenta reconstruir do
título original — só aceita se a marca derivada bater com a já gravada
(rede de segurança contra regressão, mesmo critério da rodada 3).

Uso:
    python scripts/reprocessar_modelo_vazio_motorizacao.py            # dry-run
    python scripts/reprocessar_modelo_vazio_motorizacao.py --apply    # aplica
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import inferir_marca_modelo_versao_obs_ano, separar_modelo_versao_obs
from src.pipeline.persistence import _connect

_OBS_LISTA_AGREGADA = frozenset({"L SL SS", "GL SL LITE TURIM", "PLUS LS S", "D20 CUSTOM S"})


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, marca, modelo, versao, obs, titulo FROM anuncios ORDER BY id")
            rows = cur.fetchall()

        print(f"Total de anúncios: {len(rows)}")

        excluidos = 0
        estava_vazio = 0
        recuperado_via_recombinacao = 0
        recuperado_via_titulo = 0
        rejeitados_marca_diferente = 0
        ainda_vazio = 0
        mudancas: dict[int, tuple[str, str | None, str | None]] = {}

        for r in rows:
            if r["obs"] in _OBS_LISTA_AGREGADA:
                excluidos += 1
                continue

            marca = r["marca"] or ""
            modelo_original_vazio = not r["modelo"]
            if modelo_original_vazio:
                estava_vazio += 1

            bruto = " ".join(p for p in [r["modelo"], r["versao"], r["obs"]] if p)
            modelo2, versao2, obs2 = separar_modelo_versao_obs(marca, bruto) if bruto else ("", None, None)

            if modelo_original_vazio and modelo2:
                recuperado_via_recombinacao += 1
            elif not modelo2 and r["titulo"]:
                marca_t, modelo_t, versao_t, obs_t, _ano_t = inferir_marca_modelo_versao_obs_ano(r["titulo"])
                if marca_t == marca and modelo_t:
                    modelo2, versao2, obs2 = modelo_t, versao_t, obs_t
                    if modelo_original_vazio:
                        recuperado_via_titulo += 1
                elif marca_t != marca and modelo_t:
                    rejeitados_marca_diferente += 1

            if not modelo2:
                ainda_vazio += 1

            if (modelo2 or None, versao2, obs2) != (r["modelo"], r["versao"], r["obs"]):
                mudancas[r["id"]] = (modelo2 or None, versao2, obs2)

        print(f"Excluídos (lista agregada da rodada 2): {excluidos}")
        print(f"Anúncios com modelo em branco antes deste reprocessamento: {estava_vazio}")
        print(f"  Recuperados recombinando modelo+versão+obs já gravados: {recuperado_via_recombinacao}")
        print(f"  Recuperados via título (marca bateu com a já gravada): {recuperado_via_titulo}")
        print(f"  Rejeitados — título sugeriria marca diferente da já gravada: {rejeitados_marca_diferente}")
        print(f"  Continuam sem modelo recuperável: {ainda_vazio}")
        print(f"Total de linhas alteradas (inclui modelo=motorização virando vazio em linhas que JÁ tinham modelo): {len(mudancas)}")

        print("\n--- Amostra de 40 mudanças ---")
        by_id = {r["id"]: r for r in rows}
        for id_, (modelo2, versao2, obs2) in list(mudancas.items())[:40]:
            r = by_id[id_]
            print(
                f"  #{id_} [{r['marca']}] modelo {r['modelo']!r}->{modelo2!r} "
                f"versao {r['versao']!r}->{versao2!r} obs {r['obs']!r}->{obs2!r}"
            )

        print("\n--- Ainda sem modelo (revisão manual) ---")
        count_mostrado = 0
        for r in rows:
            id_ = r["id"]
            if id_ in mudancas:
                modelo2 = mudancas[id_][0]
            else:
                modelo2 = r["modelo"]
            if not modelo2:
                print(f"  #{id_} [{r['marca']}] titulo={r['titulo']!r}")
                count_mostrado += 1
                if count_mostrado >= 40:
                    break

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
