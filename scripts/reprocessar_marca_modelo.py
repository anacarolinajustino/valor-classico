"""
Reprocessamento retroativo de marca/modelo (auditoria 2026-07-15).

Re-roda inferir_marca_modelo_ano() contra o titulo já salvo de cada anúncio
e atualiza marca/modelo quando o resultado muda. NÃO toca na coluna ano —
ela pode já ter sido corrigida por lógica específica de conector (ex.: ano
do badge no pastorecc) que a inferência genérica por título não reproduz.

Uso:
    python scripts/reprocessar_marca_modelo.py            # dry-run (só relatório)
    python scripts/reprocessar_marca_modelo.py --apply    # aplica as mudanças
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.normalizer import inferir_marca_modelo_ano
from src.pipeline.persistence import _connect

# Reclassificações que o reprocessamento encontra mas que são decisão de
# nomenclatura separada da confusão desta auditoria (marca=lixo/ano/typo) —
# ficam de fora deste lote até o usuário decidir qual grafia é a canônica.
# Formato: (marca_antiga, marca_nova) a pular.
_EXCLUIR: set[tuple[str, str]] = {
    ("WILLYS", "WILLYS OVERLAND"),
}


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, titulo, marca, modelo FROM anuncios ORDER BY id")
            rows = cur.fetchall()

        print(f"Total de anúncios: {len(rows)}")

        mudancas: list[tuple[int, str, str, str, str, str]] = []
        for r in rows:
            marca_nova, modelo_novo, _ano_novo = inferir_marca_modelo_ano(r["titulo"] or "")
            marca_nova = marca_nova or None
            modelo_novo = modelo_novo or None
            if (r["marca"], marca_nova) in _EXCLUIR:
                continue
            if marca_nova != r["marca"] or modelo_novo != r["modelo"]:
                mudancas.append((
                    r["id"], r["marca"] or "", marca_nova or "",
                    r["modelo"] or "", modelo_novo or "", r["titulo"] or "",
                ))

        print(f"Linhas com marca/modelo diferentes após reprocessar: {len(mudancas)}")

        # Resumo por marca antiga -> nova (só marca, pra ver o quadro geral)
        resumo: dict[tuple[str, str], int] = {}
        for _id, marca_velha, marca_nova, *_ in mudancas:
            if marca_velha != marca_nova:
                resumo[(marca_velha, marca_nova)] = resumo.get((marca_velha, marca_nova), 0) + 1

        print("\n--- Resumo marca antiga -> marca nova (contagem) ---")
        for (velha, nova), n in sorted(resumo.items(), key=lambda x: -x[1]):
            print(f"  {n:4d}  {velha!r:20} -> {nova!r}")

        print("\n--- Amostra de 20 mudanças (id | marca | modelo | titulo) ---")
        for id_, mv, mn, modv, modn, titulo in mudancas[:20]:
            print(f"  #{id_} marca: {mv!r} -> {mn!r} | modelo: {modv!r} -> {modn!r} | titulo: {titulo!r}")

        if not aplicar:
            print("\nDry-run — nada foi alterado. Rode com --apply pra gravar as mudanças.")
            return

        print(f"\nAplicando {len(mudancas)} atualizações...")
        with conn.cursor() as cur:
            for id_, _mv, marca_nova, _modv, modelo_novo, _titulo in mudancas:
                cur.execute(
                    "UPDATE anuncios SET marca = %s, modelo = %s WHERE id = %s",
                    (marca_nova, modelo_novo, id_),
                )
        print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
