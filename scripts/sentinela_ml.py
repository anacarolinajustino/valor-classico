"""
Uma requisição por semana pra saber se o muro do Mercado Livre caiu.

O ML passou a redirecionar toda listagem pra /gz/account-verification entre
14/07 e 17/08 de 2026. Pode ser definitivo, pode ser rollout - e a diferença
vale 5.345 anúncios por mês. Em vez de lembrar de conferir, esta sentinela
confere sozinha e só fala quando muda.

Deliberadamente MÍNIMA: uma requisição, sem browser, sem proxy. Foi excesso
de requisição que derrubou as páginas de anúncio em 403 por três horas em
18/08. Uma por semana não incomoda ninguém.

Uso:
    python scripts/sentinela_ml.py            # confere e registra
    python scripts/sentinela_ml.py --historico

Pra rodar sozinha no Windows (semanal, segunda 9h), numa linha só:
    schtasks /create /tn "sentinela-ml" /sc weekly /d MON /st 09:00
      /tr "python \"C:\\...\\valor-classico\\scripts\\sentinela_ml.py\""
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ))

import requests

HISTORICO = RAIZ / "data" / "sentinela_ml.jsonl"
ALVO = "https://lista.mercadolivre.com.br/veiculos/carros-antigos/"
CABECALHO = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def sondar() -> dict:
    agora = datetime.now().isoformat(timespec="seconds")
    try:
        r = requests.get(ALVO, headers=CABECALHO, timeout=30, allow_redirects=True)
        return {
            "quando": agora,
            "http": r.status_code,
            "muro": "account-verification" in r.url,
            "bytes": len(r.text),
            "url_final": r.url[:120],
        }
    except Exception as exc:
        return {
            "quando": agora,
            "http": None,
            "muro": None,
            "erro": f"{type(exc).__name__}: {exc}"[:200],
        }


def _linhas() -> list[dict]:
    if not HISTORICO.exists():
        return []
    return [
        json.loads(l)
        for l in HISTORICO.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]


def _estado(d: dict) -> str:
    if d.get("erro"):
        return "erro"
    return "MURO" if d.get("muro") else "ABERTO"


def main() -> int:
    if "--historico" in sys.argv:
        linhas = _linhas()
        if not linhas:
            print("Sem histórico ainda.")
            return 0
        for d in linhas:
            print(f"  {d['quando']}  {_estado(d):7} http={d.get('http')}")
        return 0

    anteriores = _linhas()
    anterior = anteriores[-1] if anteriores else None

    agora = sondar()
    HISTORICO.parent.mkdir(parents=True, exist_ok=True)
    with HISTORICO.open("a", encoding="utf-8") as f:
        f.write(json.dumps(agora, ensure_ascii=False) + "\n")

    if agora.get("erro"):
        print(f"Sonda falhou: {agora['erro']}")
        return 1

    print(f"{agora['quando']}  {_estado(agora)}  http={agora['http']}")

    # O ponto da sentinela: só gritar quando o estado VIRA. Repetir "segue
    # barrado" toda semana é o que faz alarme virar ruído que se ignora.
    if anterior and anterior.get("muro") is True and agora["muro"] is False:
        print("\n" + "=" * 62)
        print("O MURO CAIU. A listagem do ML respondeu sem verificação.")
        print("Confirme com uma coleta de teste antes de contar com isso:")
        print("    python scripts/coletar_todas.py --so mercadolivre")
        print("=" * 62)
    elif anterior and anterior.get("muro") is False and agora["muro"] is True:
        print("\nO muro voltou a subir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
