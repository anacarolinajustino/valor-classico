#!/usr/bin/env python3
"""
Demo de busca — executa o pipeline completo do Valor Clássico para uma
marca e modelo, imprimindo os resultados na saída padrão.

Uso:
    python scripts/demo_busca.py --marca VOLKSWAGEN --modelo KOMBI
    python scripts/demo_busca.py --marca FORD --modelo MUSTANG --paginas 3
"""
from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

# Suprimir avisos de SSL (aceitável para spike/demo local)
warnings.filterwarnings("ignore")

# Adicionar raiz do projeto ao path para imports relativos funcionarem
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.catalog.loader import carregar_catalogo, match_anuncio, resetar_cache
from src.connectors.maxicar import buscar
from src.pipeline.deduplicator import deduplicar
from src.pipeline.normalizer import normalizar_texto
from src.pipeline.outlier_filter import filtrar_outliers
from src.pipeline.schema import validar
from src.pipeline.stats import calcular

CSV_CATALOGO = Path("/Users/ana.justino/Downloads/base_dados_webmotors.csv")


def configurar_logging(verbose: bool) -> None:
    nivel = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=nivel,
        stream=sys.stderr,
    )


def rodar_pipeline(marca: str, modelo: str, paginas: int) -> None:
    print(f"\n{'='*60}")
    print(f"  VALOR CLÁSSICO — DEMO DE BUSCA")
    print(f"  Marca : {marca}")
    print(f"  Modelo: {modelo}")
    print(f"  Fonte : Maxicar (https://www.maxicar.com.br)")
    print(f"{'='*60}\n")

    # 1. Coleta
    print("⏳ Coletando anúncios no Maxicar...")
    anuncios_brutos = buscar(marca, modelo, paginas=paginas)
    print(f"   → {len(anuncios_brutos)} anúncio(s) coletado(s) (antes de validação)\n")

    if not anuncios_brutos:
        print("⚠️  Nenhum anúncio encontrado. Verifique marca/modelo ou acesso à internet.")
        return

    # 2. Validação (descartar sem preço ou sem modelo)
    validos = [a for a in anuncios_brutos if validar(a)]
    print(f"✅ Válidos após validação: {len(validos)} / {len(anuncios_brutos)}")

    # 3. Deduplicação
    deduplicados = deduplicar(validos)
    print(f"🔄 Após deduplicação: {len(deduplicados)}")

    # 4. Filtro de outliers
    filtrados = filtrar_outliers(deduplicados)
    print(f"📊 Após filtro IQR: {len(filtrados)}\n")

    # 5. Matching com catálogo
    resetar_cache()
    if CSV_CATALOGO.exists():
        carregar_catalogo(CSV_CATALOGO)
        com_match = [match_anuncio(a, CSV_CATALOGO) for a in filtrados]
        matched_high = sum(1 for a in com_match if a.match_confidence == "high")
        matched_med = sum(1 for a in com_match if a.match_confidence == "medium")
        print(f"🗂️  Matching catálogo: {matched_high} high | {matched_med} medium | "
              f"{len(com_match)-matched_high-matched_med} unmatched\n")
    else:
        com_match = filtrados
        print("⚠️  CSV do catálogo não encontrado — matching ignorado.\n")

    # 6. Estatísticas
    stats = calcular(com_match)

    print("─" * 50)
    print("  RESULTADOS ESTATÍSTICOS")
    print("─" * 50)
    if stats["amostra"] == 0:
        print("  Sem dados suficientes para calcular estatísticas.")
    else:
        print(f"  Amostra          : {stats['amostra']} anúncio(s)")
        print(f"  Preço médio      : R$ {stats['media']:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        print(f"  Mediana          : R$ {stats['mediana']:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        print(f"  Mínimo           : R$ {stats['minimo']:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        print(f"  Máximo           : R$ {stats['maximo']:>12,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        print(f"  Coleta mais recente: {stats['data_coleta_mais_recente']}")
    print("─" * 50)

    # 7. Listar anúncios
    if com_match:
        print("\n  ANÚNCIOS COLETADOS")
        print("─" * 50)
        for i, a in enumerate(com_match, 1):
            preco_str = f"R$ {a.preco:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if a.preco else "N/D"
            ano_str = str(a.ano) if a.ano else "?"
            conf = a.match_confidence
            print(f"  {i:2d}. [{ano_str}] {a.titulo:<45} {preco_str}  [{conf}]")
            print(f"       {a.url}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demo de busca Valor Clássico — Conector Maxicar"
    )
    parser.add_argument("--marca", required=True, help="Marca do veículo (ex.: VOLKSWAGEN)")
    parser.add_argument("--modelo", required=True, help="Modelo do veículo (ex.: KOMBI)")
    parser.add_argument("--paginas", type=int, default=2, help="Número máximo de páginas (default: 2)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Log detalhado")

    args = parser.parse_args()
    configurar_logging(args.verbose)

    rodar_pipeline(
        marca=normalizar_texto(args.marca),
        modelo=normalizar_texto(args.modelo),
        paginas=args.paginas,
    )


if __name__ == "__main__":
    main()
