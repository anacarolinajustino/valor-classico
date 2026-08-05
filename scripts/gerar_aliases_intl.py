"""
Gera data/aliases_intl.csv — ponte entre a grafia PT-BR do banco e a grafia
em inglês das fontes estrangeiras.

O problema: as duas fontes externas (the-oldtimers, classic.com) são em
inglês, e boa parte dos pares do banco que "não existem" lá na verdade
existem com outro nome. Medido 2026-08-04, o match literal cobria 64 dos 401
pares órfãos; parte grande do resto é só tradução ou espaçamento:

    banco             fonte externa
    BMW SERIE 3       BMW 3 SERIES
    MERCEDES CLASSE C MERCEDES-BENZ C
    LEXUS ES300       LEXUS ES 300

Cada linha do CSV traz a REGRA que produziu o alias e a fonte onde o nome em
inglês foi confirmado, então dá pra revisar por classe de regra em vez de
uma a uma. As linhas de regra `fuzzy` são candidatas, não certezas: saem
ordenadas por similaridade justamente pra serem trianguladas antes de usar.

O CSV é material de CONSULTA, isolado do catálogo canônico — ver
src/catalog/externo.py. Não é lido pelo pipeline.

Uso:
    python scripts/gerar_aliases_intl.py --dry-run
    python scripts/gerar_aliases_intl.py
"""
from __future__ import annotations

import argparse
import csv
import difflib
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.catalog.externo import (
    ALIASES_INTL_CSV,
    BASE_INTL_CSV,
    VOCABULARIO_CSV,
    chave_alfanumerica,
)
from src.catalog.loader import carregar_catalogo
from src.pipeline.normalizer import normalizar_texto
from src.pipeline.persistence import _connect

# Similaridade mínima pro palpite fuzzy. 0.85 é mais apertado que o 0.80 do
# loader de propósito: aqui um falso positivo cria um alias errado que fica
# gravado no CSV, enquanto no loader ele só afeta um match em memória.
LIMIAR_FUZZY = 0.85


def _pares_do_banco() -> list[tuple[str, str, int]]:
    """(marca, modelo, n_anuncios) distintos do banco, do mais comum ao menos."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT marca, modelo, COUNT(*) AS n
                FROM anuncios
                WHERE marca IS NOT NULL AND marca <> ''
                  AND modelo IS NOT NULL AND modelo <> ''
                GROUP BY marca, modelo
                ORDER BY n DESC
                """
            )
            return [(r["marca"], r["modelo"], r["n"]) for r in cur.fetchall()]


def _modelos_externos() -> dict[str, dict[str, str]]:
    """marca -> {modelo_normalizado: fonte} reunindo as duas fontes externas."""
    por_marca: dict[str, dict[str, str]] = defaultdict(dict)
    for caminho, fonte in ((BASE_INTL_CSV, "the-oldtimers.com"),
                           (VOCABULARIO_CSV, "classic.com")):
        try:
            with open(caminho, encoding="utf-8", newline="") as f:
                for linha in csv.DictReader(f):
                    marca = (linha.get("marca") or "").strip()
                    modelo = (linha.get("modelo") or "").strip()
                    if marca and modelo:
                        por_marca[marca].setdefault(modelo, fonte)
        except FileNotFoundError:
            print(f"AVISO: {caminho.name} não existe — rode o ingest antes.",
                  file=sys.stderr)
    return por_marca


def _numerico_demais(modelo: str) -> bool:
    """
    True se o modelo é dominado por dígitos ('600R', 'C250', '2335', '120').

    Nesses nomes o difflib é enganoso: um dígito a mais ou a menos ainda dá
    similaridade alta, e o resultado é sempre um carro DIFERENTE — a rodada
    anterior produzia 'C250'->'250', '2335'->'335' e 'D400'->'400', que são
    três erros. Nome com letra ('CRISTLINE', 'GIULI') não tem esse problema,
    e é lá que o fuzzy acerta typo de anunciante.
    """
    letras = sum(c.isalpha() for c in modelo)
    digitos = sum(c.isdigit() for c in modelo)
    return digitos > 0 and letras <= 1


def _candidatos_por_regra(modelo: str) -> list[tuple[str, str]]:
    """
    Formas alternativas do modelo, com o nome da regra que as produziu.
    Só transformações determinísticas — o palpite fuzzy vem depois.
    """
    saida: list[tuple[str, str]] = []

    # "SERIE 3" -> "3 SERIES" (BMW; o banco herdou a grafia PT do ML)
    achado = re.match(r"^SERIE\s+(\w+)$", modelo)
    if achado:
        saida.append((f"{achado.group(1)} SERIES", "serie_n"))

    # "CLASSE C" -> "C" e "C-CLASS" (classic.com usa a letra sozinha)
    achado = re.match(r"^CLASSE\s+(\w+)$", modelo)
    if achado:
        letra = achado.group(1)
        saida.append((letra, "classe_x"))
        saida.append((f"{letra} CLASS", "classe_x"))

    return saida


def gerar() -> list[dict]:
    externos = _modelos_externos()
    catalogo = carregar_catalogo()

    # Índice alfanumérico por marca: casa 'ES300' com 'ES 300', 'LS 400' com
    # 'LS400' — divergência de espaçamento, não de nome.
    idx_alfa: dict[str, dict[str, str]] = {}
    for marca, modelos in externos.items():
        idx_alfa[marca] = {}
        for modelo in modelos:
            idx_alfa[marca].setdefault(chave_alfanumerica(modelo), modelo)

    aliases: list[dict] = []
    for marca_bruta, modelo_bruto, n in _pares_do_banco():
        marca = normalizar_texto(marca_bruta)
        modelo = normalizar_texto(modelo_bruto)

        modelos_marca = externos.get(marca)
        if not modelos_marca:
            continue  # marca inexistente nas fontes externas (caso do carro nacional)

        # NB: pares que JÁ estão no catálogo canônico continuam valendo alias.
        # 'BMW SERIE 3' e 'MERCEDES-BENZ CLASSE C' estão no _SUPLEMENTO do
        # loader desde as auditorias anteriores, mas é justamente pra eles que
        # a ponte serve — sem saber que lá fora se chamam '3 SERIES' e 'C',
        # não há como consultar geração nem faixa de ano nas fontes externas.

        # Match literal já resolve — não é alias.
        if modelo in modelos_marca:
            continue

        encontrado: tuple[str, str, str] | None = None

        # 1. Regras determinísticas de tradução.
        for candidato, regra in _candidatos_por_regra(modelo):
            if candidato in modelos_marca:
                encontrado = (candidato, regra, modelos_marca[candidato])
                break

        # 2. Só espaçamento/separador difere.
        if not encontrado:
            alvo = idx_alfa[marca].get(chave_alfanumerica(modelo))
            if alvo and alvo != modelo:
                encontrado = (alvo, "espacamento", modelos_marca[alvo])

        # 3. Palpite fuzzy dentro da mesma marca — só pra nome com letra.
        if not encontrado and not _numerico_demais(modelo):
            proximos = [
                m for m in difflib.get_close_matches(
                    modelo, list(modelos_marca), n=3, cutoff=LIMIAR_FUZZY
                )
                if not _numerico_demais(m)
            ]
            if proximos:
                alvo = proximos[0]
                encontrado = (alvo, "fuzzy", modelos_marca[alvo])

        if encontrado:
            alvo, regra, fonte = encontrado
            aliases.append(
                {
                    "marca": marca,
                    "modelo_ptbr": modelo,
                    "modelo_intl": alvo,
                    "regra": regra,
                    "fonte": fonte,
                    "n_anuncios": n,
                    "similaridade": round(
                        difflib.SequenceMatcher(None, modelo, alvo).ratio(), 3
                    ),
                }
            )

    # Determinísticos primeiro, fuzzy por último (do mais parecido ao menos) —
    # a ordem em que vale a pena revisar.
    ordem_regra = {"serie_n": 0, "classe_x": 1, "espacamento": 2, "fuzzy": 3}
    aliases.sort(key=lambda a: (ordem_regra[a["regra"]], -a["similaridade"], -a["n_anuncios"]))
    return aliases


def gravar(aliases: list[dict], destino: Path) -> None:
    campos = ["marca", "modelo_ptbr", "modelo_intl", "regra", "fonte",
              "n_anuncios", "similaridade"]
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(aliases)
    print(f"gravado: {destino} ({len(aliases)} aliases)", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path, default=ALIASES_INTL_CSV)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    aliases = gerar()

    por_regra: dict[str, int] = defaultdict(int)
    for a in aliases:
        por_regra[a["regra"]] += 1
    print("aliases por regra: " + ", ".join(
        f"{k}={v}" for k, v in sorted(por_regra.items())), file=sys.stderr)

    if args.dry_run:
        print(f"\n--- dry-run: {len(aliases)} aliases ---", file=sys.stderr)
        for a in aliases[:30]:
            print(f"  [{a['regra']:<12}] {a['marca']:<16} "
                  f"{a['modelo_ptbr']:<18} -> {a['modelo_intl']:<20} "
                  f"(sim={a['similaridade']}, n={a['n_anuncios']})", file=sys.stderr)
        return

    gravar(aliases, args.saida)


if __name__ == "__main__":
    main()
