"""
Reprocessamento retroativo por SANEAMENTO do MODELO (auditoria 2026-07-17).

Espelha `reprocessar_saneamento_marca.py`, mas mexe SÓ na coluna `modelo`: passa
o modelo já salvo por `sanear_modelo(marca, modelo)`, que tira a cauda de
especificação (cilindrada "1.6"/"1300", válvulas "8V", combustível "Gasolina",
injeção "MPFI", câmbio "Mec.", portas "2P"/"4 Portas", potência "50cv" e
observações "modelo antigo") e MANTÉM o nome do modelo + versão/trim (XR3, GSI,
GLX — decisão da usuária, pesa no preço de clássico). A marca NÃO é tocada (já
foi saneada nas rodadas anteriores — ver reprocessar_saneamento_marca.py).

O saneamento é idempotente pra quem já está limpo. O ganho é desfragmentar o
ranking: o mesmo Fusca vinha como "FUSCA", "FUSCA 1300", "FUSCA 1600",
"FUSCA ALCOOL", "FUSCA FUSCA GASOLINA"...

Uso:
    python scripts/reprocessar_saneamento_modelo.py            # dry-run (relatório)
    python scripts/reprocessar_saneamento_modelo.py --apply    # backup + aplica
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import sanear_modelo
from src.pipeline.persistence import _connect


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, marca, modelo FROM anuncios ORDER BY id")
            rows = cur.fetchall()

        print(f"Total de anúncios: {len(rows)}")

        mudancas: list[tuple[int, str, str, str]] = []  # id, marca, modelo_velho, modelo_novo
        for r in rows:
            marca = r["marca"] or ""
            modelo_velho = r["modelo"] or ""
            modelo_novo = sanear_modelo(marca, modelo_velho)
            if modelo_novo != modelo_velho:
                mudancas.append((r["id"], marca, modelo_velho, modelo_novo))

        print(f"Linhas que mudam o modelo: {len(mudancas)}")

        # Quanto o campo encolhe, em média (medida do quanto de spot estava poluindo)
        if mudancas:
            enc = sum(len(mv.split()) - len(mn.split()) for _, _, mv, mn in mudancas)
            print(f"Tokens de spec removidos no total: {enc} "
                  f"(~{enc/len(mudancas):.1f} por linha alterada)")

        # Desfragmentação: quantos (marca, modelo) distintos antes x depois
        antes = {(r["marca"] or "", r["modelo"] or "") for r in rows}
        depois = {
            (r["marca"] or "", sanear_modelo(r["marca"] or "", r["modelo"] or ""))
            for r in rows
        }
        print(f"Pares (marca, modelo) distintos: {len(antes)} -> {len(depois)}")

        # Amostra dos maiores colapsos: modelo_novo com mais grafias velhas distintas
        from collections import defaultdict

        grafias: dict[tuple[str, str], set[str]] = defaultdict(set)
        for _id, marca, mv, mn in mudancas:
            grafias[(marca, mn)].add(mv)

        print("\n--- Top 25 colapsos (modelo novo <- nº de grafias velhas) ---")
        top = sorted(grafias.items(), key=lambda kv: -len(kv[1]))[:25]
        for (marca, mn), velhas in top:
            exemplos = ", ".join(sorted(velhas)[:3])
            print(f"  {len(velhas):3d}x  {marca} | {mn!r:28} <- {exemplos}")

        print("\n--- Amostra de 30 mudanças ---")
        for id_, marca, mv, mn in mudancas[:30]:
            print(f"  #{id_} [{marca}] {mv!r} -> {mn!r}")

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
            for id_, _marca, _mv, modelo_novo in mudancas:
                cur.execute(
                    "UPDATE anuncios SET modelo = %s WHERE id = %s",
                    (modelo_novo, id_),
                )
        print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
