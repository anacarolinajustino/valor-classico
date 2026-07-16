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

# Reclassificações que o reprocessamento por TÍTULO encontraria mas que já
# foram corrigidas por uma fonte mais confiável que o título sozinho —
# reprocessar reverteria a correção. Formato: (marca_antiga, marca_nova) a pular.
_EXCLUIR: set[tuple[str, str]] = {
    # "Ap 2000,injecao,4 portas..." — "AP" é o código do motor VW no
    # título, não a marca; a real (Ford Versailles) só apareceu na ficha
    # técnica do anúncio #34724 (ver src/connectors/mercadolivre.py).
    ("FORD", "AP"),
    # Auditoria 2026-07-15 (2ª rodada) — correções manuais pontuais onde a
    # marca real está no MEIO/FIM do título, não no prefixo. A inferência
    # por título sozinho não alcança esses casos (só olha prefixo/fallback
    # 1º token) e reverteria pra marca-lixo se reprocessada às cegas.
    ("YAMAHA", "DT"),            # #572  "DT 180 Z" — DT é código de modelo Yamaha
    ("YAMAHA", "RD"),            # #573  "RD 135 1988/89" — idem
    ("MONARK", "MONARETA"),      # #1736 "Monareta Monark AVX" — Monareta é o modelo
    ("HONDA", "CB"),             # #6169 "CB 360 Cafe Racer" — CB é código de modelo Honda
    ("MERCEDES-BENZ", "EXCLUSIVA"),  # #6424 "Exclusiva Mercedes Benz SL190"
    ("VOLKSWAGEN", "GOL."),      # #34963 "Gol. 1.3..." — ponto colado quebra o parsing
    ("PONTIAC", "IMP"),          # #35160 "Imp / Pontiac Trans Sport" — Imp = "importado"
    ("CHEVROLET", "MARTA"),      # #35231 "Marta Rocha Chevrolet" — marca no fim do título
    ("LANZ", "LOCOMOVEL"),       # #35283 "Locomóvel...Heinrich Lanz" — marca no fim
    ("CADILLAC", "LIMOUSINE"),   # #36518 "Limousine Fleetwood" — Fleetwood é linha Cadillac
    # Verificação geral 2026-07-15 (3ª rodada) — mais correções pontuais
    # com marca no meio/fim do título ou exigindo conhecimento externo
    # (typo de modelo, sub-marca) que o algoritmo não alcança.
    ("WILLYS", "AERO"),          # #643   "Aero Willys 2600" — Aero-Willys é a linha, marca é Willys
    ("FORD", "NAO IDENTIFICADA"),  # #18447 "Carro de Coleção! Escort..." — "DE" não é prefixo (colide com "De Soto"/"De Tomaso") e agora está na stoplist de _PALAVRAS_NAO_MARCA
    ("FORD", "29"),              # #34736 "Hot Rod 29 V8 Ford Tudor..." — "29" é o ano abreviado (Ford 1929), não marca
    ("VOLKSWAGEN", "PASSAR"),    # #34906 "Passar Ts 1978" — typo de "Passat" (TS é versão real do Passat)
    ("CHEVROLET", "C1404"),      # #35040 "Picape C1404 - D10 Diesel..." — D10 confirma Chevrolet, C1404 não é marca
    ("CHEVROLET", "PERFEITO"),   # #36076 "Perfeito Barn Find Rat Look - Bel Air 55..." — Bel Air é modelo Chevrolet
    # Candidatos ambíguos demais pra aceitar como marca (nome próprio ou
    # código não identificável com confiança) — marcados manualmente como
    # NAO IDENTIFICADA; sem esta entrada, reprocessar por título reverteria
    # pro valor-lixo original (a palavra em si não está na stoplist de
    # _PALAVRAS_NAO_MARCA por não ser uma palavra comum de português).
    ("NAO IDENTIFICADA", "BAJA"),    # #35652 fabricante do buggy "Bajanete" desconhecido
    ("NAO IDENTIFICADA", "DAYMER"),  # #36369 possível typo de "Daimler", confiança baixa demais
    ("NAO IDENTIFICADA", "GSI"),     # #35649 "GSi" é sufixo de versão comum a várias marcas, não marca
    ("NAO IDENTIFICADA", "MON"),     # #16330 "Mon Protótipo" — carro único sem marca de fábrica
    ("NAO IDENTIFICADA", "S2"),      # #34780 sem marca real (referência a "Porsche Edition" é estilo, não fabricante)
    ("NAO IDENTIFICADA", "T."),      # #35054 "Hot Rods T. Buket" — resíduo do fallback após pular Hot Rod
    ("NAO IDENTIFICADA", "THREE"),   # #35007 "Three Window Coupe" é estilo de carroceria, não marca
    ("NAO IDENTIFICADA", "V8"),      # #34779/#35418 "V8" é motor, não marca
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
