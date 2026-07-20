"""
Reprocessamento retroativo: separa VERSÃO e OBS de dentro do campo `modelo`
(auditoria 2026-07-20).

Espelha `reprocessar_saneamento_modelo.py`, mas em vez de só limpar o modelo,
usa `separar_modelo_versao_obs(marca, modelo)` pra reparti-lo em três colunas:
  - modelo: só o nome do modelo (ex.: "OPALA", "GOL", "CIVIC")
  - versao: trim/edição que pesa no preço (ex.: "COMODORO", "GERACAO I CL",
    "GLX") — geração entra aqui junto com o trim, decisão da usuária
    2026-07-20
  - obs: carroceria/tração que não é trim mas não pode ser descartada (ex.:
    "CABINE ESTENDIDA", "PICK-UP", "SEDAN", "4X4")

Specs de verdade (cilindrada, válvula, câmbio, combustível, injeção, porta,
observação de venda) continuam sendo descartadas — esse comportamento não
muda, é o mesmo corte de `sanear_modelo`.

Uso:
    python scripts/reprocessar_versao_obs.py            # dry-run (relatório)
    python scripts/reprocessar_versao_obs.py --apply     # backup + aplica
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import separar_modelo_versao_obs
from src.pipeline.persistence import _connect


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, marca, modelo, titulo FROM anuncios ORDER BY id")
            rows = cur.fetchall()

        print(f"Total de anúncios: {len(rows)}")

        # id, marca, modelo_velho, modelo_novo, versao, obs
        mudancas: list[tuple[int, str, str, str, str | None, str | None]] = []
        com_versao = 0
        com_obs = 0
        for r in rows:
            marca = r["marca"] or ""
            modelo_velho = r["modelo"] or ""
            if not modelo_velho.strip():
                continue
            modelo_novo, versao, obs = separar_modelo_versao_obs(marca, modelo_velho)
            if versao:
                com_versao += 1
            if obs:
                com_obs += 1
            if modelo_novo != modelo_velho or versao or obs:
                mudancas.append((r["id"], marca, modelo_velho, modelo_novo, versao, obs))

        print(f"Linhas alteradas (modelo muda e/ou versao/obs preenchidos): {len(mudancas)}")
        print(f"Linhas com versão extraída: {com_versao}")
        print(f"Linhas com obs extraída (carroceria/tração): {com_obs}")

        # Desfragmentação do campo modelo (sem versão colada)
        antes = {(r["marca"] or "", r["modelo"] or "") for r in rows if (r["modelo"] or "").strip()}
        depois = {
            (marca, separar_modelo_versao_obs(marca, modelo)[0])
            for marca, modelo in antes
        }
        print(f"Pares (marca, modelo) distintos: {len(antes)} -> {len(depois)}")

        # Top famílias de versão (quantas grafias de versão distintas por modelo)
        versoes_por_modelo: dict[tuple[str, str], set[str]] = defaultdict(set)
        for _id, marca, _mv, mn, versao, _obs in mudancas:
            if versao:
                versoes_por_modelo[(marca, mn)].add(versao)

        print("\n--- Top 20 modelos com mais versões distintas ---")
        top = sorted(versoes_por_modelo.items(), key=lambda kv: -len(kv[1]))[:20]
        for (marca, mn), versoes in top:
            exemplos = ", ".join(sorted(versoes)[:6])
            print(f"  {len(versoes):3d}x  {marca} {mn!r:16} <- {exemplos}")

        # Amostra de obs (carroceria/tração preservada)
        print("\n--- Amostra de 20 com obs preenchida ---")
        com_obs_exemplos = [m for m in mudancas if m[5]][:20]
        for id_, marca, mv, mn, versao, obs in com_obs_exemplos:
            print(f"  #{id_} [{marca}] {mv!r} -> modelo={mn!r} versao={versao!r} obs={obs!r}")

        # Casos suspeitos: modelo "encolheu" só de 1 token só e virou versão
        # de 1 número — provável nome de modelo protegido pelo catálogo que
        # não tem a forma composta cadastrada (tipo "Defender 110"). Vale
        # revisão manual antes de aceitar como versão de verdade.
        suspeitos = [
            m for m in mudancas
            if m[4] and m[4].replace(" ", "").isdigit() and len(m[3].split()) == 1
        ]
        print(f"\n--- {len(suspeitos)} casos suspeitos: modelo de 1 token + versão numérica ---")
        print("    (número pode ser parte do NOME do modelo, não trim — ver Defender 110)")
        vistos_suspeitos: set[tuple[str, str, str]] = set()
        for id_, marca, mv, mn, versao, obs in suspeitos:
            chave = (marca, mn, versao)
            if chave in vistos_suspeitos:
                continue
            vistos_suspeitos.add(chave)
            print(f"  [{marca}] modelo={mn!r} versao={versao!r}  (bruto: {mv!r})")
            if len(vistos_suspeitos) >= 20:
                break

        # Casos "lista agregada" — versão com 2+ tokens que são todos trims
        # curtos (L/SL/SS/GL/CL...), sinal de que a fonte empilhou várias
        # versões no mesmo registro em vez de uma versão real. Não resolvido
        # nesta rodada (precisa olhar o título anúncio a anúncio) — só
        # reportado pra dimensionar o problema.
        TRIMS_CURTOS = {"L", "SL", "SS", "GL", "CL", "GLS", "SLE", "DL", "SE", "LS", "LX", "CD"}
        listas = [
            m for m in mudancas
            if m[4] and len(m[4].split()) >= 2
            and sum(1 for t in m[4].split() if t in TRIMS_CURTOS) >= 2
        ]
        print(f"\n--- {len(listas)} anúncios com versão parecendo 'lista agregada' (não resolvido) ---")
        vistos_listas: set[tuple[str, str, str]] = set()
        for id_, marca, mv, mn, versao, obs in listas:
            chave = (marca, mn, versao)
            if chave in vistos_listas:
                continue
            vistos_listas.add(chave)
            print(f"  [{marca}] modelo={mn!r} versao={versao!r}")
            if len(vistos_listas) >= 15:
                break

        print("\n--- Amostra de 25 mudanças em geral ---")
        for id_, marca, mv, mn, versao, obs in mudancas[:25]:
            print(f"  #{id_} [{marca}] {mv!r} -> modelo={mn!r} versao={versao!r} obs={obs!r}")

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
            for id_, _marca, _mv, modelo_novo, versao, obs in mudancas:
                cur.execute(
                    "UPDATE anuncios SET modelo = %s, versao = %s, obs = %s WHERE id = %s",
                    (modelo_novo, versao, obs, id_),
                )
        print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
