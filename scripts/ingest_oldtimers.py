"""
Ingest do catálogo the-oldtimers.com -> data/base_marcamodelo_intl.csv

Fonte: https://the-oldtimers.com/database/ (WordPress + wpDataTables).
A tabela é server-side: o HTML da página não traz os dados, mas expõe um
endpoint AJAX que devolve a base inteira em JSON numa única requisição.

    POST /wp-admin/admin-ajax.php?action=get_wdtable&table_id=1
         draw=1&start=0&length=<N>&wdtNonce=<nonce>

O nonce sai do próprio HTML da página (input `wdtNonceFrontendServerSide_1`)
e é obrigatório — sem ele o endpoint devolve corpo vazio com HTTP 200.
robots.txt do site libera tudo (`Disallow:` vazio); ainda assim a coleta é
uma requisição só, sem paginação e sem carga.

Formato de cada linha do JSON (medido 2026-08-04, 23.174 linhas):
    [marca, variante, ano, modelo, foto_html, id, ordem]
Repare que MODELO é a coluna 3, não a 1 — a coluna 1 é a variante/trim.
A granularidade é um registro por modelo-ano, então a faixa de produção
(ano_min/ano_max) sai por agregação.

O CSV gerado é material de CONSULTA, isolado do catálogo canônico — ver
src/catalog/externo.py pro porquê. Não é lido pelo pipeline.

Uso:
    python scripts/ingest_oldtimers.py --limite 200   # smoke test
    python scripts/ingest_oldtimers.py                # coleta completa
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.catalog.externo import BASE_INTL_CSV, marca_canonica
from src.pipeline.normalizer import normalizar_texto

URL_PAGINA = "https://the-oldtimers.com/database/"
URL_AJAX = "https://the-oldtimers.com/wp-admin/admin-ajax.php?action=get_wdtable&table_id=1"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Antes de 1900 a base tem protótipos soltos; depois de 2004 não há nada.
# O corte de baixo evita linhas com ano de 2 dígitos mal digitado.
ANO_MINIMO = 1900
ANO_MAXIMO = 2010

# A coluna "variante" mistura trim de verdade ('Carrera 2.7 RS', 'GTV') com
# cilindrada solta (',1.6', '0.4', '1300'). Só o que sobra depois deste corte
# entra na coluna `versoes` — o mesmo critério de spec-vs-trim que o catálogo
# canônico usa em `_SPEC_VERSAO_RE`, adaptado ao ruído desta fonte.
_VARIANTE_SO_SPEC = re.compile(r"^[\d.,\s]*$|^\d[.,]\d\s*[LT]?$", re.IGNORECASE)


def _nonce(sessao: requests.Session) -> str:
    """Extrai o nonce do wpDataTables do HTML da página pública."""
    resp = sessao.get(URL_PAGINA, timeout=60)
    resp.raise_for_status()
    achado = re.search(
        r'name="wdtNonceFrontendServerSide_1"\s+value="([a-f0-9]+)"', resp.text
    )
    if not achado:
        raise RuntimeError(
            "nonce do wpDataTables não encontrado no HTML — o site provavelmente "
            "mudou de plugin ou de versão; reveja o seletor."
        )
    return achado.group(1)


def baixar(limite: Optional[int] = None) -> list[list]:
    """Baixa as linhas cruas da tabela. `limite` recorta pro smoke test."""
    sessao = requests.Session()
    sessao.headers.update({"User-Agent": USER_AGENT, "Referer": URL_PAGINA})

    token = _nonce(sessao)
    resp = sessao.post(
        URL_AJAX,
        data={
            "draw": "1",
            "start": "0",
            "length": str(limite or 30000),
            "search[value]": "",
            "sRangeSeparator": "|",
            "wdtNonce": token,
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=180,
    )
    resp.raise_for_status()
    payload = resp.json()

    total = payload.get("recordsTotal")
    linhas = payload.get("data") or []
    print(f"the-oldtimers: {len(linhas)} linhas baixadas (total na fonte: {total})",
          file=sys.stderr)
    if not linhas:
        raise RuntimeError("endpoint devolveu zero linhas — nonce inválido?")
    return linhas


def _variante_limpa(bruto: Optional[str]) -> Optional[str]:
    """Devolve a variante como trim, ou None se for só cilindrada/ruído."""
    if not bruto:
        return None
    texto = html.unescape(str(bruto)).strip().strip(",").strip()
    if not texto or _VARIANTE_SO_SPEC.match(texto):
        return None
    return normalizar_texto(texto)


def agregar(linhas: list[list]) -> list[dict]:
    """
    Agrega as linhas modelo-ano em uma linha por (marca, modelo), com a faixa
    de anos e o vocabulário de variantes.
    """
    anos: dict[tuple[str, str], set[int]] = defaultdict(set)
    versoes: dict[tuple[str, str], set[str]] = defaultdict(set)
    descartadas = 0

    for linha in linhas:
        if len(linha) < 4:
            descartadas += 1
            continue

        marca = marca_canonica(html.unescape(str(linha[0] or "")).strip())
        modelo = normalizar_texto(html.unescape(str(linha[3] or "")).strip())
        if not marca or not modelo:
            descartadas += 1
            continue

        bruto_ano = str(linha[2] or "").strip()
        if not bruto_ano.isdigit():
            descartadas += 1
            continue
        ano = int(bruto_ano)
        if not ANO_MINIMO <= ano <= ANO_MAXIMO:
            descartadas += 1
            continue

        chave = (marca, modelo)
        anos[chave].add(ano)
        variante = _variante_limpa(linha[1])
        if variante:
            versoes[chave].add(variante)

    if descartadas:
        print(f"linhas descartadas (sem marca/modelo/ano válido): {descartadas}",
              file=sys.stderr)

    saida = []
    for (marca, modelo), conjunto in sorted(anos.items()):
        saida.append(
            {
                "marca": marca,
                "modelo": modelo,
                "ano_min": min(conjunto),
                "ano_max": max(conjunto),
                "anos_distintos": len(conjunto),
                "versoes": "|".join(sorted(versoes[(marca, modelo)])),
                "fonte": "the-oldtimers.com",
            }
        )
    return saida


def gravar(registros: list[dict], destino: Path) -> None:
    campos = ["marca", "modelo", "ano_min", "ano_max", "anos_distintos", "versoes", "fonte"]
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(registros)
    print(f"gravado: {destino} ({len(registros)} pares marca/modelo)", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limite", type=int, default=None,
        help="baixa só as N primeiras linhas (smoke test antes da coleta cheia)",
    )
    parser.add_argument(
        "--saida", type=Path, default=BASE_INTL_CSV,
        help=f"CSV de destino (padrão: {BASE_INTL_CSV})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="não grava; só imprime uma amostra do que sairia",
    )
    args = parser.parse_args()

    registros = agregar(baixar(args.limite))

    if args.dry_run:
        print(f"\n--- dry-run: {len(registros)} pares, amostra de 15 ---", file=sys.stderr)
        for r in registros[:15]:
            print(f"  {r['marca']:<18} {r['modelo']:<22} "
                  f"{r['ano_min']}-{r['ano_max']}  versoes={r['versoes'][:60]}",
                  file=sys.stderr)
        return

    gravar(registros, args.saida)


if __name__ == "__main__":
    main()
