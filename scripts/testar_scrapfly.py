"""
Descobre se o Scrapfly passa o muro do Mercado Livre, gastando o mínimo.

O ML redireciona toda listagem pra /gz/account-verification desde 17/08/2026.
O muro é probabilístico (uma sessão passou em ~150 na coleta descontrolada de
18/08), o que é o tipo de defesa que produto de unlocker existe pra vencer -
mas isso é hipótese até medir.

Sobe uma ESCADA de configuração, da mais barata pra mais cara, e para na
primeira que passar. Sem isso o teste começaria pelos 30 créditos por
requisição e queimaria a cota grátis (1.000) em 33 tentativas.

Custo em crédito por requisição, conforme a tabela deles:
    básica (datacenter)    1        residencial          25
    + render_js           +5        residencial + JS     30
Requisição que falha não é cobrada - mas a proteção cai se mais de 30%
falharem numa hora, então o script é deliberadamente curto.

Uso:
    set SCRAPFLY_KEY=scp-live-xxxxx     (ou no .env)
    python scripts/testar_scrapfly.py
    python scripts/testar_scrapfly.py --url https://...   # outro alvo
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

import requests

API = "https://api.scrapfly.io/scrape"
ALVO_PADRAO = "https://lista.mercadolivre.com.br/veiculos/carros-antigos/"

# Da mais barata pra mais cara. `asp` pode subir o pool sozinho, então o
# custo real vem no cabeçalho da resposta, não desta estimativa.
ESCADA = [
    ("datacenter puro",          {"country": "br"},                                        1),
    ("datacenter + ASP",         {"country": "br", "asp": "true"},                        25),
    ("ASP + JS",                 {"country": "br", "asp": "true", "render_js": "true"},   30),
    ("residencial + ASP + JS",   {"country": "br", "asp": "true", "render_js": "true",
                                  "proxy_pool": "public_residential_pool"},               30),
]


def _passou(html: str, url_final: str) -> tuple[bool, str]:
    """O muro do ML é um redirect; o sucesso é a listagem com cards."""
    if "account-verification" in (url_final or "") or "account-verification" in html[:4000]:
        return False, "caiu no muro de verificação"
    marcas = html.count("MLB-") + html.count("/p/MLB")
    if marcas < 5:
        return False, f"passou mas sem anúncios (só {marcas} refs a MLB)"
    return True, f"{marcas} referências a anúncio"


def tentar(chave: str, url: str, rotulo: str, extra: dict, estimado: int) -> bool:
    params = {"key": chave, "url": url, "retry": "false", **extra}
    print(f"\n-- {rotulo}  (~{estimado} créditos)")
    try:
        r = requests.get(API, params=params, timeout=180)
    except Exception as exc:
        print(f"   erro de rede: {type(exc).__name__}: {exc}")
        return False

    custo = r.headers.get("X-Scrapfly-Api-Cost", "?")
    resta = r.headers.get("X-Scrapfly-Remaining-Api-Credit", "?")
    if r.status_code != 200:
        print(f"   http={r.status_code} custo={custo} resta={resta}")
        print(f"   {r.text[:220]}")
        return False

    d = r.json()
    res = d.get("result", {})
    html = res.get("content") or ""
    ok, motivo = _passou(html, res.get("url", ""))
    print(f"   http={r.status_code}  status_alvo={res.get('status_code')}  "
          f"custo={custo}  resta={resta}")
    print(f"   {len(html):,} bytes - {'PASSOU' if ok else 'barrado'}: {motivo}")
    return ok


def main() -> int:
    chave = os.environ.get("SCRAPFLY_KEY", "").strip()
    if not chave:
        raise SystemExit("Falta SCRAPFLY_KEY no .env (formato scp-live-...).")

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=ALVO_PADRAO)
    args = p.parse_args()

    print(f"alvo: {args.url}")
    for rotulo, extra, estimado in ESCADA:
        if tentar(chave, args.url, rotulo, extra, estimado):
            print(f"\n{'=' * 62}")
            print(f"FUNCIONA com: {rotulo}")
            print("Próximo: medir a taxa de sucesso em várias páginas antes")
            print("de reescrever o conector - uma passada não é uma coleta.")
            print("=" * 62)
            return 0
        time.sleep(3)

    print(f"\n{'=' * 62}")
    print("Nenhuma configuração passou. Antes de desistir, vale abrir um")
    print("ticket com eles: unlocker é o produto, e o ML é alvo conhecido.")
    print("=" * 62)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
