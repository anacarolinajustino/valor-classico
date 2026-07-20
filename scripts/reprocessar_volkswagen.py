"""
Reprocessamento retroativo: revisão geral dos modelos Volkswagen (auditoria
2026-07-20, rodada 6 — usuária pediu pra revisar todos os modelos VW).

Achados e correções no normalizer:

1. Busca de âncora não pulava carroceria solto na frente ("Perua Kombi" —
   virava modelo="PERUA" em vez de achar "KOMBI" depois) nem cilindrada
   colada a trim ("1600S" em "Fuscão 1600s..." virava modelo="1600S").
   Corrigido em _achar_ancora_modelo.
2. Grafias fragmentadas do mesmo modelo (apelido, typo, plural, glued):
   FUSCAO/FUSQUINHA->FUSCA, APOLO->APOLLO, BRASLIA->BRASILIA (typo),
   VOYAGEM/VOYAGES/VOIAGE->VOYAGE, KARMANN-GUIA->KARMANN-GHIA,
   GOLCL/SAVEIROCL/VOYAGECL-> modelo base (perde o trim "CL" à parte,
   aceitável pro volume). Ver _MODELO_ABREVIACAO.
3. Alias de MARCA "VOIAGE"->VOLKSWAGEN consumia o token e "Voiage
   Argentino" perdia "Voyage" do modelo — movido pra _MODELO_AMBIGUO_MARCA
   (não consome), a canonização acontece depois no pipeline de modelo.
4. Um punhado de anúncios (todos do Mercado Livre) tinham modelo
   completamente desconectado do título ("Kombi Corujinha" -> modelo
   "GABINETE", "Volkswagen Fusca" -> modelo "EXPORTACAO") — resíduo de
   uma derivação antiga, nunca recomputado porque era estável sob
   recombinação (recombinar o valor já errado dá o mesmo errado de novo).
   Só resolve reprocessando direto do título.

Esse reprocessamento, diferente das rodadas 4/5, recomputa TODOS os
anúncios Volkswagen a partir do título (não só recombina modelo/versão/obs
já gravados) — é o único jeito de pegar o caso 4. Rede de segurança: só
aplica se a marca derivada do título ainda bater "VOLKSWAGEN" (evita
regressão tipo trocar a marca por engano).

Uso:
    python scripts/reprocessar_volkswagen.py            # dry-run (relatório)
    python scripts/reprocessar_volkswagen.py --apply    # aplica
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import inferir_marca_modelo_versao_obs_ano
from src.pipeline.persistence import _connect

_OBS_LISTA_AGREGADA = frozenset({"L SL SS", "GL SL LITE TURIM", "PLUS LS S", "D20 CUSTOM S"})


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, marca, modelo, versao, obs, titulo FROM anuncios WHERE marca = 'VOLKSWAGEN' ORDER BY id")
            rows = cur.fetchall()

        print(f"Total de anúncios Volkswagen: {len(rows)}")

        excluidos = 0
        rejeitados_marca_diferente = 0
        mudancas: dict[int, tuple[str, str | None, str | None]] = {}

        for r in rows:
            if r["obs"] in _OBS_LISTA_AGREGADA:
                excluidos += 1
                continue
            if not r["titulo"]:
                continue

            marca2, modelo2, versao2, obs2, _ano2 = inferir_marca_modelo_versao_obs_ano(r["titulo"])
            if marca2 != "VOLKSWAGEN":
                if modelo2:
                    rejeitados_marca_diferente += 1
                continue

            if (modelo2 or None, versao2, obs2) != (r["modelo"], r["versao"], r["obs"]):
                mudancas[r["id"]] = (modelo2 or None, versao2, obs2)

        print(f"Excluídos (lista agregada da rodada 2): {excluidos}")
        print(f"Rejeitados — título sugeriria marca diferente de Volkswagen: {rejeitados_marca_diferente}")
        print(f"Total de linhas alteradas: {len(mudancas)}")

        print("\n--- Todas as mudanças de modelo ---")
        by_id = {r["id"]: r for r in rows}
        vistos_modelo: set[tuple[str | None, str | None]] = set()
        for id_, (modelo2, versao2, obs2) in mudancas.items():
            r = by_id[id_]
            chave = (r["modelo"], modelo2)
            if chave in vistos_modelo:
                continue
            vistos_modelo.add(chave)
            print(f"  [{r['modelo']!r} -> {modelo2!r}]  (ex.: #{id_} {r['titulo']!r})")

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
