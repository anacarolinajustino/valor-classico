"""
Conector Mercado Livre — coleta anúncios de carros clássicos via páginas
renderizadas (Playwright), não mais via API oficial.

Site: https://www.mercadolivre.com.br
Motor: Playwright + proxy residencial (DataImpulse) + stealth.

Estratégia batch (coletar_completo, 2026-07-14): varre as listagens de
categoria de veículos — carros-antigos (dedicada) + carros-caminhonetes
fatiada por _YearRange_ (filtro de ano no servidor). Todo card é um veículo
real. A estratégia anterior (coletar_por_catalogo: busca por slug de cada par
marca+modelo do catálogo) fica pra uso manual — o ML cai num fallback de
marketplace geral quando o par tem poucos carros, o que encheu o banco de
peças/miniaturas na coleta de 2026-07-10 (84% de lixo).

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

Ficha técnica (2026-07-15): a página de LISTAGEM só tem título + preço + o
badge de ano do card — marca/modelo vinham só de adivinhar o título, o que
falha quando o título começa por outra coisa que não a marca (ex.: "AP
2000..." é o código do motor VW, não a marca; a marca real — Ford Versailles
— só aparece na ficha técnica da página do anúncio). Diferente da listagem,
a página de detalhe do anúncio NÃO tem o mesmo bloqueio anti-bot (testado
ao vivo: 200 sem proxy/stealth, ~1s) — por isso o enriquecimento usa
`requests` puro, sem gastar sessão/IP residencial da listagem. Usuária
decidiu (2026-07-15) enriquecer TODO anúncio, aceitando o custo de ~1
requisição extra por anúncio coletado.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import replace
from datetime import date
from typing import Optional

import requests
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

# Enriquecimento via ficha técnica (requests puro — ver docstring do módulo).
_FICHA_TIMEOUT_S = 15
_FICHA_RATE_LIMIT = 1.0
_FICHA_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Categorias de veículos usadas pela coleta batch (descobertas pelo usuário em
# 2026-07-14). São categorias REAIS de veículo — todo card é um carro à venda,
# sem o fallback de marketplace geral das buscas por slug (ver coletar_por_catalogo).
# carros-antigos: categoria dedicada (~2.500 anúncios; sem filtro de ano — o
#   parser corta em ANO_CORTE_CLASSICO, descartando réplicas modernas etc.).
# carros-caminhonetes: categoria geral, com filtro _YearRange_ aplicado no
#   servidor, fatiado porque o offset _Desde_ tem teto (validado até ~2.000).
_FONTES_CATEGORIA: list[tuple[str, Optional[tuple[int, int]]]] = [
    ("carros-antigos", None),
    ("carros-caminhonetes", (1900, 1969)),
    ("carros-caminhonetes", (1970, 1979)),
    ("carros-caminhonetes", (1980, 1989)),
    ("carros-caminhonetes", (1990, 1994)),
    ("carros-caminhonetes", (1995, 1999)),
    ("carros-caminhonetes", (2000, 2000)),
]

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


def _url_categoria(slug: str, pagina: int = 1, fatia: Optional[tuple[int, int]] = None) -> str:
    """
    Monta URL de listagem de categoria de veículos, com filtro opcional de
    faixa de ano (_YearRange_, aplicado no servidor) e paginação (_Desde_).

    O sufixo _NoIndex_True na paginação é OBRIGATÓRIO: sem ele o ML
    redireciona a página 2+ de volta pra página 1 silenciosamente (validado
    ao vivo em 2026-07-14; a página vem com os mesmos 48 cards da primeira).
    """
    partes: list[str] = []
    if pagina > 1:
        offset = _ITENS_POR_PAGINA * (pagina - 1) + 1
        partes.append(f"_Desde_{offset}")
    if fatia is not None:
        partes.append(f"_YearRange_{fatia[0]}-{fatia[1]}")
    if pagina > 1:
        partes.append("_NoIndex_True")
    return f"https://lista.mercadolivre.com.br/veiculos/{slug}/{''.join(partes)}"


def coletar_completo(max_paginas_por_fonte: int = 60) -> tuple[list[Anuncio], dict]:
    """
    Coleta batch do ML — ponto de entrada do painel admin.

    Varre listagens de CATEGORIA de veículos (_FONTES_CATEGORIA): a categoria
    dedicada carros-antigos + a categoria geral carros-caminhonetes fatiada
    por faixa de ano via _YearRange_ (filtro aplicado no servidor). Todo card
    dessas listagens é um veículo real à venda — estratégia adotada em
    2026-07-14 no lugar da varredura por pares do catálogo
    (coletar_por_catalogo), cuja busca por slug caía num fallback de
    marketplace geral e trouxe 84% de peças/miniaturas na coleta de 07-10.

    Sessão de browser contínua (mesmo IP residencial via sticky session);
    reabre sessão nova só quando a atual é bloqueada, retomando da mesma
    página onde parou.

    Args:
        max_paginas_por_fonte: teto de páginas por listagem (default 60 —
            a maior fatia tem ~1.400 resultados ≈ 29 páginas; 60 dá folga).

    Returns:
        (anuncios, metricas)
    """
    inicio = time.monotonic()
    data_coleta = date.today().isoformat()

    anuncios: list[Anuncio] = []
    seen: set[str] = set()
    total_req = 0
    erros = 0
    fichas_ok = 0
    fichas_ausentes = 0
    fonte_idx = 0
    pagina = 1
    # URLs brutas (todos os cards) da listagem atual — detecta teto de
    # paginação (página repetida), mesmo padrão do conector da OLX.
    urls_brutas_fonte: set[str] = set()

    def _proxima_fonte():
        nonlocal fonte_idx, pagina, urls_brutas_fonte
        fonte_idx += 1
        pagina = 1
        urls_brutas_fonte = set()

    logger.info(
        "[mercadolivre] coleta completa: %d listagens de categoria, até %d págs cada",
        len(_FONTES_CATEGORIA), max_paginas_por_fonte,
    )

    while fonte_idx < len(_FONTES_CATEGORIA):
        try:
            with criar_contexto_aquecido(_HOME_URL, bloqueado=_bloqueado, max_tentativas=3) as (ctx, page):
                _bloquear_midia(page)
                while fonte_idx < len(_FONTES_CATEGORIA):
                    slug, fatia = _FONTES_CATEGORIA[fonte_idx]
                    rotulo = slug + (f" {fatia[0]}-{fatia[1]}" if fatia else "")
                    url = _url_categoria(slug, pagina, fatia)

                    try:
                        page.goto(url, timeout=45000, wait_until="networkidle", referer=page.url)
                        page.wait_for_timeout(_ESPERA_NAV_MS)
                    except Exception as exc:
                        logger.warning("[mercadolivre] erro navegando %s pág %d: %s", rotulo, pagina, exc)
                        erros += 1
                        _proxima_fonte()
                        continue
                    total_req += 1

                    if _bloqueado(page):
                        logger.warning(
                            "[mercadolivre] sessão bloqueada em %s pág %d — trocando de sessão",
                            rotulo, pagina,
                        )
                        break  # reabre sessão aquecida; retoma da mesma página

                    html = _conteudo_com_retry(page)
                    urls_pagina = _urls_cards(html)
                    novos = _parsear_listagem(html, data_coleta)

                    if not urls_pagina:
                        logger.info("[mercadolivre] %s pág %d: vazia — fim da listagem.", rotulo, pagina)
                        _proxima_fonte()
                        continue
                    if urls_pagina <= urls_brutas_fonte:
                        logger.info(
                            "[mercadolivre] %s pág %d: repetida (teto de paginação) — fim da listagem.",
                            rotulo, pagina,
                        )
                        _proxima_fonte()
                        continue
                    urls_brutas_fonte |= urls_pagina

                    adicionados = 0
                    for a in novos:
                        if a.url in seen:
                            continue
                        seen.add(a.url)

                        # Ficha técnica da página de detalhe é autoridade
                        # sobre marca/modelo/ano (o título só é usado como
                        # fallback quando ela não está disponível) — ver
                        # docstring do módulo. 1 requisição extra por
                        # anúncio, sem sessão Playwright (não precisa do
                        # stealth/proxy da listagem).
                        a_enriquecido = _enriquecer_com_ficha_tecnica(a)
                        time.sleep(_FICHA_RATE_LIMIT)
                        if a_enriquecido is None:
                            continue  # ficha revelou ano fora do corte de clássico
                        if a_enriquecido is not a:
                            fichas_ok += 1
                        else:
                            fichas_ausentes += 1

                        anuncios.append(a_enriquecido)
                        adicionados += 1

                    logger.info(
                        "[mercadolivre] %s pág %d: %d cards → %d válidos → %d novos (total: %d, fichas ok: %d)",
                        rotulo, pagina, len(urls_pagina), len(novos), adicionados, len(anuncios), fichas_ok,
                    )

                    if len(urls_pagina) < _ITENS_POR_PAGINA or pagina >= max_paginas_por_fonte:
                        _proxima_fonte()
                    else:
                        pagina += 1
                    time.sleep(_RATE_LIMIT)
        except RuntimeError as exc:
            logger.error("[mercadolivre] não foi possível abrir sessão aquecida: %s", exc)
            erros += 1
            break

    metricas = {
        "fonte": FONTE,
        "modo": "categorias",
        "listagens": [s + (f" {f[0]}-{f[1]}" if f else "") for s, f in _FONTES_CATEGORIA],
        "data_coleta": data_coleta,
        "anuncios_validos": len(anuncios),
        "erros_listagem": erros,
        "erros_detalhe": fichas_ausentes,
        "fichas_tecnicas_ok": fichas_ok,
        "requisicoes": total_req,
        "tempo_total_s": round(time.monotonic() - inicio, 1),
    }
    logger.info("[mercadolivre] coleta completa: %s", metricas)
    return anuncios, metricas


def coletar_por_catalogo() -> tuple[list[Anuncio], dict]:
    """
    Estratégia antiga de coleta batch (uso pontual/manual): busca cada par
    (marca, modelo) do catálogo canônico (data/base_marcamodelo.csv) numa
    sessão de browser contínua — reaproveita a mesma sessão aquecida (mesmo
    IP residencial) para todas as buscas, abrindo uma nova só quando a
    sessão atual for bloqueada.

    Não é mais o ponto de entrada do painel (ver coletar_completo): a busca
    por slug cai num fallback de marketplace geral quando o par tem poucos
    carros reais, exigindo os pós-filtros agressivos abaixo — e mesmo assim
    cobre menos que as listagens de categoria.
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
                    if a.url in seen:
                        continue
                    seen.add(a.url)
                    a_enriquecido = _enriquecer_com_ficha_tecnica(a)
                    time.sleep(_FICHA_RATE_LIMIT)
                    if a_enriquecido is not None:
                        anuncios.append(a_enriquecido)

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


def _urls_cards(html: str) -> set[str]:
    """
    URLs de TODOS os cards da página (válidos ou não pro nosso filtro) —
    usado pra detectar página repetida (teto de paginação) e página vazia.
    """
    soup = BeautifulSoup(html, "lxml")
    urls: set[str] = set()
    for card in soup.find_all("li", class_="ui-search-layout__item"):
        link = card.find("a", class_=re.compile(r"poly-component__title"))
        if link and link.get("href"):
            urls.add(link["href"].split("#")[0])
    return urls


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


# ── Ficha técnica (página de detalhe do anúncio) ──────────────────────────────

def _extrair_ficha_tecnica(html: str) -> dict[str, str]:
    """
    Extrai a tabela "Características do veículo" da página do anúncio como
    um dict {rótulo: valor}, com rótulos normalizados (maiúsculo, sem acento)
    pra lookup robusto — ex.: {"MARCA": "Ford", "MODELO": "Versailles",
    "ANO": "1996", "VERSAO": "GL 2.0i"}. Dict vazio se a tabela não existir
    (anúncio sem ficha preenchida) ou a página não for a esperada.
    """
    soup = BeautifulSoup(html, "lxml")
    tabela = soup.find("div", class_="ui-pdp-specs__table")
    if not tabela:
        return {}

    ficha: dict[str, str] = {}
    for linha in tabela.find_all("tr"):
        rotulo_el = linha.find("th")
        valor_el = linha.find("td")
        if not rotulo_el or not valor_el:
            continue
        rotulo = normalizar_texto(rotulo_el.get_text(strip=True))
        valor = valor_el.get_text(strip=True)
        if rotulo and valor:
            ficha[rotulo] = valor
    return ficha


def _buscar_ficha_tecnica(url: str) -> Optional[dict[str, str]]:
    """
    Busca a página do anúncio e extrai a ficha técnica via `requests` puro —
    a página de detalhe não tem o mesmo bloqueio anti-bot da listagem (ver
    docstring do módulo), então não precisa da sessão Playwright com stealth
    e proxy residencial. None se a requisição falhar (timeout, bloqueio,
    HTTP != 200) — o chamador deve degradar pro anúncio original (do título).
    """
    try:
        resp = requests.get(
            url, headers={"User-Agent": _FICHA_USER_AGENT}, timeout=_FICHA_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.warning("[mercadolivre] erro buscando ficha técnica de %s: %s", url, exc)
        return None
    if resp.status_code != 200 or "/gz/" in resp.url or "/captcha/" in resp.url:
        logger.warning(
            "[mercadolivre] ficha técnica indisponível (status=%d) em %s",
            resp.status_code, url,
        )
        return None
    return _extrair_ficha_tecnica(resp.text)


def _enriquecer_com_ficha_tecnica(anuncio: Anuncio) -> Optional[Anuncio]:
    """
    Sobrescreve marca/modelo/versão (e ano, se presente) do anúncio com os
    valores estruturados da ficha técnica, quando disponível. Sem isso,
    marca/modelo vêm só de adivinhar o título — que erra quando o título
    começa por outra coisa que não a marca (ex.: "AP 2000..." é o código
    do motor, não a marca; a marca real só está na ficha técnica).

    Retorna o anúncio original (do título) se a ficha técnica não estiver
    disponível ou não tiver marca/modelo. Retorna None (descarta o anúncio)
    se a ficha técnica revelar um ano fora do corte de clássico — mesma
    regra central de upsert_anuncios, aplicada aqui também porque o ano da
    ficha pode divergir do ano inferido do título/card.
    """
    ficha = _buscar_ficha_tecnica(anuncio.url)
    if not ficha or "MARCA" not in ficha or "MODELO" not in ficha:
        return anuncio

    ano_novo = anuncio.ano
    ano_raw = ficha.get("ANO", "")
    if re.fullmatch(r"(19|20)\d{2}", ano_raw):
        ano_novo = int(ano_raw)
        if ano_novo > ANO_CORTE_CLASSICO:
            return None

    return replace(
        anuncio,
        marca=ficha["MARCA"].upper(),
        modelo=ficha["MODELO"].upper(),
        ano=ano_novo,
        versao=ficha.get("VERSAO") or anuncio.versao,
    )
