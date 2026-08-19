"""
Mede se o Web Unlocker do Bright Data passa o muro do Mercado Livre.

Contexto: o ML redireciona toda listagem pra /gz/account-verification desde
17/08/2026. O Scrapfly vence o muro com proxy residencial + JS + 8s de espera
(medido em 19/08: 24 requisições, 100% de sucesso), mas cobra US$ 30/mês de
piso. O Bright Data dá 5.000 requisições/mês no plano gratuito permanente -
30x o que precisamos - e por isso é o primeiro da fila.

A diferença que este teste existe pra resolver: o Unlocker é CAIXA-PRETA.
Não se pede "residencial com 8 segundos"; manda-se a URL e o motor decide.
Pode tratar o desafio melhor que a receita que achamos, ou pode não esperar o
bastante. Não dá pra saber sem medir.

Requer uma zona do tipo `unblocker` criada no painel (o token de API não cria
zona sem permissão de admin).

Uso:
    python scripts/testar_brightdata.py
    python scripts/testar_brightdata.py --zona minha_zona --paginas 3
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(RAIZ / ".env")

import bs4
import requests

# O lxml devolve ZERO elementos na listagem renderizada do ML, que passa de
# 1,7 MB - limite do libxml2. O html.parser devolve os 48 cards. Medido em
# 19/08; sem esta troca o teste conclui que o fornecedor não serve, quando o
# problema é do nosso parser.
_bs_original = bs4.BeautifulSoup


def _bs(markup, features="lxml", **kw):
    return _bs_original(markup, "html.parser", **kw)


import src.connectors.mercadolivre as ml  # noqa: E402

ml.BeautifulSoup = _bs

API_ZONAS = "https://api.brightdata.com/zone/get_active_zones"
API_REQUEST = "https://api.brightdata.com/request"


def _token() -> str:
    t = os.environ.get("BRIGHTDATA_TOKEN", "").strip()
    if not t:
        raise SystemExit("Falta BRIGHTDATA_TOKEN no .env.")
    return t


def descobrir_zona(token: str) -> str | None:
    r = requests.get(API_ZONAS, headers={"Authorization": f"Bearer {token}"}, timeout=40)
    if r.status_code != 200:
        print(f"não consegui listar zonas ({r.status_code}): {r.text[:160]}")
        return None
    zonas = r.json() or []
    if not zonas:
        print("Nenhuma zona na conta. Crie uma do tipo 'Web Unlocker API' no")
        print("painel (brightdata.com/cp -> Proxies & Scraping -> Add).")
        return None
    print("zonas na conta:", ", ".join(f"{z.get('name')}({z.get('type')})" for z in zonas))
    for z in zonas:
        if "unblock" in str(z.get("type", "")).lower():
            return z["name"]
    return zonas[0]["name"]


def buscar(token: str, zona: str, url: str) -> tuple[str | None, str]:
    r = requests.post(
        API_REQUEST,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"zone": zona, "url": url, "format": "raw", "country": "br"},
        timeout=180,
    )
    if r.status_code != 200:
        return None, f"http {r.status_code}: {r.text[:180]}"
    h = r.text
    if "account-verification" in h[:5000]:
        return None, "caiu no muro de verificação"
    if "requires JavaScript" in h:
        return None, "parou no desafio JavaScript (faltou espera)"
    # O Unlocker recusa URL que o robots.txt do alvo proíbe, e a recusa vem
    # como 200 com um corpo de duas linhas. Sem esta checagem o teste dá
    # "funciona" para uma resposta de 252 bytes - aconteceu em 19/08.
    if "Residential Failed" in h or "bad_endpoint" in h:
        return None, f"recusado pelo fornecedor: {h[:150]}"
    if len(h) < 50_000:
        return None, f"resposta curta demais ({len(h)} bytes) - não é listagem"
    return h, "ok"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--zona", default=None)
    p.add_argument("--paginas", type=int, default=3)
    args = p.parse_args()

    token = _token()
    zona = args.zona or descobrir_zona(token)
    if not zona:
        return 1
    print(f"usando a zona: {zona}\n")

    vistos: set[str] = set()
    ok = 0
    for pg in range(1, args.paginas + 1):
        url = ml._url_categoria("carros-antigos", pg, None)
        h, estado = buscar(token, zona, url)
        if h is None:
            print(f"pág {pg}: {estado}")
        else:
            cards = ml._urls_cards(h)
            anuncios = ml._parsear_listagem(h, "2026-08-19")
            for a in anuncios:
                vistos.add(a.url)
            ok += 1
            print(f"pág {pg}: ok  {len(h):>9,} bytes  cards={len(cards):>3}  "
                  f"válidos={len(anuncios):>3}  únicos acumulados={len(vistos)}")
        time.sleep(2)

    print("\n" + "=" * 62)
    print(f"{ok}/{args.paginas} páginas, {len(vistos)} anúncios únicos")
    if ok == args.paginas and vistos:
        print("FUNCIONA - e dentro da cota gratuita de 5.000/mês o custo é zero.")
    elif ok:
        print("Funciona em parte. Taxa de sucesso baixa muda a conta de créditos.")
    else:
        print("Não passou. O caixa-preta do Unlocker não deu conta do desafio;")
        print("o próximo da fila é o ScrapingBee, que reproduz a receita exata.")
    return 0 if ok == args.paginas else 1


if __name__ == "__main__":
    raise SystemExit(main())
