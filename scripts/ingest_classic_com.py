"""
Ingest da taxonomia classic.com -> data/vocabulario_geracao_trim.csv

Fonte: https://www.classic.com/sitemap-market.xml (3 páginas, 11.191 URLs).

Por que só os sitemaps: as páginas de conteúdo do classic.com são React
(o HTML cru vem com `<h1>` vazio e ~2,6 MB por página), então extrair
especificação exigiria browser. Mas o dado que interessa aqui já está na
ESTRUTURA DA URL, e o sitemap entrega essa estrutura inteira em 3
requisições, sem renderizar nada:

    /m/bmw/3-series/e30/m3/coupe/
       marca / modelo / geração / trim / carroceria

robots.txt permite `/m/` (bloqueia só /chart-data/, /garage/, /partners/,
/tracker/, /sell/list-your-car/). Os termos de uso não puderam ser lidos
(/about/terms-conditions/ devolve HTTP 500 em 2026-08-04), e é mais uma razão
pra ficar nos sitemaps — que existem justamente pra serem lidos por robô — em
vez de raspar conteúdo.

CLASSIFICAÇÃO DOS NÍVEIS: a hierarquia NÃO é posicionalmente rígida. Medido
sobre as 11.191 URLs, o nível 3 é geração na maioria dos casos ('e30', 'w124',
'991', '1st-gen', 'g-body') mas às vezes é carroceria ('coupe'); e os níveis
4 a 7 misturam trim ('m3', 'carrera-4s', 'turbo-s') com carroceria
('cabriolet', 'coupe-manual'). Por isso a classificação aqui é por
VOCABULÁRIO e não por posição.

O CSV gerado é material de CONSULTA, isolado do catálogo canônico — ver
src/catalog/externo.py. Não é lido pelo pipeline.

Uso:
    python scripts/ingest_classic_com.py --limite 1   # smoke test (1 sitemap)
    python scripts/ingest_classic_com.py              # coleta completa
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.catalog.externo import VOCABULARIO_CSV, marca_canonica
from src.pipeline.normalizer import normalizar_texto

SITEMAPS = [
    "https://www.classic.com/sitemap-market.xml",
    "https://www.classic.com/sitemap-market.xml?p=2",
    "https://www.classic.com/sitemap-market.xml?p=3",
]

# UA honesto: o sitemap existe justamente pra ser lido por robô, e o Cloudflare
# do site deixa passar UA de crawler. Não há motivo pra fingir navegador aqui.
USER_AGENT = "valor-classico-bot/1.0 (+catalogo de referencia; contato via repo)"

# POR QUE curl E NÃO requests (medido 2026-08-04):
# o site está atrás de Cloudflare, que faz fingerprint do handshake TLS. Com o
# MESMO User-Agent e a mesma URL, `requests` toma 403 ('cf-mitigated: challenge')
# em 100% das tentativas e `curl` responde 200 em 100% — a diferença é só a
# stack TLS. Playwright com stealth e proxy residencial DataImpulse TAMBÉM toma
# 403 e o challenge nunca resolve (testado com 32s de espera), então subir pra
# browser não adianta e sairia mais caro.
#
# curl.exe é nativo do Windows 10+ (C:\Windows\System32\curl.exe), então não é
# dependência nova. A alternativa seria o pacote curl_cffi, que não vale um
# requirements novo por causa de um script de referência.
_TIMEOUT_S = 90

_LOC = re.compile(r"<loc>https://www\.classic\.com/m/([^<]+)</loc>")

# Carroceria e câmbio. O site combina os dois num segmento só
# ('coupe-manual', 'cabriolet-automatic'), então o sufixo sai antes do teste.
_CARROCERIA = frozenset({
    "coupe", "sedan", "wagon", "cabriolet", "convertible", "roadster", "targa",
    "hardtop", "hard-top", "soft-top", "fastback", "spider", "spyder", "estate",
    "saloon", "hatchback", "liftback", "berlina", "limousine", "phaeton",
    "pickup", "double-cab-pickup", "single-cab-pickup", "suv", "van", "minivan",
    "shooting-brake", "speedster", "touring", "drophead-coupe", "sportback",
})
_CAMBIO_SUFIXO = re.compile(r"-(manual|automatic)$")

# Códigos de geração INEQUÍVOCOS — têm letra, então não se confundem com ano
# nem com trim numérico: '1st-gen', 'e30', 'w124', 'g-body', 'mk2', 's-197-i'.
_GERACAO = re.compile(
    r"^(\d+(st|nd|rd|th)-gen"          # 1st-gen, 12th-gen
    r"|[a-z]{1,2}\d{1,4}[a-z]?"        # e30, w124, s197, r129
    r"|mk[-\s]?\d+([a-z-]+)?"          # mk1, mk2-eu
    r"|[a-z]-body"                     # g-body, f-body
    r"|s-\d+-[iv]+"                    # s-197-i
    r"|gen-\d+"
    r")$"
)

# Código de geração PURAMENTE numérico ('993', '991', '997' da Porsche). Só
# conta como geração no nível 3, que é o slot de geração na convenção do site:
# fora dali um número é quase sempre trim ('325', '740i') ou cilindrada. Mesmo
# assim é ambíguo — a BMW usa o número como trim NO nível 3 também — então
# este é o campo menos confiável dos três (ver docs/fontes_externas.md).
_GERACAO_NUMERICA = re.compile(r"^\d{3}$")
_NIVEL_GERACAO = 2  # índice 2 = terceiro segmento (/m/marca/modelo/AQUI/)

# Ano ou faixa de anos ('1967', '1967-1968'): não é geração nem trim, é recorte
# temporal do próprio site. Descartado pra não poluir os dois vocabulários.
_ANO = re.compile(r"^(19|20)\d{2}([-\s](19|20)\d{2})?$")

# Rótulos de agrupamento do próprio site, não são geração/trim/carroceria.
_PLACEHOLDER = frozenset({
    "base-model", "standard-variants", "standard", "race-cars", "custom",
    "other", "all", "variants", "specials",
})


def _texto(slug: str) -> str:
    """'carrera-4s' -> 'CARRERA 4S'."""
    return normalizar_texto(slug.replace("-", " "))


def _buscar(url: str) -> str:
    """GET via curl (ver comentário sobre fingerprint TLS no topo do módulo)."""
    curl = shutil.which("curl") or r"C:\Windows\System32\curl.exe"
    if not Path(curl).exists() and not shutil.which("curl"):
        raise RuntimeError(
            "curl não encontrado. É nativo do Windows 10+ em System32; "
            "em outro SO, instale curl ou adapte este script."
        )
    proc = subprocess.run(
        [curl, "-sSL", "--max-time", str(_TIMEOUT_S), "-A", USER_AGENT,
         "-w", "\n%{http_code}", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"curl falhou ({proc.returncode}) em {url}: {proc.stderr.strip()}")

    corpo, _, status = proc.stdout.rpartition("\n")
    if status.strip() != "200":
        raise RuntimeError(
            f"HTTP {status.strip()} em {url} — se for 403, o Cloudflare mudou a "
            f"regra e o UA de crawler deixou de passar."
        )
    return corpo


def baixar(limite: int | None = None) -> list[list[str]]:
    """Baixa os sitemaps e devolve os caminhos de /m/ já quebrados em segmentos."""
    caminhos: list[list[str]] = []
    for url in SITEMAPS[:limite] if limite else SITEMAPS:
        achados = _LOC.findall(_buscar(url))
        print(f"{url}: {len(achados)} URLs", file=sys.stderr)
        caminhos.extend([s for s in p.strip("/").split("/") if s] for p in achados)

    if not caminhos:
        raise RuntimeError("nenhuma URL /m/ encontrada nos sitemaps")
    print(f"total: {len(caminhos)} URLs de taxonomia", file=sys.stderr)
    return caminhos


def _classificar(slug: str, nivel: int) -> str:
    """Devolve 'carroceria', 'geracao', 'trim' ou 'descartar'."""
    if slug in _PLACEHOLDER or _ANO.match(slug):
        return "descartar"
    sem_cambio = _CAMBIO_SUFIXO.sub("", slug)
    if sem_cambio in _CARROCERIA:
        return "carroceria"
    if _GERACAO.match(slug):
        return "geracao"
    if nivel == _NIVEL_GERACAO and _GERACAO_NUMERICA.match(slug):
        return "geracao"
    return "trim"


def agregar(caminhos: list[list[str]]) -> list[dict]:
    """Uma linha por (marca, modelo), com os vocabulários acumulados."""
    geracoes: dict[tuple[str, str], set[str]] = defaultdict(set)
    trims: dict[tuple[str, str], set[str]] = defaultdict(set)
    carrocerias: dict[tuple[str, str], set[str]] = defaultdict(set)
    contagem: dict[tuple[str, str], int] = defaultdict(int)

    for segmentos in caminhos:
        if len(segmentos) < 2:
            continue  # /m/{marca}/ sozinho não diz nada de modelo

        marca = marca_canonica(segmentos[0].replace("-", " "))
        modelo = _texto(segmentos[1])
        if not marca or not modelo:
            continue

        chave = (marca, modelo)
        contagem[chave] += 1

        for nivel, slug in enumerate(segmentos):
            if nivel < 2:
                continue
            tipo = _classificar(slug, nivel)
            if tipo == "geracao":
                geracoes[chave].add(_texto(slug))
            elif tipo == "trim":
                trims[chave].add(_texto(slug))
            elif tipo == "carroceria":
                carrocerias[chave].add(_texto(_CAMBIO_SUFIXO.sub("", slug)))

    saida = []
    for chave in sorted(contagem):
        marca, modelo = chave
        saida.append(
            {
                "marca": marca,
                "modelo": modelo,
                "geracoes": "|".join(sorted(geracoes[chave])),
                "trims": "|".join(sorted(trims[chave])),
                "carrocerias": "|".join(sorted(carrocerias[chave])),
                "n_urls": contagem[chave],
                "fonte": "classic.com",
            }
        )
    return saida


def gravar(registros: list[dict], destino: Path) -> None:
    campos = ["marca", "modelo", "geracoes", "trims", "carrocerias", "n_urls", "fonte"]
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(registros)
    print(f"gravado: {destino} ({len(registros)} pares marca/modelo)", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limite", type=int, default=None,
                        help="baixa só os N primeiros sitemaps (smoke test)")
    parser.add_argument("--saida", type=Path, default=VOCABULARIO_CSV)
    parser.add_argument("--dry-run", action="store_true",
                        help="não grava; só imprime uma amostra")
    args = parser.parse_args()

    registros = agregar(baixar(args.limite))

    if args.dry_run:
        print(f"\n--- dry-run: {len(registros)} pares, amostra ---", file=sys.stderr)
        for r in sorted(registros, key=lambda x: -x["n_urls"])[:15]:
            print(f"  {r['marca']:<16} {r['modelo']:<14} "
                  f"ger=[{r['geracoes'][:40]}] trim=[{r['trims'][:40]}] "
                  f"carr=[{r['carrocerias'][:30]}]", file=sys.stderr)
        return

    gravar(registros, args.saida)


if __name__ == "__main__":
    main()
