"""
Conector Ateliê do Carro — coleta anúncios de veículos clássicos.

Site: https://ateliedocarro.com.br
Motor: WordPress (Server-Side Rendering)
Estratégia: requests + BeautifulSoup em dois passos:
  1. Crawl paginado de /carros-a-venda/page/N/ → coleta URLs de detalhe
     filtrando por marca/modelo no título do card.
  2. Fetch individual de /carro/{slug}/ → extração da tabela estruturada
     (Marca/Modelo, Ano/Modelo, Valor).

Compliance (verificado 2026-05-30):
- robots.txt: Disallow: (vazio) — tudo permitido ✅
- Rate limit: 1 requisição/segundo entre páginas
- User-Agent realista definido abaixo.

Separação de responsabilidades:
- buscar()               → I/O (requests), orquestra os dois passos
- parsear_listagem_html() → função pura (BS4), usada nos testes
- parsear_detalhe_html()  → função pura (BS4), usada nos testes
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.pipeline.normalizer import normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
# Configurações do conector
# ────────────────────────────────────────────────
FONTE = "ateliedocarro"
BASE_URL = "https://ateliedocarro.com.br"
LISTING_PATH = "/carros-a-venda/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20          # segundos por requisição
MAX_RETRIES = 2
BACKOFF_SEGUNDOS = 2.0
RATE_LIMIT_SEGUNDOS = 1.0  # mínimo entre requisições


# ────────────────────────────────────────────────
# Interface pública
# ────────────────────────────────────────────────

def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """
    Busca anúncios no Ateliê do Carro por marca e modelo.

    Estratégia (dois passos):
      1. Busca WordPress via /?s={modelo}&paged=N → coleta URLs de cards
         cujo título contém modelo (e marca para pós-filtragem).
         Muito mais rápido que crawl da listagem completa — a maioria dos
         modelos retorna resultados em 1 página.
      2. Fetch de cada URL de detalhe → extrai campos estruturados da tabela
         (Marca/Modelo, Ano/Modelo, Valor).

    Args:
        marca:   Nome da marca (ex.: "VOLKSWAGEN"). Pós-filtragem por título.
        modelo:  Nome do modelo (ex.: "KOMBI"). Termo de busca WordPress.
        paginas: Número máximo de páginas de resultado a percorrer (default 2).

    Returns:
        Lista de Anuncio normalizados. Anúncios sem preço válido são descartados.
    """
    inicio = time.monotonic()
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)

    # ── Passo 1: busca WordPress ?s={modelo} ─────────────────────────────────
    urls_detalhe: list[str] = []

    for pagina in range(1, paginas + 1):
        url_pagina = _url_busca(modelo, pagina)
        logger.info("[ateliedocarro] busca página %d — %s", pagina, url_pagina)

        html = _requisitar(sessao, url_pagina)
        if html is None:
            logger.warning("[ateliedocarro] falha na página %d, continuando.", pagina)
            continue

        cards = parsear_listagem_html(html, data_coleta)

        for card in cards:
            titulo_norm = normalizar_texto(card.titulo)
            # Nota: títulos dos cards do Ateliê do Carro normalmente omitem a marca
            # (ex: "Kombi Luxo 1500 6 Portas 1972…" sem "Volkswagen").
            # A verificação de marca é feita após o fetch da página de detalhe, que
            # sempre contém a tabela MARCA/MODELO. Filtramos aqui apenas por modelo.
            if modelo_norm and modelo_norm not in titulo_norm:
                continue
            if card.url not in urls_detalhe:
                urls_detalhe.append(card.url)

        if not _tem_proxima_pagina(html):
            logger.info("[ateliedocarro] última página atingida (%d).", pagina)
            break

        if pagina < paginas:
            time.sleep(RATE_LIMIT_SEGUNDOS)

    logger.info("[ateliedocarro] %d URL(s) encontradas.", len(urls_detalhe))

    # ── Passo 2: fetch individual de cada página de detalhe ──────────────────
    anuncios: list[Anuncio] = []
    erros = 0

    for url in urls_detalhe:
        logger.info("[ateliedocarro] detalhe: %s", url)

        html = _requisitar(sessao, url)
        if html is None:
            erros += 1
            logger.warning("[ateliedocarro] falha no detalhe: %s", url)
            continue

        anuncio = parsear_detalhe_html(html, url, data_coleta)
        if anuncio is not None:
            anuncios.append(anuncio)

        time.sleep(RATE_LIMIT_SEGUNDOS)

    latencia = time.monotonic() - inicio
    logger.info(
        "[ateliedocarro] busca concluída: %d anúncio(s), %d erro(s), %.1fs",
        len(anuncios), erros, latencia,
    )
    return anuncios


def coletar_completo(max_paginas: int = 100) -> tuple[list[Anuncio], dict]:
    """
    Coleta TODOS os anúncios do site (ingestão batch), sem filtro de marca/modelo.

    Diferente de buscar(), percorre a listagem completa /carros-a-venda/page/N/
    até a última página e busca cada página de detalhe. Pensada para rodar em
    batch (1 fonte/dia, revisita mensal), não no caminho da requisição do usuário.

    Args:
        max_paginas: teto de segurança para o crawl da listagem.

    Returns:
        (anuncios, metricas) — metricas instrumenta o custo real da coleta:
        páginas lidas, requisições, erros, latência p50/p95 e tempo total.
    """
    inicio = time.monotonic()
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()
    latencias: list[float] = []

    def _fetch(url: str) -> Optional[str]:
        t0 = time.monotonic()
        html = _requisitar(sessao, url)
        latencias.append(time.monotonic() - t0)
        return html

    # ── Passo 1: crawl completo da listagem ──────────────────────────────────
    urls_detalhe: list[str] = []
    paginas_lidas = 0
    erros_listagem = 0

    for pagina in range(1, max_paginas + 1):
        url_pagina = _url_listagem(pagina)
        logger.info("[ateliedocarro] listagem página %d — %s", pagina, url_pagina)

        html = _fetch(url_pagina)
        if html is None:
            erros_listagem += 1
            logger.warning("[ateliedocarro] falha na listagem página %d.", pagina)
            break  # listagem sequencial: falha aqui encerra o crawl

        paginas_lidas += 1
        for card in parsear_listagem_html(html, data_coleta):
            if card.url not in urls_detalhe:
                urls_detalhe.append(card.url)

        if not _tem_proxima_pagina(html):
            logger.info("[ateliedocarro] última página da listagem: %d.", pagina)
            break

        time.sleep(RATE_LIMIT_SEGUNDOS)

    logger.info(
        "[ateliedocarro] listagem completa: %d página(s), %d anúncio(s).",
        paginas_lidas, len(urls_detalhe),
    )

    # ── Passo 2: fetch de cada página de detalhe ─────────────────────────────
    anuncios: list[Anuncio] = []
    erros_detalhe = 0
    descartados = 0  # detalhe sem preço válido ou sem modelo

    for i, url in enumerate(urls_detalhe, start=1):
        time.sleep(RATE_LIMIT_SEGUNDOS)
        logger.info("[ateliedocarro] detalhe %d/%d: %s", i, len(urls_detalhe), url)

        html = _fetch(url)
        if html is None:
            erros_detalhe += 1
            continue

        anuncio = parsear_detalhe_html(html, url, data_coleta)
        if anuncio is None:
            descartados += 1
        else:
            anuncios.append(anuncio)

    tempo_total = time.monotonic() - inicio
    lat_ordenadas = sorted(latencias)
    metricas = {
        "fonte": FONTE,
        "data_coleta": data_coleta,
        "paginas_listagem": paginas_lidas,
        "urls_detalhe": len(urls_detalhe),
        "anuncios_validos": len(anuncios),
        "descartados_sem_preco_ou_modelo": descartados,
        "erros_listagem": erros_listagem,
        "erros_detalhe": erros_detalhe,
        "requisicoes": len(latencias),
        "latencia_p50_s": round(lat_ordenadas[len(lat_ordenadas) // 2], 2) if lat_ordenadas else None,
        "latencia_p95_s": round(lat_ordenadas[int(len(lat_ordenadas) * 0.95)], 2) if lat_ordenadas else None,
        "tempo_total_s": round(tempo_total, 1),
        "segundos_por_anuncio": round(tempo_total / len(anuncios), 2) if anuncios else None,
    }
    logger.info("[ateliedocarro] coleta completa: %s", metricas)
    return anuncios, metricas


# ────────────────────────────────────────────────
# Parsers puros — testáveis sem I/O
# ────────────────────────────────────────────────

def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """
    Extrai cards da listagem /carros-a-venda/, usando o botão "Mais detalhes"
    de cada card como fonte do URL de detalhe.

    Retorna Anuncio com titulo, url e ano preenchidos; preco=None e
    marca/modelo="" (esses campos só estão disponíveis na página de detalhe).

    Seletores em ordem de confiabilidade:
    1. div.car-loop — estrutura real do site; URL vem do botão "Mais detalhes".
    2. h2.entry-title > a[href*="/carro/"] — fallback WordPress padrão.
    3. article > a[href*="/carro/"] — fallback genérico.
    4. qualquer a[href*="/carro/"] — último recurso.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    anuncios: list[Anuncio] = []

    # ── Seletor 1: div.car-loop — botão "Mais detalhes" ─────────────────────
    # Estrutura real do site:
    #   <div class="loop car-loop">
    #     <a href="/carro/...">                       (link da imagem)
    #     <a href="/carro/...">Título do veículo</a>  (link do título)
    #     <a href="/carro/...">1972/72</a>             (link do ano)
    #     <a class="button" href="/carro/...">Mais detalhes</a>
    #   </div>
    for card_div in soup.find_all("div", class_=lambda c: c and "car-loop" in c):
        anuncio = _anuncio_de_car_loop(card_div, data_coleta, seen)
        if anuncio:
            anuncios.append(anuncio)

    # ── Seletor 2: WordPress padrão — h2.entry-title > a[href*="/carro/"] ────
    if not anuncios:
        for h2 in soup.find_all("h2", class_=re.compile(r"entry.title|post.title", re.I)):
            link = h2.find("a", href=re.compile(r"/carro/"))
            if not link:
                continue
            anuncio = _card_de_link(link, data_coleta, seen)
            if anuncio:
                anuncios.append(anuncio)

    # ── Seletor 3: links /carro/ dentro de <article> ─────────────────────────
    if not anuncios:
        for article in soup.find_all("article"):
            for link in article.find_all("a", href=re.compile(r"/carro/")):
                anuncio = _card_de_link(link, data_coleta, seen)
                if anuncio:
                    anuncios.append(anuncio)
                    break  # um card por article

    # ── Seletor 4: último fallback — qualquer link /carro/ ───────────────────
    if not anuncios:
        for link in soup.find_all("a", href=re.compile(r"/carro/")):
            anuncio = _card_de_link(link, data_coleta, seen)
            if anuncio:
                anuncios.append(anuncio)

    return anuncios


def parsear_detalhe_html(
    html: str, url: str, data_coleta: str = "2000-01-01"
) -> Optional[Anuncio]:
    """
    Extrai anúncio completo de uma página de detalhe (/carro/{slug}/).

    Campos lidos da tabela estruturada da página:
    - "Marca/Modelo" → marca e modelo (split por "/")
    - "Ano/Modelo"   → ano de fabricação
    - "Valor"        → preço (R$ xxx.xxx)

    Fallback de preço: regex R$ no corpo da página (campo Descrição).

    Retorna None se não houver preço válido ou modelo ausente.
    """
    soup = BeautifulSoup(html, "lxml")

    # Título
    h1 = soup.find("h1")
    titulo = h1.get_text(strip=True) if h1 else ""

    # Tabela estruturada: label → valor
    tabela = _extrair_tabela(soup)

    # Marca e modelo
    marca_modelo_raw = (
        tabela.get("marca/modelo")
        or tabela.get("marca / modelo")
        or tabela.get("marca")
        or ""
    )
    marca, modelo = _split_marca_modelo(marca_modelo_raw)

    # Ano
    ano_raw = tabela.get("ano/modelo") or tabela.get("ano / modelo") or tabela.get("ano") or ""
    ano = _extrair_ano(ano_raw) or _extrair_ano(titulo) or _extrair_ano_do_slug(url)

    # Preço: linha "Valor" da tabela
    preco_raw = (
        tabela.get("valor")
        or tabela.get("preco")
        or tabela.get("preço")
        or ""
    )
    preco = normalizar_preco(preco_raw)

    # Fallback: regex R$ no corpo da página (campo Descrição em texto livre)
    if preco is None:
        corpo = soup.get_text(separator=" ")
        m = re.search(r"R\$\s*[\d.,]+", corpo)
        if m:
            preco = normalizar_preco(m.group(0))

    if preco is None or preco <= 0:
        return None

    if not modelo:
        # Último recurso: inferir do título
        partes = titulo.split()
        modelo = partes[1].upper() if len(partes) >= 2 else ""

    if not modelo:
        return None

    if not titulo:
        titulo = f"{marca} {modelo} {ano or ''}".strip()

    return Anuncio(
        titulo=titulo,
        preco=preco,
        marca=marca.upper(),
        modelo=modelo.upper(),
        ano=ano,
        versao=None,
        url=url,
        fonte=FONTE,
        data_coleta=data_coleta,
    )


# ────────────────────────────────────────────────
# Helpers internos
# ────────────────────────────────────────────────

def _criar_sessao() -> requests.Session:
    sessao = requests.Session()
    sessao.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return sessao


def _url_listagem(pagina: int) -> str:
    """Monta URL da listagem paginada (usada em parsear_listagem_html)."""
    if pagina == 1:
        return BASE_URL + LISTING_PATH
    return f"{BASE_URL}{LISTING_PATH}page/{pagina}/"


def _url_busca(modelo: str, pagina: int) -> str:
    """Monta URL de busca WordPress (?s=) para o modelo especificado."""
    import urllib.parse
    termo = urllib.parse.quote_plus(modelo.lower())
    if pagina == 1:
        return f"{BASE_URL}/?s={termo}"
    return f"{BASE_URL}/?s={termo}&paged={pagina}"


def _requisitar(sessao: requests.Session, url: str) -> Optional[str]:
    """GET com retry. Retorna HTML ou None em caso de falha."""
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            resp = sessao.get(url, timeout=TIMEOUT, verify=False)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as exc:
            logger.warning(
                "[ateliedocarro] tentativa %d/%d falhou para %s: %s",
                tentativa, MAX_RETRIES, url, exc,
            )
            if tentativa < MAX_RETRIES:
                time.sleep(BACKOFF_SEGUNDOS)
    return None


def _tem_proxima_pagina(html: str) -> bool:
    """Verifica se há link para a próxima página (WordPress pagination)."""
    soup = BeautifulSoup(html, "lxml")
    # WordPress padrão: <a class="next page-numbers"> ou <a rel="next">
    return bool(
        soup.find("a", class_=re.compile(r"next", re.I))
        or soup.find("a", rel="next")
    )


def _anuncio_de_car_loop(
    card: BeautifulSoup, data_coleta: str, seen: set[str]
) -> Optional[Anuncio]:
    """
    Extrai Anuncio parcial de um card div.car-loop.

    URL: botão "Mais detalhes" (<a class="button">), com fallback para o último
    link /carro/ do card.
    Título: primeiro link com texto que não seja "Mais detalhes" nem ano puro.
    """
    links_carro = card.find_all("a", href=re.compile(r"/carro/"))
    if not links_carro:
        return None

    # URL: preferir o botão "Mais detalhes", senão usar o último link do card
    mais_detalhes = next(
        (a for a in links_carro
         if "mais detalhes" in a.get_text(strip=True).lower()),
        links_carro[-1],
    )
    href = mais_detalhes.get("href", "")
    if href.startswith("/"):
        href = BASE_URL + href
    if not href.startswith("http") or href in seen:
        return None
    seen.add(href)

    # Título: primeiro link com texto útil (ignora "Mais detalhes" e padrão "1972/72")
    titulo = ""
    for link in links_carro:
        texto = link.get_text(strip=True)
        if (texto
                and "mais detalhes" not in texto.lower()
                and not re.fullmatch(r"\d{4}/\d{2,4}", texto)
                and len(texto) > 4):
            titulo = texto
            break

    if not titulo:
        slug = href.rstrip("/").split("/")[-1]
        titulo = slug.replace("-", " ").title()

    ano = _extrair_ano(titulo) or _extrair_ano_do_slug(href)
    return Anuncio(
        titulo=titulo,
        preco=None,
        marca="",
        modelo="",
        ano=ano,
        versao=None,
        url=href,
        fonte=FONTE,
        data_coleta=data_coleta,
    )


def _card_de_link(
    link: BeautifulSoup, data_coleta: str, seen: set[str]
) -> Optional[Anuncio]:
    """Constrói Anuncio parcial a partir de um <a href="/carro/...">."""
    href = link.get("href", "")
    if not href:
        return None

    # Normalizar para URL absoluta
    if href.startswith("/"):
        href = BASE_URL + href

    if not href.startswith("http") or href in seen:
        return None

    # NÃO adicionar a seen ainda — só após título confirmado.
    # Sem isso, o image-link (texto vazio) bloqueia o title-link subsequente
    # quando há múltiplos <a> para o mesmo href no mesmo card.

    # Título: texto do link
    titulo = link.get_text(strip=True)

    # Fallback: h2/h1 mais próximo
    if not titulo:
        parent = link.parent
        while parent and parent.name not in ("article", "section", "div", "li", "body"):
            heading = parent.find(["h2", "h1", "h3"])
            if heading:
                titulo = heading.get_text(strip=True)
                break
            parent = parent.parent

    if not titulo:
        return None

    seen.add(href)  # Marca como visto somente após título confirmado

    ano = _extrair_ano(titulo) or _extrair_ano_do_slug(href)

    return Anuncio(
        titulo=titulo,
        preco=None,
        marca="",
        modelo="",
        ano=ano,
        versao=None,
        url=href,
        fonte=FONTE,
        data_coleta=data_coleta,
    )


def _extrair_tabela(soup: BeautifulSoup) -> dict[str, str]:
    """
    Extrai pares label→valor de todas as <table> e <dl> da página.

    Labels são normalizados para lowercase sem acento para lookups
    case-insensitive. O separador "/" é preservado (ex: "marca/modelo").
    """
    resultado: dict[str, str] = {}

    # <table> com linhas <tr><th>Label</th><td>Valor</td></tr>
    for tabela in soup.find_all("table"):
        for tr in tabela.find_all("tr"):
            celulas = tr.find_all(["th", "td"])
            if len(celulas) >= 2:
                label = _normalizar_label(celulas[0].get_text(strip=True))
                valor = celulas[1].get_text(strip=True)
                if label:
                    resultado[label] = valor

    # <dl><dt>Label</dt><dd>Valor</dd></dl> — alguns temas WordPress usam isso
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            label = _normalizar_label(dt.get_text(strip=True))
            valor = dd.get_text(strip=True)
            if label:
                resultado[label] = valor

    return resultado


def _normalizar_label(texto: str) -> str:
    """
    Normaliza label da tabela para lookup robusto.

    Remove acentos, converte para minúsculas, colapsa espaços ao redor de "/".
    Exemplos:
        "Marca/Modelo"   → "marca/modelo"
        "Marca / Modelo" → "marca/modelo"
        "Ano de Fab."    → "ano de fab."
    """
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    resultado = sem_acento.lower().strip()
    # Colapsar espaços ao redor de /
    resultado = re.sub(r"\s*/\s*", "/", resultado)
    return resultado


def _split_marca_modelo(valor: str) -> tuple[str, str]:
    """
    Divide string "Marca/Modelo" ou "Marca / Modelo".

    Exemplos:
        "Volkswagen/Kombi"    → ("Volkswagen", "Kombi")
        "Volkswagen / Kombi"  → ("Volkswagen", "Kombi")
        "Volkswagen"          → ("Volkswagen", "")
        ""                    → ("", "")
    """
    partes = [p.strip() for p in valor.split("/") if p.strip()]
    if len(partes) >= 2:
        return partes[0], partes[1]
    if len(partes) == 1:
        return partes[0], ""
    return "", ""


def _extrair_ano(texto: str) -> Optional[int]:
    """Extrai o primeiro ano no intervalo 1900–2099 do texto."""
    m = re.search(r"\b(19|20)\d{2}\b", texto)
    return int(m.group(0)) if m else None


def _extrair_ano_do_slug(url: str) -> Optional[int]:
    """Extrai ano do slug/URL, se presente."""
    m = re.search(r"\b(19|20)\d{2}\b", url)
    return int(m.group(0)) if m else None
