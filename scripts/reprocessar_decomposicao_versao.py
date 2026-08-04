"""
Reprocessamento retroativo da DECOMPOSIÇÃO DA VERSÃO (auditoria 2026-08-04).

Passa a versão já gravada por `decompor_versao(marca, modelo, versao, obs,
titulo)`, que separa nos eixos que o campo vinha misturando:

    versao   trim/acabamento, canonizado pelo vocabulário do catálogo
    geracao  "I", "II", "III"     (antes vinha colado: "GERACAO I CL")
    motor    "1.6 8V GASOLINA"    (antes entulhava a versão ou era descartado)
    obs      carroceria/tração    (SW, HATCH, VAN... somados aos que já havia)

Também aplica, na mesma passada:
  - a sentinela VERSAO_AGREGADA nos anúncios cujo título é o rótulo da
    taxonomia da fonte, e não do carro ("Chevette L / SL / Sl/e / DL / SE");
  - a normalização da versão crua da Webmotors (acento, barra, ordem);
  - o descarte do nome do modelo repetido na versão ("Blazer Dlx" no BLAZER).

O estudo que motivou a rodada mediu, na base de 2026-08-04: 2.593 versões
distintas pra 1.018 pares marca/modelo, com 2.287 dos 3.293 grupos (marca,
modelo, versão) tendo 1 ou 2 anúncios — inúteis pra tirar média.

`decompor_versao` é idempotente, então rodar de novo é seguro.

Uso:
    python scripts/reprocessar_decomposicao_versao.py            # dry-run
    python scripts/reprocessar_decomposicao_versao.py --limite 300   # amostra
    python scripts/reprocessar_decomposicao_versao.py --apply    # backup + aplica
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import VERSAO_AGREGADA, decompor_versao
from src.pipeline.persistence import _connect


def _arg_limite() -> int | None:
    """--limite N: reprocessa só as N primeiras linhas (smoke test)."""
    if "--limite" not in sys.argv:
        return None
    i = sys.argv.index("--limite")
    try:
        return int(sys.argv[i + 1])
    except (IndexError, ValueError):
        print("ERRO: --limite exige um número (ex.: --limite 300)")
        sys.exit(1)


def main() -> None:
    aplicar = "--apply" in sys.argv
    limite = _arg_limite()

    with _connect() as conn:
        with conn.cursor() as cur:
            sql = (
                "SELECT id, marca, modelo, versao, obs, geracao, motor, titulo "
                "FROM anuncios ORDER BY id"
            )
            if limite:
                sql += f" LIMIT {int(limite)}"
            cur.execute(sql)
            rows = cur.fetchall()

        print(f"Total de anúncios lidos: {len(rows)}")

        # id, (versao, geracao, motor, obs) velho -> novo
        mudancas: list[tuple[int, tuple, tuple]] = []
        for r in rows:
            velho = (r["versao"], r["geracao"], r["motor"], r["obs"])
            novo = decompor_versao(
                r["marca"] or "", r["modelo"] or "",
                r["versao"], r["obs"], r["titulo"],
            )
            if novo != velho:
                mudancas.append((r["id"], velho, novo))

        print(f"Linhas que mudam: {len(mudancas)}")

        # ── Efeito nos eixos novos ──────────────────────────────
        com_geracao = sum(1 for _i, _v, n in mudancas if n[1])
        com_motor = sum(1 for _i, _v, n in mudancas if n[2])
        agregadas = sum(1 for _i, _v, n in mudancas if n[0] == VERSAO_AGREGADA)
        print(f"  geração extraída pro campo próprio: {com_geracao}")
        print(f"  motorização extraída pro campo próprio: {com_motor}")
        print(f"  versão marcada como {VERSAO_AGREGADA}: {agregadas}")

        # ── Desfragmentação: grupos antes x depois ──────────────
        antes = Counter(
            (r["marca"] or "", r["modelo"] or "", r["versao"] or "")
            for r in rows
        )
        depois_map = {
            r["id"]: decompor_versao(
                r["marca"] or "", r["modelo"] or "",
                r["versao"], r["obs"], r["titulo"],
            )
            for r in rows
        }
        depois = Counter(
            (r["marca"] or "", r["modelo"] or "",
             depois_map[r["id"]][0] or "", depois_map[r["id"]][1] or "")
            for r in rows
        )
        print(f"\nGrupos (marca, modelo, versão) ANTES: {len(antes)}")
        print(f"Grupos (marca, modelo, versão, geração) DEPOIS: {len(depois)}")

        # Amostra com 3+ anúncios é o que dá média confiável — é a métrica
        # que interessa pra calculadora, não a contagem de grupos em si.
        util_antes = sum(n for n in antes.values() if n >= 3)
        util_depois = sum(n for n in depois.values() if n >= 3)
        total = max(len(rows), 1)
        print(
            f"Anúncios em grupo com 3+ amostras: "
            f"{util_antes} ({util_antes*100//total}%) -> "
            f"{util_depois} ({util_depois*100//total}%)"
        )

        # ── Maiores colapsos ────────────────────────────────────
        grafias: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        for r in rows:
            nova = depois_map[r["id"]][0] or ""
            if nova and nova != (r["versao"] or ""):
                grafias[(r["marca"] or "", r["modelo"] or "", nova)].add(
                    r["versao"] or ""
                )
        print("\n--- Top 25 colapsos (versão nova <- nº de grafias velhas) ---")
        for (mk, md, nova), velhas in sorted(
            grafias.items(), key=lambda kv: -len(kv[1])
        )[:25]:
            exemplos = ", ".join(sorted(velhas)[:3])
            print(f"  {len(velhas):3d}x  {mk} {md} | {nova!r:22} <- {exemplos}")

        # ── Trim que o catálogo não reconheceu ──────────────────
        # Sai no relatório porque é a fila de curadoria: o que aparece muito
        # aqui é candidato a entrar no suplemento ou virar sinônimo.
        desconhecidos: Counter = Counter()
        for r in rows:
            nova = depois_map[r["id"]][0]
            if nova and nova != VERSAO_AGREGADA:
                for t in nova.split():
                    desconhecidos[(r["marca"] or "", r["modelo"] or "", t)] += 1
        try:
            from src.catalog.loader import canonizar_trim

            sem_catalogo = Counter(
                {k: v for k, v in desconhecidos.items()
                 if not canonizar_trim(k[0], k[1], k[2])}
            )
            print(f"\n--- Top 20 trims fora do catálogo (fila de curadoria) ---")
            for (mk, md, t), n in sem_catalogo.most_common(20):
                print(f"  {n:5d}  {mk} {md} | {t}")
        except Exception as exc:  # pragma: no cover
            print(f"(vocabulário de trim indisponível: {exc})")

        print("\n--- Amostra de 30 mudanças ---")
        for id_, velho, novo in mudancas[:30]:
            print(f"  #{id_}")
            print(f"      antes: versao={velho[0]!r} geracao={velho[1]!r} "
                  f"motor={velho[2]!r} obs={velho[3]!r}")
            print(f"      depois: versao={novo[0]!r} geracao={novo[1]!r} "
                  f"motor={novo[2]!r} obs={novo[3]!r}")

        if not aplicar:
            print("\nDry-run — nada foi alterado. Rode com --apply pra gravar.")
            return

        if limite:
            print("\nERRO: --apply com --limite gravaria só parte da base "
                  "(o relatório de desfragmentação sairia enviesado). "
                  "Rode o dry-run com --limite e o --apply sem ele.")
            sys.exit(1)

        print("\nGerando backup antes de aplicar...")
        caminho = fazer_backup()
        if caminho is None:
            print("ERRO: backup falhou — abortando pra não gravar sem rede de segurança.")
            sys.exit(1)
        print(f"Backup criado: {caminho}")

        print(f"\nAplicando {len(mudancas)} atualizações...")
        with conn.cursor() as cur:
            for id_, _velho, novo in mudancas:
                cur.execute(
                    "UPDATE anuncios SET versao = %s, geracao = %s, "
                    "motor = %s, obs = %s WHERE id = %s",
                    (novo[0], novo[1], novo[2], novo[3], id_),
                )
        print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
