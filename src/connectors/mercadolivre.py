"""
Conector Mercado Livre — coleta anúncios de carros clássicos via páginas
renderizadas (Playwright), não mais via API oficial.

Site: https://www.mercadolivre.com.br
Motor: Playwright + proxy residencial (DataImpulse) + stealth.

Histórico: a API pública (api.mercadolibre.com) passou a bloquear até
endpoints triviais com 403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES (ver
investigação de 2026-07-08). Testado ao vivo:
- IP de datacenter: bloqueado sempre (interstitial /gz/account-verification
  ou /captcha/wall), mesmo via Playwright real.
- IP residencial (DataImpulse) sem stealth: ainda bloqueado ~92% das vezes —
  não é reputação de IP, é detecção de fingerprint de automação via CDP.
- IP residencial + stealth (playwright-stealth): 0 bloqueios em 12 tentativas.

Uso de stealth para coleta de dados públicos (preço/título/ano de anúncios)
foi autorizado explicitamente pelo usuário em 2026-07-08.

Compliance: apenas dados públicos de anúncios (sem login, sem dados pessoais).
Rate limit: ~2s entre navegações para não se comportar como scraper agressivo.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from src.catalog.loader import carregar_catalogo
from src.connectors._browser import criar_contexto_aquecido
from src.pipeline.normalizer import inferir_marca_modelo_ano, normalizar_texto, remover_acentos
from src.pipeline.persistence import ANO_CORTE_CLASSICO
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

FONTE = "mercadolivre"
_HOME_URL = "https://www.mercadolivre.com.br/"
_CATEGORIA_SLUG = "carros-vans-utilitarios"
_ITENS_POR_PAGINA = 48

_ESPERA_NAV_MS = 4000
_RATE_LIMIT = 2.0

# A busca por slug do ML cai num fallback de marketplace geral quando o par
# marca+modelo tem poucos carros reais — devolvendo miniaturas, kits e peças
# cujo título cita o modelo e um ano (descoberto 2026-07-14: 84% dos 4.440
# anúncios da coleta de 07-10 eram isso). Títulos com esses termos nunca são
# veículo à venda.
_TERMOS_NAO_VEICULO = (
    "miniatura", "hot wheels", "matchbox", "escala 1", "1/64", "1/43",
    "1/24", "1/18", "1:64", "1:43", "1:24", "1:18", "chaveiro", "adesivo",
    "camiseta", "quadro decorativo", "placa decorativa",
)


def _bloqueado(page) -> bool:
    """True se a página caiu num interstitial anti-bot do ML (captcha ou verificação)."""
    return "/gz/" in page.url or "/captcha/" in page.url


def _bloquear_midia(page) -> None:
    """Aborta requisições de imagem/fonte/mídia — só precisamos do HTML/dados, economiza banda de proxy."""
    page.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in ("image", "font", "media")
        else route.continue_(),
    )


def _slug(texto: str) -> str:
    """Converte texto em slug de URL (minúsculo, sem acento, hífens no lugar de espaços)."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    minusculo = sem_acento.lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", minusculo).strip("-")


def _url_busca(marca: str, modelo: str, pagina: int = 1) -> str:
    slug = f"{_CATEGORIA_SLUG}-{_slug(marca)}-{_slug(modelo)}"
    if pagina <= 1:
        return f"https://lista.mercadolivre.com.br/{slug}"
    offset = _ITENS_POR_PAGINA * (pagina - 1) + 1
    return f"https://lista.mercadolivre.com.br/{slug}_Desde_{offset}_NoIndex_True"


def coletar_completo() -> tuple[list[Anuncio], dict]:
    """
    Coleta anúncios buscando cada par (marca, modelo) do catálogo canônico
    (data/base_marcamodelo.csv) numa sessão de browser contínua — reaproveita
    a mesma sessão aquecida (mesmo IP residencial) para todas as buscas,
    abrindo uma nova só quando a sessão atual for bloqueada.
    """
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()
    pares = sorted(carregar_catalogo().keys())

    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    total_req = 0
    erros = 0
    idx = 0

    logger.info("[mercadolivre] coleta completa: %d pares marca+modelo no catálogo", len(pares))

    while idx < len(pares):
        try:
            with criar_contexto_aquecido(_HOME_URL, bloqueado=_bloqueado, max_tentativas=3) as (ctx, page):
                _bloquear_midia(page)
                while idx < len(pares):
                    marca, modelo = pares[idx]
                    novos, req, bloqueou = _buscar_pagina(page, marca, modelo, pagina=1, data_coleta=data_coleta)
                    total_req += req

                    if bloqueou:
                        logger.warning(
                            "[mercadolivre] sessão bloqueada em '%s %s' (par %d/%d) — trocando de sessão",
                            marca, modelo, idx + 1, len(pares),
                        )
                        break

                    # Pós-filtro obrigatório: a busca por slug do ML cai num
                    # fallback de marketplace geral (peças, kits, miniaturas)
                    # quando o par tem poucos carros reais — sem isso, 84% da
                    # coleta de 2026-07-10 veio lixo. Além do filtro padrão de
                    # buscar(), exige marca inferida == marca buscada: título
                    # de peça começa com o nome da peça ("Kit...", "Bomba..."),
                    # não com a marca do carro.
                    marca_norm = normalizar_texto(marca)
                    novos = [
                        a for a in _filtrar_marca_modelo(novos, marca_norm, normalizar_texto(modelo))
                        if a.marca and normalizar_texto(a.marca) == marca_norm
                    ]

                    for a in novos:
                        if a.url not in seen:
                            seen.add(a.url)
                            anuncios.append(a)

                    idx += 1
                    if idx % 50 == 0:
                        logger.info(
                            "[mercadolivre] progresso: %d/%d pares, %d anúncio(s) até agora",
                            idx, len(pares), len(anuncios),
                        )
                    time.sleep(_RATE_LIMIT)
        except RuntimeError as exc:
            logger.error("[mercadolivre] não foi possível abrir sessão aquecida: %s", exc)
            erros += 1
            break

    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "erros_detalhe": 0,
        "requisicoes": total_req,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[mercadolivre] coleta completa: %s", metricas)
    return anuncios, metricas


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """
    Busca anúncios no Mercado Livre por marca e modelo via páginas renderizadas.

    Args:
        marca:   Nome da marca (ex.: "VOLKSWAGEN"). Usado para pós-filtragem.
        modelo:  Nome do modelo (ex.: "FUSCA"). Usado como termo de busca.
        paginas: Número máximo de páginas (48 itens cada) a buscar.

    Returns:
        Lista de Anuncio normalizados com ano <= ANO_CORTE_CLASSICO.
    """
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anuncios: list[Anuncio] = []
    seen: set[str] = set()

    try:
        with criar_contexto_aquecido(_HOME_URL, bloqueado=_bloqueado) as (ctx, page):
            _bloquear_midia(page)
            for pagina in range(1, paginas + 1):
                novos, _req, bloqueou = _buscar_pagina(page, marca, modelo, pagina, data_coleta)
                if bloqueou:
                    logger.warning("[mercadolivre] sessão bloqueada na página %d", pagina)
                    break

                itens = _filtrar_marca_modelo(novos, marca_norm, modelo_norm)
                for a in itens:
                    if a.url not in seen:
                        seen.add(a.url)
                        anuncios.append(a)

                if len(novos) < _ITENS_POR_PAGINA:
                    break
                if pagina < paginas:
                    time.sleep(_RATE_LIMIT)
    except RuntimeError as exc:
        logger.error("[mercadolivre] não foi possível abrir sessão aquecida: %s", exc)

    logger.info(
        "[mercadolivre] busca '%s %s': %d anúncio(s) em %.1fs",
        marca, modelo, len(anuncios), time.monotonic() - inicio,
    )
    return anuncios


# ── Helpers internos ──────────────────────────────────────────────────────────

def _buscar_pagina(
    page, marca: str, modelo: str, pagina: int, data_coleta: str,
) -> tuple[list[Anuncio], int, bool]:
    """Navega para uma página de busca e devolve (anuncios, requisicoes, bloqueado)."""
    url = _url_busca(marca, modelo, pagina)
    try:
        page.goto(url, timeout=45000, wait_until="networkidle", referer=page.url)
        page.wait_for_timeout(_ESPERA_NAV_MS)
    except Exception as exc:
        logger.warning("[mercadolivre] erro navegando para %s: %s", url, exc)
        return [], 1, False

    if _bloqueado(page):
        return [], 1, True

    html = _conteudo_com_retry(page)
    return _parsear_listagem(html, data_coleta), 1, False


def _conteudo_com_retry(page, tentativas: int = 3) -> str:
    """page.content() pode falhar se a página ainda estiver navegando (SPA client-side redirect)."""
    for i in range(tentativas):
        try:
            return page.content()
        except Exception:
            if i == tentativas - 1:
                raise
            page.wait_for_timeout(2000)
    return ""


def _filtrar_marca_modelo(itens: list[Anuncio], marca_norm: str, modelo_norm: str) -> list[Anuncio]:
    if marca_norm:
        itens = [
            a for a in itens
            if not a.marca
            or normalizar_texto(a.marca) == marca_norm
            or marca_norm in normalizar_texto(a.titulo)
        ]
    if modelo_norm:
        itens = [
            a for a in itens
            if not a.modelo
            or modelo_norm in normalizar_texto(a.modelo)
            or normalizar_texto(a.modelo) in modelo_norm
            or modelo_norm in normalizar_texto(a.titulo)
        ]
    return itens


def _parsear_listagem(html: str, data_coleta: str) -> list[Anuncio]:
    """Extrai anúncios de uma página de listagem/busca do Mercado Livre."""
    soup = BeautifulSoup(html, "lxml")
    anuncios: list[Anuncio] = []

    for card in soup.find_all("li", class_="ui-search-layout__item"):
        a = _parsear_card(card, data_coleta)
        if a is not None:
            anuncios.append(a)
    return anuncios


def _parsear_card(card, data_coleta: str) -> Optional[Anuncio]:
    link = card.find("a", class_=re.compile(r"poly-component__title"))
    if not link or not link.get("href"):
        return None
    titulo = link.get_text(strip=True)
    if not titulo:
        return None
    url = link["href"].split("#")[0]

    preco_el = card.find("span", class_=re.compile(r"\bandes-money-amount\b"))
    preco = _extrair_preco(preco_el)
    if not preco or preco <= 0:
        return None

    # remover_acentos + lower (e não normalizar_texto) porque a pontuação
    # importa aqui: "1/64" normalizado viraria "164" e casaria com o Alfa
    # Romeo 164, um clássico real.
    titulo_lower = remover_acentos(titulo).lower()
    if any(t in titulo_lower for t in _TERMOS_NAO_VEICULO):
        return None

    ano_cartao = _extrair_ano_cartao(card)
    marca, modelo, ano_inferido = inferir_marca_modelo_ano(titulo)
    ano = ano_cartao or ano_inferido
    if ano is None or not (1900 <= ano <= ANO_CORTE_CLASSICO):
        return None
    if not modelo:
        return None

    return Anuncio(
        titulo=titulo,
        preco=preco,
        marca=marca,
        modelo=modelo,
        ano=ano,
        versao=None,
        url=url,
        fonte=FONTE,
        data_coleta=data_coleta,
    )


def _extrair_preco(preco_el) -> Optional[float]:
    """Extrai o preço a partir do aria-label (ex.: '63890 reais') — evita ambiguidade do separador de milhar."""
    if preco_el is None:
        return None
    aria = preco_el.get("aria-label", "")
    m = re.search(r"(\d+)", aria)
    if m:
        return float(m.group(1))
    # fallback: texto visível "63.890" (ponto = separador de milhar)
    fracao = preco_el.find("span", class_="andes-money-amount__fraction")
    if fracao:
        digitos = re.sub(r"\D", "", fracao.get_text())
        if digitos:
            return float(digitos)
    return None


def _extrair_ano_cartao(card) -> Optional[int]:
    """O primeiro item de poly-attributes_list costuma ser o ano do veículo."""
    lista_attrs = card.find("ul", class_="poly-attributes_list")
    if not lista_attrs:
        return None
    primeiro_item = lista_attrs.find("li")
    if not primeiro_item:
        return None
    texto = primeiro_item.get_text(strip=True)
    if texto.isdigit() and len(texto) == 4:
        ano = int(texto)
        if 1900 <= ano <= date.today().year + 1:
            return ano
    return None
