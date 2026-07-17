"""
Reprocessamento retroativo por SANEAMENTO de marca/modelo (auditoria 2026-07-17).

Diferente de `reprocessar_marca_modelo.py` (que re-infere tudo do TÍTULO), este
script sanea a marca/modelo JÁ SALVOS com `sanear_marca_modelo`, usando o
catálogo pra separar marca de modelo e canonizar a grafia. É o reprocessamento
certo pros anúncios do Mercado Livre: a marca boa veio da ficha técnica (que o
título sozinho não reproduz — ex.: título "Ap 2000..." vs marca real Ford), mas
o campo "Marca" da ficha vinha CRU, com marca+modelo colados ("Chevrolet Opala")
ou grafia errada ("Alfa Romeu", "Volkswagem"). Reprocessar por título reverteria
a informação da ficha; sanear preserva a marca da ficha e só limpa a bagunça.

O saneamento é idempotente pra quem já está correto (marca do catálogo, grafia
canônica) — só as ~184 linhas com marca-lixo mudam. Preserva a sentinela
MARCA_NAO_IDENTIFICADA e a decisão deliberada de BUGGY (ver normalizer.py).

Uso:
    python scripts/reprocessar_saneamento_marca.py            # dry-run (só relatório)
    python scripts/reprocessar_saneamento_marca.py --apply    # backup + aplica
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import sanear_marca_modelo
from src.pipeline.persistence import _connect


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, marca, modelo FROM anuncios ORDER BY id")
            rows = cur.fetchall()

        print(f"Total de anúncios: {len(rows)}")

        mudancas: list[tuple[int, str, str, str, str]] = []
        for r in rows:
            marca_velha = r["marca"] or ""
            modelo_velho = r["modelo"] or ""
            marca_nova, modelo_novo = sanear_marca_modelo(marca_velha, modelo_velho)
            if marca_nova != marca_velha or modelo_novo != modelo_velho:
                mudancas.append((r["id"], marca_velha, marca_nova, modelo_velho, modelo_novo))

        muda_marca = [m for m in mudancas if m[1] != m[2]]
        print(f"Linhas que mudam (marca e/ou modelo): {len(mudancas)}")
        print(f"  dessas, mudam a MARCA: {len(muda_marca)}")

        # Resumo por marca antiga -> nova (só quando a marca muda)
        resumo: dict[tuple[str, str], int] = {}
        for _id, mv, mn, *_ in muda_marca:
            resumo[(mv, mn)] = resumo.get((mv, mn), 0) + 1

        print("\n--- Resumo marca antiga -> marca nova (contagem) ---")
        for (velha, nova), n in sorted(resumo.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {n:4d}  {velha!r:42} -> {nova!r}")

        print("\n--- Amostra de até 30 mudanças de modelo (marca inalterada) ---")
        so_modelo = [m for m in mudancas if m[1] == m[2]]
        for id_, _mv, _mn, modv, modn in so_modelo[:30]:
            print(f"  #{id_} modelo: {modv!r} -> {modn!r}")

        if not aplicar:
            print("\nDry-run — nada foi alterado. Rode com --apply pra gravar as mudanças.")
            return

        print("\nGerando backup antes de aplicar...")
        caminho = fazer_backup()
        if caminho is None:
            print("ERRO: backup falhou — abortando pra não gravar sem rede de segurança.")
            sys.exit(1)
        print(f"Backup criado: {caminho}")

        print(f"\nAplicando {len(mudancas)} atualizações...")
        with conn.cursor() as cur:
            for id_, _mv, marca_nova, _modv, modelo_novo in mudancas:
                cur.execute(
                    "UPDATE anuncios SET marca = %s, modelo = %s WHERE id = %s",
                    (marca_nova, modelo_novo, id_),
                )
        print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
