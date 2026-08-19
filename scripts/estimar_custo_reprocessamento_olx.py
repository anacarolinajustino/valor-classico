"""
Estimativa de custo (proxy DataImpulse, $1/GB) de um eventual reprocessamento
retroativo da OLX por página de detalhe (2026-07-16).

A página de detalhe da OLX bloqueia `requests` puro (confirmado ao vivo em
2026-07-16) — diferente do enriquecimento por ficha técnica do Mercado Livre
(`scripts/reprocessar_ml_ficha_tecnica.py`), que usa `requests` sem proxy e
portanto não gera custo. Um reprocessamento da OLX exigiria Playwright +
proxy residencial (`src/connectors/_browser.criar_contexto()`), o que GERA
tráfego cobrado. Antes de comprometer a rodada completa, este script mede o
consumo de banda REAL (bytes de rede de cada resposta, não só o tamanho do
HTML — imagens, trackers etc. também contam) numa amostra de anúncios e
extrapola para o total de anúncios OLX salvos no banco.

Uso:
    python scripts/estimar_custo_reprocessamento_olx.py                # reusa amostra salva (scratch_olx_urls.txt)
    python scripts/estimar_custo_reprocessamento_olx.py --amostra=20   # sorteia nova amostra de N urls do banco
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.connectors._browser import criar_contexto
from src.pipeline.persistence import _connect

_PRECO_USD_POR_GB = 1.0  # DataImpulse, confirmado pelo usuário em 2026-07-16
_ARQUIVO_AMOSTRA = Path(__file__).parent.parent / "scratch_olx_urls.txt"
_RATE_LIMIT_SEGUNDOS = 2.0
_TIMEOUT_PAGINA_MS = 30_000


def _carregar_amostra(n: int | None) -> list[str]:
    if n is None and _ARQUIVO_AMOSTRA.exists():
        urls = [l.strip() for l in _ARQUIVO_AMOSTRA.read_text(encoding="utf-8").splitlines() if l.strip()]
        if urls:
            print(f"Usando amostra existente: {_ARQUIVO_AMOSTRA.name} ({len(urls)} urls)")
            return urls

    n = n or 8
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT url FROM anuncios WHERE fonte = 'olx' ORDER BY RANDOM() LIMIT %s", (n,))
            urls = [r["url"] for r in cur.fetchall()]
    _ARQUIVO_AMOSTRA.write_text("\n".join(urls) + "\n", encoding="utf-8")
    print(f"Nova amostra aleatória salva em {_ARQUIVO_AMOSTRA.name} ({len(urls)} urls)")
    return urls


def _total_anuncios_olx() -> int:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM anuncios WHERE fonte = 'olx'")
            return cur.fetchone()["n"]


def _medir_bytes_pagina(page: object, url: str) -> int | None:
    total = 0

    def _on_response(response: object) -> None:
        nonlocal total
        try:
            total += len(response.body())
        except Exception:
            pass  # respostas sem corpo (redirects, 304 etc.) — ignora

    page.on("response", _on_response)
    try:
        page.goto(url, timeout=_TIMEOUT_PAGINA_MS, wait_until="networkidle")
    except Exception as exc:
        print(f"  erro em {url}: {exc}")
        return None
    finally:
        page.remove_listener("response", _on_response)

    return total


def main() -> None:
    n_amostra = None
    for arg in sys.argv:
        if arg.startswith("--amostra="):
            n_amostra = int(arg.split("=", 1)[1])

    urls = _carregar_amostra(n_amostra)
    if not urls:
        print("Nenhuma URL de amostra disponível (banco sem anúncios OLX?).")
        return

    print(f"\nMedindo bytes de rede reais em {len(urls)} página(s) de detalhe da OLX (via proxy)...")
    bytes_por_pagina: list[int] = []

    with criar_contexto() as ctx:
        page = ctx.new_page()
        for i, url in enumerate(urls, 1):
            total = _medir_bytes_pagina(page, url)
            if total is not None:
                bytes_por_pagina.append(total)
                print(f"  #{i} {total / 1024:.0f} KB — {url}")
            if i < len(urls):
                time.sleep(_RATE_LIMIT_SEGUNDOS)

    if not bytes_por_pagina:
        print("\nNenhuma página medida com sucesso — não dá pra estimar custo.")
        return

    media_bytes = sum(bytes_por_pagina) / len(bytes_por_pagina)
    total_olx = _total_anuncios_olx()
    total_gb = (media_bytes * total_olx) / 1e9
    custo_usd = total_gb * _PRECO_USD_POR_GB

    print(f"\nMedidas com sucesso: {len(bytes_por_pagina)}/{len(urls)}")
    print(f"Média por página: {media_bytes / 1024:.0f} KB")
    print(f"Total de anúncios OLX no banco: {total_olx}")
    print(f"Estimativa de tráfego total do reprocessamento: {total_gb:.2f} GB")
    print(f"Custo estimado (DataImpulse, ${_PRECO_USD_POR_GB:.2f}/GB): ${custo_usd:.2f}")


if __name__ == "__main__":
    main()
