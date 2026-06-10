"""
Conector Maxicar — coleta anúncios de veículos antigos à venda.

Site: https://www.maxicar.com.br
Motor: WordPress + WooCommerce
Estratégia: requests + BeautifulSoup na listagem de produtos

Compliance:
- robots.txt verificado em 2026-05-29: /veiculos-antigos-a-venda/ é permitido.
- Rate limit: máx. 1 requisição/segundo (sleep de 1s entre páginas).
- User-Agent realista definido abaixo.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.pipeline.normalizer import inferir_marca_modelo_ano, normalizar_preco, normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
# Aliases de marcas (abreviações reconhecidas)
# ────────────────────────────────────────────────
# Mapeamento de forma canônica → conjunto de aliases conhecidos.
# Garante que "VW" e "VOLKSWAGEN" sejam tratados como equivalentes.
_MARCA_ALIASES: dict[str, frozenset[str]] = {
    "VOLKSWAGEN": frozenset(["VW", "VOLKS", "VOLKSWAGEN"]),
    "CHEVROLET": frozenset(["GM", "CHEVY", "CHEVROLET", "GENERAL MOTORS"]),
    "MERCEDES-BENZ": frozenset(["MERCEDES", "MERCEDES-BENZ", "MERCEDES BENZ", "MB"]),
    "FORD": frozenset(["FORD"]),
    "FIAT": frozenset(["FIAT"]),
    "TOYOTA": frozenset(["TOYOTA"]),
    "HONDA": frozenset(["HONDA"]),
    "RENAULT": frozenset(["RENAULT"]),
    "PEUGEOT": frozenset(["PEUGEOT"]),
}
# Índice reverso: qualquer alias → forma canônica
_ALIAS_PARA_CANONICAL: dict[str, str] = {
    alias: canonical
    for canonical, aliases in _MARCA_ALIASES.items()
    for alias in aliases
}


def _marcas_equivalentes(marca_a: str, marca_b: str) -> bool:
    """Retorna True se as duas marcas são equivalentes (inclui aliases/abreviações)."""
    if marca_a == marca_b:
        return True
    canonical_a = _ALIAS_PARA_CANONICAL.get(marca_a, marca_a)
    canonical_b = _ALIAS_PARA_CANONICAL.get(marca_b, marca_b)
    return canonical_a == canonical_b


# ────────────────────────────────────────────────
# Configurações do conector
# ────────────────────────────────────────────────
FONTE = "maxicar"
BASE_URL = "https://www.maxicar.com.br/veiculos-antigos-a-venda/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20  # segundos por requisição
MAX_RETRIES = 2
BACKOFF_SEGUNDOS = 2.0
RATE_LIMIT_SEGUNDOS = 1.0  # mínimo entre requisições


def buscar(marca: str, modelo: str, paginas: int = 2) -> list[Anuncio]:
    """
    Busca anúncios no Maxicar por marca e modelo.

    Estratégia de busca:
    - O WooCommerce do Maxicar retorna resultados mais precisos com o modelo
      como termo principal. Buscar "VOLKSWAGEN KOMBI" retorna 0 resultados;
      buscar "KOMBI" retorna 3. Por isso usamos só o modelo como termo de
      busca e fazemos pós-filtragem pela marca em Python.

    Args:
        marca:   Nome da marca (ex.: "VOLKSWAGEN"). Usado para pós-filtragem.
        modelo:  Nome do modelo (ex.: "KOMBI"). Usado como termo de busca.
        paginas: Número máximo de páginas a percorrer (default 2).

    Returns:
        Lista de Anuncio normalizados. Anúncios sem preço válido são descartados.
    """
    inicio = time.monotonic()
    sessao = _criar_sessao()
    data_coleta = date.today().isoformat()

    # Usar apenas o modelo como termo de busca (mais eficaz no WooCommerce)
    termo_busca = modelo.strip()
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo.strip())
    anuncios: list[Anuncio] = []
    erros = 0

    for pagina in range(1, paginas + 1):
        url_pagina = _url_pagina(termo_busca, pagina)
        logger.info("[maxicar] buscando página %d — %s", pagina, url_pagina)

        html, url_final = _requisitar(sessao, url_pagina)
        if html is None:
            erros += 1
            logger.warning("[maxicar] falha na página %d, continuando.", pagina)
            continue

        # WooCommerce redireciona para a página de detalhe quando há resultado único.
        # Detectar pelo padrão de URL /classificados/ e parsear como produto avulso.
        if url_final and "/classificados/" in url_final and url_final != url_pagina:
            logger.info(
                "[maxicar] redirect detectado para página de detalhe: %s", url_final
            )
            item = _parsear_produto_detalhe(html, url_final, data_coleta)
            itens_brutos = [item] if item else []
        else:
            itens_brutos = _parsear_listagem(html, data_coleta)
        # Pós-filtragem por marca (case-insensitive, normalizado + aliases)
        if marca_norm:
            itens = [
                a for a in itens_brutos
                if not a.marca
                or _marcas_equivalentes(normalizar_texto(a.marca), marca_norm)
                or marca_norm in normalizar_texto(a.titulo)
            ]
        else:
            itens = itens_brutos
        # Pós-filtragem por modelo: garante que o WooCommerce não trouxe outros
        # modelos da mesma marca (ex.: PAMPA quando buscou DEL REY).
        if modelo_norm:
            itens = [
                a for a in itens
                if not a.modelo
                or modelo_norm in normalizar_texto(a.modelo)
                or normalizar_texto(a.modelo) in modelo_norm
                or modelo_norm in normalizar_texto(a.titulo)
            ]
        logger.info(
            "[maxicar] página %d: %d anúncio(s) encontrado(s) (%d antes de filtro de marca).",
            pagina, len(itens), len(itens_brutos),
        )
        anuncios.extend(itens)

        # Verificar se há próxima página
        if not _tem_proxima_pagina(html, pagina):
            logger.info("[maxicar] última página atingida (%d).", pagina)
            break

        if pagina < paginas:
            time.sleep(RATE_LIMIT_SEGUNDOS)

    latencia = time.monotonic() - inicio
    logger.info(
        "[maxicar] busca concluída: %d anúncio(s) coletados, %d erro(s), %.1fs",
        len(anuncios), erros, latencia,
    )

    return anuncios


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


def _url_pagina(termo: str, pagina: int) -> str:
    """Monta URL de busca para a página especificada."""
    import urllib.parse
    params = urllib.parse.urlencode({"s": termo})
    if pagina == 1:
        return f"{BASE_URL}?{params}"
    return f"{BASE_URL}page/{pagina}/?{params}"


def _requisitar(sessao: requests.Session, url: str) -> tuple[Optional[str], Optional[str]]:
    """
    Executa GET com retry. Retorna (html, url_final) ou (None, None) em caso de falha.
    url_final pode diferir de url quando o servidor redireciona (ex.: WooCommerce
    redireciona busca com resultado único direto para a página do produto).
    """
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            resp = sessao.get(url, timeout=TIMEOUT, verify=False)
            resp.raise_for_status()
            return resp.text, resp.url
        except requests.RequestException as exc:
            logger.warning(
                "[maxicar] erro tentativa %d/%d para %s: %s",
                tentativa, MAX_RETRIES, url, exc,
            )
            if tentativa < MAX_RETRIES:
                time.sleep(BACKOFF_SEGUNDOS)
    return None, None


def _parsear_produto_detalhe(html: str, url_produto: str, data_coleta: str) -> Optional[Anuncio]:
    """
    Extrai dados de uma página de detalhe de produto WooCommerce.
    Usado quando a busca retorna um único resultado e o servidor redireciona
    diretamente para a página do produto em vez de exibir a grade de listagem.
    """
    soup = BeautifulSoup(html, "lxml")

    titulo_tag = soup.find("h1", class_="product_title") or soup.find("h1")
    titulo = titulo_tag.get_text(strip=True) if titulo_tag else ""
    if not titulo:
        return None

    preco_tag = soup.find("p", class_="price")
    preco_span = preco_tag.find("span", class_="woocommerce-Price-amount") if preco_tag else None
    preco_bruto = preco_span.get_text(strip=True) if preco_span else ""
    preco = normalizar_preco(preco_bruto)

    if preco is None or preco <= 0:
        return None

    marca, modelo, ano = inferir_marca_modelo_ano(titulo)
    if not modelo:
        return None

    return Anuncio(
        titulo=titulo,
        preco=preco,
        marca=marca,
        modelo=modelo,
        ano=ano,
        versao=None,
        url=url_produto,
        fonte=FONTE,
        data_coleta=data_coleta,
    )


def _parsear_listagem(html: str, data_coleta: str) -> list[Anuncio]:
    """
    Extrai anúncios de uma página de listagem WooCommerce do Maxicar.

    Campos extraídos da listagem:
    - titulo: h2.woocommerce-loop-product__title
    - preco:  span.woocommerce-Price-amount bdi
    - url:    a.woocommerce-loop-product__link[href]
    - marca/modelo/ano: inferidos do título
    """
    soup = BeautifulSoup(html, "lxml")
    produtos = soup.find_all("li", class_="product")
    anuncios: list[Anuncio] = []

    for produto in produtos:
        titulo_tag = produto.find("h2", class_="woocommerce-loop-product__title")
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else ""

        if not titulo:
            continue

        # Preço
        preco_tag = produto.find("span", class_="woocommerce-Price-amount")
        preco_bruto = preco_tag.get_text(strip=True) if preco_tag else ""
        preco = normalizar_preco(preco_bruto)

        # URL do anúncio
        link_tag = produto.find("a", class_="woocommerce-loop-product__link")
        url_anuncio = link_tag["href"] if link_tag and link_tag.get("href") else ""

        # Inferência de marca/modelo/ano a partir do título
        marca, modelo, ano = inferir_marca_modelo_ano(titulo)

        # Descartar se sem preço ou sem modelo
        if preco is None or preco <= 0 or not modelo:
            continue

        anuncio = Anuncio(
            titulo=titulo,
            preco=preco,
            marca=marca,
            modelo=modelo,
            ano=ano,
            versao=None,  # disponível apenas na página de detalhe
            url=url_anuncio,
            fonte=FONTE,
            data_coleta=data_coleta,
        )
        anuncios.append(anuncio)

    return anuncios


def _tem_proxima_pagina(html: str, pagina_atual: int) -> bool:
    """
    Verifica se existe link para a próxima página na paginação WooCommerce.
    """
    soup = BeautifulSoup(html, "lxml")
    nav = soup.find("nav", class_="woocommerce-pagination")
    if not nav:
        return False
    # Procurar link com classe 'next'
    proximo = nav.find("a", class_="next")
    return proximo is not None


def parsear_listagem_html(html: str, data_coleta: str = "2000-01-01") -> list[Anuncio]:
    """
    Ponto de entrada público para parsear HTML de listagem.
    Usado nos testes de regressão com snapshot.
    """
    return _parsear_listagem(html, data_coleta)
