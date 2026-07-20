"""
Conector Pastore CC.
Site: https://pastorecc.com.br
Motor: WordPress custom (tema redesenhado em 2026)
Estratégia: requests + BeautifulSoup
Listagem: div.vehicle-card (sem preço) → fetch da página de detalhe para preço.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.pipeline.normalizer import inferir_marca_modelo_versao_obs_ano, normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "pastorecc"
BASE_URL = "https://pastorecc.com.br"
LISTING_URL = "https://pastorecc.com.br/veiculos/?condicoes[]=antigos-e-colecao&segmento[]=carros"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
MAX_RETRIES = 2
BACKOFF = 2.0
RATE_LIMIT = 1.5
DETAIL_RATE_LIMIT = 0.8


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    for pg in range(1, paginas + 1):
        url = LISTING_URL if pg == 1 else f"{BASE_URL}/veiculos/page/{pg}/?condicoes[]=antigos-e-colecao&segmento[]=carros"
        html = _requisitar(sessao, url)
        if html is None:
            break

        for card_url, card_title, card_ano in _extrair_cards(html):
            titulo_norm = normalizar_texto(card_title)
            if modelo_norm and modelo_norm not in titulo_norm:
                continue
            if marca_norm and marca_norm not in titulo_norm:
                continue
            if card_url in seen:
                continue
            seen.add(card_url)

            a = _buscar_detalhe(sessao, card_url, card_title, data_coleta, ano_card=card_ano)
            if a:
                anuncios.append(a)
            time.sleep(DETAIL_RATE_LIMIT)

        if not _tem_proxima(html):
            break
        time.sleep(RATE_LIMIT)

    logger.info("[pastorecc] busca: %d anúncio(s)", len(anuncios))
    return anuncios


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    inicio = time.monotonic()
    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    erros = 0
    paginas_ok = 0

    for pg in range(1, max_paginas + 1):
        url = LISTING_URL if pg == 1 else f"{BASE_URL}/veiculos/page/{pg}/?condicoes[]=antigos-e-colecao&segmento[]=carros"
        html = _requisitar(sessao, url)
        if html is None:
            erros += 1
            break

        cards = _extrair_cards(html)
        if not cards:
            break

        paginas_ok += 1
        for card_url, card_title, card_ano in cards:
            if card_url in seen:
                continue
            seen.add(card_url)
            a = _buscar_detalhe(sessao, card_url, card_title, data_coleta, ano_card=card_ano)
            if a:
                anuncios.append(a)
            time.sleep(DETAIL_RATE_LIMIT)

        if not _tem_proxima(html):
            break
        time.sleep(RATE_LIMIT)

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_ok,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[pastorecc] coleta completa: %s", metricas)
    return anuncios, metricas


def _extrair_cards(html: str) -> list[tuple[str, str, Optional[int]]]:
    """
    Retorna lista de (url_detalhe, titulo, ano) a partir da página de listagem.

    O ano vem do badge do card ("GM 1969", div com classe uppercase) ou, na
    falta dele, do primeiro ano de 4 dígitos no texto do card. É o único
    lugar confiável: o h1 da página de detalhe e o alt da imagem muitas
    vezes não trazem o ano (auditoria 2026-07-14: 760/777 anúncios da fonte
    estavam sem ano no banco).
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[tuple[str, str, Optional[int]]] = []

    for card in soup.select("div.vehicle-card"):
        link = card.select_one("a[href]")
        if not link:
            continue
        url = link["href"]
        if not url.startswith("http"):
            url = BASE_URL + url

        img = card.select_one("img[alt]")
        titulo = img["alt"].strip() if img and img.get("alt") else (
            url.rstrip("/").split("/")[-1].replace("-", " ").title()
        )

        ano: Optional[int] = None
        badge = card.select_one("div[class*=uppercase]")
        alvo = badge.get_text(" ", strip=True) if badge else card.get_text(" ", strip=True)
        m = re.search(r"\b(19\d{2}|20\d{2})\b", alvo)
        if not m and badge is not None:
            m = re.search(r"\b(19\d{2}|20\d{2})\b", card.get_text(" ", strip=True))
        if m:
            ano = int(m.group(0))

        if titulo:
            results.append((url, titulo, ano))
    return results


def _buscar_detalhe(
    sessao: requests.Session,
    url: str,
    titulo_fallback: str,
    data_coleta: str,
    ano_card: Optional[int] = None,
) -> Optional[Anuncio]:
    html = _requisitar(sessao, url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    titulo = h1.get_text(strip=True) if h1 else titulo_fallback

    preco_tag = (
        soup.select_one(".cgc-card-price")
        or soup.select_one(".cgc-offer__price")
        or soup.select_one("[class*=price]")
    )
    preco = normalizar_preco(preco_tag.get_text(strip=True)) if preco_tag else None
    if not preco or preco <= 0:
        return None

    marca, modelo, versao, obs, ano = inferir_marca_modelo_versao_obs_ano(titulo)
    if not modelo:
        return None
    if ano is None:
        ano = ano_card

    return Anuncio(
        titulo=titulo, preco=preco, marca=marca, modelo=modelo,
        ano=ano, versao=versao, obs=obs, url=url, fonte=FONTE,
        data_coleta=data_coleta,
    )


def _tem_proxima(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    return bool(soup.find("a", class_="next") or soup.find("a", rel="next"))


def _criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    return s


def _requisitar(sessao: requests.Session, url: str) -> Optional[str]:
    for i in range(1, MAX_RETRIES + 1):
        try:
            r = sessao.get(url, timeout=TIMEOUT, verify=False, allow_redirects=True)
            r.raise_for_status()
            return r.text
        except requests.RequestException as exc:
            logger.warning("[pastorecc] tentativa %d/%d %s: %s", i, MAX_RETRIES, url, exc)
            if i < MAX_RETRIES:
                time.sleep(BACKOFF)
    return None
