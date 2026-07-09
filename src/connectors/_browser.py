"""
Helper Playwright compartilhado — cria contexto de browser com suporte opcional
a proxy residencial (DataImpulse) e a stealth (mascarar fingerprint de
automação do Chromium), usado por conectores bloqueados por reputação de IP
de datacenter e/ou detecção de automação: mercadolivre, reginaldodecampinas.

(registro9, lopesantigos, lexicar e autoclassic foram removidos do projeto em
2026-07-08 — não era bloqueio de IP, os domínios pararam de resolver / os
sites saíram do ar ou perderam a seção de classificados.)

Proxy é ativado automaticamente se DATAIMPULSE_HOST/PORT/USER/PASS estiverem
definidos no ambiente (.env); caso contrário conecta direto, sem proxy.

Stealth (playwright-stealth) é aplicado por padrão. Investigação ao vivo em
2026-07-08 mostrou que o Mercado Livre bloqueia Playwright "puro" (headless ou
headed) ~92% das vezes mesmo com IP residencial brasileiro — é detecção de
fingerprint de automação via CDP, não reputação de IP. Com stealth aplicado
(navigator.webdriver mascarado etc.), a taxa de bloqueio caiu para 0/12 nos
testes. Uso de stealth para coleta de dados públicos (preços de anúncios) foi
autorizado explicitamente pelo usuário em 2026-07-08, ciente de que contraria
o espírito dos mecanismos anti-bot do ML.
"""
from __future__ import annotations

import logging
import os
import uuid
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_PAIS_PADRAO = "br"


def _proxy_config(pais: str = _PAIS_PADRAO) -> Optional[dict]:
    """
    Monta a config de proxy do Playwright a partir das env vars DATAIMPULSE_*.

    Usa sticky session (sufixo `__cr.<pais>;sessid.<id>` no usuário) para manter
    o mesmo IP de saída durante todo o contexto de browser — sem isso, o pool
    residencial troca de IP a cada requisição, o que quebra sessões e dispara
    CAPTCHA em sites como o Mercado Livre.
    """
    host = os.environ.get("DATAIMPULSE_HOST", "")
    port = os.environ.get("DATAIMPULSE_PORT", "")
    user = os.environ.get("DATAIMPULSE_USER", "")
    senha = os.environ.get("DATAIMPULSE_PASS", "")
    if not (host and port and user and senha):
        return None

    sessid = uuid.uuid4().hex[:12]
    username_sticky = f"{user}__cr.{pais};sessid.{sessid}"
    return {
        "server": f"http://{host}:{port}",
        "username": username_sticky,
        "password": senha,
    }


def proxy_configurado() -> bool:
    """True se as env vars DATAIMPULSE_* estiverem completas."""
    return _proxy_config() is not None


def _aplicar_stealth(ctx, locale: str) -> None:
    from playwright_stealth import Stealth

    idioma = locale.split("-")[0] if "-" in locale else locale
    Stealth(navigator_languages_override=(locale, idioma)).apply_stealth_sync(ctx)


@contextmanager
def criar_contexto(headless: bool = True, locale: str = "pt-BR", pais: str = _PAIS_PADRAO, stealth: bool = True):
    """
    Abre um browser Chromium via Playwright — com proxy residencial DataImpulse
    se configurado e stealth aplicado por padrão — e devolve um BrowserContext
    pronto para uso. Fecha o browser automaticamente ao sair do bloco `with`.

    Todo o contexto (um `with`) usa o mesmo IP de saída (sticky session), então
    reaproveite um único contexto para toda uma coleta em vez de abrir um novo
    por requisição.

    Uso:
        with criar_contexto() as ctx:
            page = ctx.new_page()
            page.goto(url)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright não instalado. Execute: pip install playwright && "
            "python -m playwright install chromium"
        ) from exc

    proxy = _proxy_config(pais)
    if proxy:
        logger.info("[_browser] usando proxy residencial DataImpulse (%s)", proxy["server"])
    else:
        logger.warning(
            "[_browser] DATAIMPULSE_* não configurado — conectando sem proxy "
            "(risco de bloqueio por reputação de IP de datacenter)"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            proxy=proxy,
        )
        ctx = browser.new_context(user_agent=USER_AGENT, locale=locale)
        if stealth:
            _aplicar_stealth(ctx, locale)
        try:
            yield ctx
        finally:
            browser.close()


@contextmanager
def criar_contexto_aquecido(
    url_aquecimento: str,
    bloqueado: Callable[[object], bool],
    headless: bool = True,
    locale: str = "pt-BR",
    pais: str = _PAIS_PADRAO,
    max_tentativas: int = 5,
    espera_aquecimento_ms: int = 2500,
    stealth: bool = True,
):
    """
    Como `criar_contexto`, mas visita `url_aquecimento` antes de devolver o
    contexto ao chamador. Sites com anti-bot agressivo (ex.: Mercado Livre)
    costumam bloquear IPs residenciais "não vistos" com mais frequência —
    aquecer a sessão visitando a home antes da página alvo reduz bastante essa
    taxa, e IPs que passam no aquecimento tendem a continuar passando pelo
    resto da sessão.

    Se `bloqueado(page)` indicar bloqueio (ex.: `"captcha" in page.url`) após o
    aquecimento, a sessão inteira é descartada — novo `sessid`, novo IP
    residencial — e tentamos de novo, até `max_tentativas`. Levanta
    RuntimeError se todas as tentativas forem bloqueadas.

    Devolve (ctx, page) com a MESMA aba usada no aquecimento — reaproveitar
    essa aba (em vez de abrir uma nova com `ctx.new_page()`) é importante:
    abrir uma aba nova para a navegação seguinte reseta o histórico de
    navegação e volta a disparar bloqueio no Mercado Livre, mesmo no mesmo IP.

    Uso:
        with criar_contexto_aquecido(
            "https://www.mercadolivre.com.br/",
            bloqueado=lambda page: "captcha" in page.url,
        ) as (ctx, page):
            page.goto(url_busca, referer="https://www.mercadolivre.com.br/")
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright não instalado. Execute: pip install playwright && "
            "python -m playwright install chromium"
        ) from exc

    with sync_playwright() as p:
        for tentativa in range(1, max_tentativas + 1):
            proxy = _proxy_config(pais)
            browser = p.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                proxy=proxy,
            )
            ctx = browser.new_context(user_agent=USER_AGENT, locale=locale)
            if stealth:
                _aplicar_stealth(ctx, locale)
            page = ctx.new_page()

            try:
                page.goto(url_aquecimento, timeout=45000, wait_until="load")
                page.wait_for_timeout(espera_aquecimento_ms)
            except Exception as exc:
                logger.warning(
                    "[_browser] erro no aquecimento (tentativa %d/%d): %s",
                    tentativa, max_tentativas, exc,
                )
                browser.close()
                continue

            if bloqueado(page):
                logger.warning(
                    "[_browser] sessão bloqueada no aquecimento (tentativa %d/%d) — trocando IP",
                    tentativa, max_tentativas,
                )
                browser.close()
                continue

            logger.info("[_browser] sessão aquecida com sucesso (tentativa %d/%d)", tentativa, max_tentativas)
            try:
                yield ctx, page
            finally:
                browser.close()
            return

        raise RuntimeError(
            f"[_browser] não foi possível aquecer sessão em {url_aquecimento} "
            f"após {max_tentativas} tentativas — todas bloqueadas"
        )
