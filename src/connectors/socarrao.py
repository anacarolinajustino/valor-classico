"""
Conector SoCarrão.
Site: https://www.socarrao.com.br
Motor: Nuxt SSR + API própria (sc-api-prod.socarrao.com.br). Marketplace
generalista de veículos usados (não focado em clássicos — buscas populares
são Onix, Civic, Renegade), mas tem estoque real de clássicos sob demanda.

Por que Playwright e não requests: a API exige um header assinado no
cliente (`x-sc-key`, HMAC calculado por uma função `Ky()` dentro do bundle
JS minificado, junto com `x-sc-origin: sc-site`) em toda requisição — não é
bloqueio de IP/Cloudflare, é assinatura anti-bot por request. Reimplementar
essa assinatura em Python seria frágil (quebra a cada redeploy do bundle,
hash do arquivo muda). Em vez disso, dirigimos o fluxo de busca real via
Playwright — o navegador calcula o header sozinho, é JS de verdade — e
escutamos as respostas JSON de `search/closed` via `page.on("response")`.

Fluxo de busca (testado ao vivo em 2026-07-09):
1. Home, digita o termo no campo "Digite aqui marca ou modelo".
2. Aparece um dropdown de autocomplete (`div.lz-select-list__item`) com
   sugestões "Marca Modelo" já filtradas pelo estoque atual — se o termo
   não tiver nenhum veículo à venda agora, não aparece nenhuma opção.
3. Clica na opção que bate com o termo buscado, depois em "VER RESULTADOS".
4. Se aparecer o modal "Trocar Localização", clica em "Manter localização"
   (mantém a busca nacional, sem restringir por cidade — importante, pois
   sem isso o resultado fica vazio até confirmar).
5. A listagem carrega via scroll infinito: cada scroll dispara mais uma
   página de `search/closed?page=N&limit=6&...`. Escutamos via listener de
   rede em vez de reconstruir a URL/paginação manualmente (o parâmetro
   `brandModelVersions` é um ID interno que só a busca guiada resolve).

Não existe endpoint de "listar tudo" (é marketplace geral, sem categoria
fixa de clássicos). `coletar_completo()` varre uma lista curada de termos
clássicos comuns no mercado nacional (mesmo padrão do TERMOS_SWEEP da OLX) —
varrer os 1128 pares marca+modelo do catálogo via UI seria caro demais
(cada termo leva alguns segundos de navegação real).
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Optional

from src.connectors._browser import criar_contexto
from src.pipeline.normalizer import normalizar_texto, separar_marca_modelo_versao_obs
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "socarrao"
SITE_BASE = "https://www.socarrao.com.br"
SEARCH_INPUT_SELECTOR = "input[placeholder='Digite aqui marca ou modelo']"
RATE_LIMIT = 1.5
# Marketplace generalista: nomes de modelo clássicos às vezes são reaproveitados
# em carros novos (ex.: "Maverick" hoje é uma picape Ford 2022+, não o cupê de
# 1970). Sem esse corte, a busca por esses termos traz o carro moderno.
ANO_MAXIMO_CLASSICO = 2000

# Termos de busca cobrindo marcas/modelos clássicos comuns no mercado
# nacional — não há endpoint de "listar tudo" nesse marketplace generalista.
# Lista deliberadamente curta (2026-07-09): cada termo reaproveita a mesma
# aba do navegador, mas navega o site inteiro de novo (Nuxt, bundle grande) —
# uma lista de ~20 termos chegou a esgotar a memória do plano free do Render
# no meio da varredura (derrubou o serviço). Se precisar de mais cobertura,
# prefira chamar buscar(marca, modelo) pontualmente por termo específico.
TERMOS_CLASSICOS: list[str] = [
    "fusca", "opala", "kombi", "karmann ghia", "puma", "chevette", "c10", "belina",
]


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """Busca anúncios no SoCarrão por marca e modelo, dirigindo a UI real."""
    data_coleta = date.today().isoformat()

    with criar_contexto() as ctx:
        page = ctx.new_page()
        itens_brutos = _buscar_termo(page, modelo, marca, paginas)

    anuncios = [a for item in itens_brutos if (a := _parsear_item(item, data_coleta))]
    logger.info("[socarrao] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def coletar_completo(max_paginas: int = 2) -> tuple[list[Anuncio], dict]:
    """Varre TERMOS_CLASSICOS numa única sessão de browser."""
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()
    anuncios: list[Anuncio] = []
    seen_ids: set[int] = set()
    termos_com_resultado = 0
    termos_sem_resultado = 0
    erros = 0

    with criar_contexto() as ctx:
        page = ctx.new_page()
        for i, termo in enumerate(TERMOS_CLASSICOS, 1):
            logger.info("[socarrao] termo %d/%d — '%s'", i, len(TERMOS_CLASSICOS), termo)
            try:
                itens_brutos = _buscar_termo(page, termo, "", max_paginas)
            except Exception as exc:
                logger.warning("[socarrao] erro buscando '%s': %s", termo, exc)
                erros += 1
                continue

            if not itens_brutos:
                termos_sem_resultado += 1
                continue
            termos_com_resultado += 1

            novos = 0
            for item in itens_brutos:
                vid = item.get("id")
                if vid is None or vid in seen_ids:
                    continue
                seen_ids.add(vid)
                a = _parsear_item(item, data_coleta)
                if a:
                    anuncios.append(a)
                    novos += 1

            logger.info(
                "[socarrao] '%s': +%d anúncio(s) (acumulado: %d)",
                termo, novos, len(anuncios),
            )
            time.sleep(RATE_LIMIT)

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "termos_com_resultado": termos_com_resultado,
        "termos_sem_resultado": termos_sem_resultado,
        "anuncios_validos": len(anuncios),
        "erros": erros,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[socarrao] coleta completa: %s", metricas)
    return anuncios, metricas


# ── Helpers internos ────────────────────────────────────────────────────────

def _buscar_termo(page: Any, termo_busca: str, marca_filtro: str, max_paginas: int) -> list[dict]:
    """
    Dirige o fluxo de busca real (ver docstring do módulo) e devolve os
    itens brutos de `results` capturados de `search/closed`.
    """
    capturados: list[dict] = []

    def _on_response(resp):
        if "search/closed" in resp.url and resp.status == 200:
            try:
                capturados.append(resp.json())
            except Exception:
                pass

    page.on("response", _on_response)
    try:
        page.goto(SITE_BASE, wait_until="load", timeout=45000)
        page.wait_for_timeout(1500)

        campo = page.locator(SEARCH_INPUT_SELECTOR)
        campo.click(timeout=10000)
        campo.fill(termo_busca)
        page.wait_for_timeout(1500)

        opcoes = page.locator("div.lz-select-list__item")
        termo_norm = normalizar_texto(termo_busca)
        marca_norm = normalizar_texto(marca_filtro) if marca_filtro else ""
        alvo = None
        for i in range(opcoes.count()):
            texto = normalizar_texto(opcoes.nth(i).inner_text())
            if termo_norm in texto and (not marca_norm or marca_norm in texto):
                alvo = opcoes.nth(i)
                break

        if alvo is None:
            logger.info("[socarrao] '%s': sem sugestão no autocomplete (sem estoque atual).", termo_busca)
            return []

        alvo.click(timeout=5000)
        page.wait_for_timeout(500)
        page.get_by_text("VER RESULTADOS", exact=True).click(timeout=5000)
        page.wait_for_timeout(2000)

        try:
            page.get_by_text("Manter localiza", exact=False).click(timeout=4000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        tentativas_sem_novo = 0
        while len(capturados) < max_paginas and tentativas_sem_novo < 3:
            antes = len(capturados)
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1500)
            tentativas_sem_novo = 0 if len(capturados) > antes else tentativas_sem_novo + 1
    finally:
        page.remove_listener("response", _on_response)

    resultados: list[dict] = []
    for body in capturados:
        resultados.extend(body.get("results", []))
    return resultados


def _parsear_item(item: dict, data_coleta: str) -> Optional[Anuncio]:
    vid = item.get("id")
    marca = ((item.get("brand") or {}).get("name") or "").upper()
    modelo = ((item.get("model") or {}).get("name") or "").upper()
    # Campo estruturado do JSON passa pelo catálogo antes de gravar (ver
    # separar_marca_modelo_versao_obs) — regra geral pra toda fonte de marca/modelo estruturada.
    marca, modelo, versao_modelo, obs = separar_marca_modelo_versao_obs(marca, modelo)
    # Campo "version" próprio da API é mais confiável que o que sobra ao
    # separar o "model" — só cai pro derivado do modelo na ausência.
    versao = (item.get("version") or {}).get("name") or versao_modelo
    preco = (item.get("priceInfo") or {}).get("price")
    ano = item.get("modelYear") or item.get("manufactureYear")

    if not vid or not modelo or not preco or preco <= 0:
        return None
    if ano and ano > ANO_MAXIMO_CLASSICO:
        return None

    titulo = " ".join(p for p in [marca, modelo, versao, str(ano) if ano else ""] if p)

    return Anuncio(
        titulo=titulo,
        preco=float(preco),
        marca=marca,
        modelo=modelo,
        ano=ano,
        versao=versao,
        obs=obs,
        url=f"{SITE_BASE}/veiculos/detalhes/{vid}",
        fonte=FONTE,
        data_coleta=data_coleta,
    )
