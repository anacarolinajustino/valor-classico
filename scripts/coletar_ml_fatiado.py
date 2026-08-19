"""
Coleta o Mercado Livre por FATIAMENTO, dentro do que o robots.txt permite.

Por que fatiar em vez de paginar: desde 17/08/2026 o ML exige verificação de
conta em toda listagem, e o robots.txt marca `_Desde_` e `_NoIndex_True` - os
parâmetros de paginação - como Disallow. O Web Unlocker do Bright Data
respeita isso e recusa a página 2 em diante:

    Residential Failed (bad_endpoint): Requested site is not available for
    immediate residential (no KYC) access mode in accordance with robots.txt

Mas `_YearRange_` e marca/modelo no caminho são PERMITIDOS. Então em vez de
pedir a página 2 de uma listagem grande, pedimos a página 1 de listagens
menores - o mesmo que o conector da OLX já faz por faixa de ano. Cada fatia
rende até 48 anúncios; quando satura, desce um nível na árvore:

    ano  ->  ano + marca  ->  ano + marca + modelo

Desce só quando a fatia devolve EXATAMENTE 48, o tamanho da página: 47 ou
menos é a fatia inteira, e descer ali gasta requisição pra não achar nada.
Medido no piloto de 19/08 - 1972 devolveu 48 e a soma das marcas deu 48
(completo), 1995 devolveu 48 e as marcas somaram 144 (truncado de verdade).

Uso:
    python scripts/coletar_ml_fatiado.py --piloto      # 1970-1975, valida
    python scripts/coletar_ml_fatiado.py --max-req 600
    python scripts/coletar_ml_fatiado.py --gravar      # upsert no banco
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(RAIZ / ".env")

import bs4
import requests

# O lxml devolve ZERO elemento na listagem renderizada do ML (passa de 1,7 MB;
# limite do libxml2). O html.parser devolve os 48 cards. Medido em 19/08.
_bs_original = bs4.BeautifulSoup


def _bs(markup, features="lxml", **kw):
    return _bs_original(markup, "html.parser", **kw)


import src.connectors.mercadolivre as ml  # noqa: E402

ml.BeautifulSoup = _bs

from src.catalog.loader import carregar_catalogo  # noqa: E402

API = "https://api.brightdata.com/request"
BASE = "https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes"
ESTADO = RAIZ / "data" / ".ml_fatiado.json"

ANO_MIN, ANO_MAX = 1900, 2000
# 48 é o tamanho da página. Uma fatia que devolve EXATAMENTE 48 está
# truncada; 47 ou menos é a fatia inteira. O piloto de 19/08 mostrou os dois
# casos: 1972 devolveu 48 e a soma das marcas deu exatamente 48 (completo),
# enquanto 1995 devolveu 48 e as marcas somaram 144 (truncado). Usar um corte
# frouxo como 44 faria descer em fatia completa e gastar 22 requisições pra
# não achar nada.
PAGINA_CHEIA = 48
PAUSA = 1.0
# Fatia vazia é quase sempre renderização incompleta, não ausência de estoque
# - o mesmo engano que zerou o socarrao. Ford/1995 devolveu 0 num teste e
# tinha anúncios. Uma segunda tentativa separa os dois casos.
TENTATIVAS = 2

# Ordem de densidade medida no snapshot de julho: descer primeiro pelas marcas
# que concentram anúncio evita gastar requisição em fatia vazia.
MARCAS_DENSAS = [
    "VOLKSWAGEN", "CHEVROLET", "FORD", "FIAT", "TOYOTA", "MERCEDES-BENZ",
    "HONDA", "DODGE", "BMW", "PUMA", "JEEP", "MITSUBISHI", "PEUGEOT",
    "RENAULT", "NISSAN", "VOLVO", "CITROEN", "AUDI", "PORSCHE", "JAGUAR",
    "WILLYS", "GURGEL",
]


def slug(texto: str) -> str:
    """MERCEDES-BENZ -> mercedes-benz, igual ao caminho do site."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()


def url_fatia(ano: int, marca: str | None = None, modelo: str | None = None) -> str:
    partes = [BASE]
    if marca:
        partes.append(slug(marca))
    if modelo:
        partes.append(slug(modelo))
    return "/".join(partes) + f"/_YearRange_{ano}-{ano}"


class Coletor:
    def __init__(self, token: str, zona: str):
        self.token, self.zona = token, zona
        self.requisicoes = 0
        self.recusadas = 0
        self.vazias = 0

    def buscar(self, url: str):
        """(anúncios, cards) ou None quando a fatia não pôde ser lida."""
        self.requisicoes += 1
        try:
            r = requests.post(
                API,
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json"},
                json={"zone": self.zona, "url": url, "format": "raw",
                      "country": "br"},
                timeout=180,
            )
        except Exception as exc:
            print(f"      erro de rede: {type(exc).__name__}")
            return None
        h = r.text
        if "Residential Failed" in h or "bad_endpoint" in h:
            self.recusadas += 1
            return None
        if len(h) < 50_000:
            self.vazias += 1
            return None
        return ml._parsear_listagem(h, date.today().isoformat()), len(ml._urls_cards(h))

    def buscar_firme(self, url: str):
        """Repete antes de aceitar vazio - ver TENTATIVAS."""
        for i in range(TENTATIVAS):
            r = self.buscar(url)
            if r is not None and r[1]:
                return r
            if i + 1 < TENTATIVAS:
                time.sleep(PAUSA * 2)
        return None


def main() -> int:
    token = os.environ.get("BRIGHTDATA_TOKEN", "").strip()
    if not token:
        raise SystemExit("Falta BRIGHTDATA_TOKEN no .env.")

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--zona", default="web_unlocker1")
    p.add_argument("--max-req", type=int, default=600)
    p.add_argument("--piloto", action="store_true")
    p.add_argument("--gravar", action="store_true")
    args = p.parse_args()

    modelos_de: dict[str, list[str]] = {}
    for mk, md in carregar_catalogo():
        modelos_de.setdefault(mk, []).append(md)

    anos = range(1970, 1976) if args.piloto else range(ANO_MIN, ANO_MAX + 1)
    col = Coletor(token, args.zona)
    achados: dict[str, dict] = {}
    t0 = time.time()

    def registrar(anuncios) -> int:
        novos = 0
        for a in anuncios:
            if a.url not in achados:
                achados[a.url] = {
                    "url": a.url, "titulo": a.titulo, "marca": a.marca,
                    "modelo": a.modelo, "ano": a.ano, "preco": a.preco,
                    "versao": a.versao, "obs": a.obs,
                }
                novos += 1
        return novos

    for ano in anos:
        if col.requisicoes >= args.max_req:
            print(f"\n[teto de {args.max_req} requisições atingido]")
            break
        r = col.buscar_firme(url_fatia(ano))
        if r is None:
            print(f"{ano}: fatia ilegível")
            time.sleep(PAUSA)
            continue
        anuncios, cards = r
        novos = registrar(anuncios)
        print(f"{ano}: {cards:>3} cards, {len(anuncios):>3} válidos, {novos:>3} novos "
              f"(total {len(achados)}, req {col.requisicoes})")
        time.sleep(PAUSA)

        if cards < PAGINA_CHEIA:
            continue

        print(f"   {ano} saturou - descendo por marca")
        for marca in MARCAS_DENSAS:
            if col.requisicoes >= args.max_req:
                break
            rm = col.buscar_firme(url_fatia(ano, marca))
            time.sleep(PAUSA)
            if rm is None:
                continue
            am, cm = rm
            nm = registrar(am)
            if cm or nm:
                print(f"      {marca:<15}{cm:>3} cards, {nm:>3} novos "
                      f"(total {len(achados)})")
            if cm < PAGINA_CHEIA:
                continue
            for modelo in modelos_de.get(marca, [])[:14]:
                if col.requisicoes >= args.max_req:
                    break
                rr = col.buscar_firme(url_fatia(ano, marca, modelo))
                time.sleep(PAUSA)
                if rr is None:
                    continue
                aa, cc = rr
                nn = registrar(aa)
                if nn:
                    print(f"         {marca} {modelo:<18}{cc:>3} cards, "
                          f"{nn:>3} novos (total {len(achados)})")

    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(list(achados.values()), ensure_ascii=False),
                      encoding="utf-8")
    print("\n" + "=" * 66)
    print(f"{col.requisicoes} requisições em {(time.time() - t0) / 60:.0f} min "
          f"({col.recusadas} recusadas pelo robots, {col.vazias} sem conteúdo)")
    print(f"{len(achados):,} anúncios únicos -> {ESTADO}")

    if args.gravar and achados:
        from src.pipeline.persistence import upsert_anuncios
        from src.pipeline.schema import Anuncio
        hoje = date.today().isoformat()
        lote = [Anuncio(titulo=a["titulo"], preco=a["preco"], marca=a["marca"],
                        modelo=a["modelo"], ano=a["ano"], versao=a["versao"],
                        obs=a["obs"], url=a["url"], fonte="mercadolivre",
                        data_coleta=hoje) for a in achados.values()]
        print("upsert:", upsert_anuncios(lote))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
