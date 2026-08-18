"""
Obtém e renova o token OAuth do Mercado Livre.

LEIA ANTES DE INVESTIR NISTO: a API do ML NÃO serve para coletar preço de
mercado. Medido com token válido em 2026-08-18 (user_id 21564580, escopo
read):

    /users/me                      200   funciona
    /sites/MLB/search?category=    403   forbidden
    /sites/MLB/search?q=           403   forbidden
    /items/{id} de outro vendedor  403   access_denied
    /items?ids=...                 200   envelope ok, TODO item 403 dentro
    /categories/{id}, /trends/...  200   só metadado, sem anúncio

É uma API de integração de VENDEDOR: dá acesso aos itens da própria conta,
não ao mercado. A tabela de descontinuações deles confirma - a busca por
categoria não tem substituição. Não há caminho oficial para o que o coletor
precisa, e nenhum token muda isso.

Este arquivo fica no repositório para registrar o resultado e poupar a
próxima pessoa de refazer o percurso, e porque o token continua servindo
para qualquer integração futura ligada à conta em si.

O ML não tem fluxo de credenciais de cliente: o token sai sempre de uma
autorização feita por uma pessoa no navegador. Isso acontece UMA vez; daí em
diante o refresh_token mantém o acesso vivo sozinho.

Cadastre no .env (nunca no git - ver .gitignore):
    ML_CLIENT_ID=...
    ML_CLIENT_SECRET=...
    ML_REDIRECT_URI=https://valorclassico.com.br/oauth

Uso:
    python scripts/ml_oauth.py autorizar   # imprime a URL pra abrir no navegador
    python scripts/ml_oauth.py trocar CODE # troca o code pelo token (uma vez)
    python scripts/ml_oauth.py token       # devolve um access token válido
    python scripts/ml_oauth.py testar      # confere se o token funciona

ARMADILHA: o refresh_token é de uso único e cada renovação devolve um novo.
Perder o novo trava o acesso e obriga a refazer a autorização no navegador.
Por isso a gravação é atômica (escreve em arquivo temporário e renomeia) e
acontece ANTES de o token novo ser usado pra qualquer coisa.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(RAIZ / ".env")

import requests

AUTORIZACAO_URL = "https://auth.mercadolivre.com.br/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
# Fica fora do git: carrega segredo de longa duração.
ARQUIVO_TOKEN = RAIZ / "data" / ".ml_token.json"
# O ML diz 6h (21600s). Renovamos antes pra não esbarrar no limite em
# coleta longa, que roda mais de uma hora.
MARGEM_S = 900


def _cfg(nome: str) -> str:
    v = os.environ.get(nome, "").strip()
    if not v:
        raise SystemExit(
            f"Falta {nome} no .env. Veja o cabeçalho deste arquivo."
        )
    return v


def _gravar(dados: dict) -> None:
    """Gravação atômica: o refresh_token é de uso único e não pode se perder."""
    ARQUIVO_TOKEN.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARQUIVO_TOKEN.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, indent=2), encoding="utf-8")
    tmp.replace(ARQUIVO_TOKEN)


def _ler() -> dict:
    if not ARQUIVO_TOKEN.exists():
        raise SystemExit(
            "Nenhum token guardado. Rode 'autorizar' e depois 'trocar CODE'."
        )
    return json.loads(ARQUIVO_TOKEN.read_text(encoding="utf-8"))


def _guardar_resposta(r: requests.Response) -> dict:
    if r.status_code != 200:
        raise SystemExit(f"ML respondeu {r.status_code}: {r.text[:400]}")
    d = r.json()
    dados = {
        "access_token": d["access_token"],
        "refresh_token": d.get("refresh_token"),
        "user_id": d.get("user_id"),
        "scope": d.get("scope"),
        "expira_em": time.time() + int(d.get("expires_in", 21600)),
    }
    _gravar(dados)
    return dados


def autorizar() -> None:
    estado = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": _cfg("ML_CLIENT_ID"),
        "redirect_uri": _cfg("ML_REDIRECT_URI"),
        "state": estado,
    }
    print("Abra esta URL no navegador, logado na conta DONA do aplicativo:\n")
    print(f"{AUTORIZACAO_URL}?{urlencode(params)}\n")
    print("Depois de autorizar, o navegador vai pra sua redirect_uri com")
    print("?code=TG-xxxxx na barra de endereço (a página pode dar 404 - tudo")
    print("bem, o que importa é o code). Copie o code e rode:")
    print("\n    python scripts/ml_oauth.py trocar TG-xxxxx\n")
    print(f"(state gerado: {estado})")


def trocar(code: str) -> None:
    r = requests.post(TOKEN_URL, timeout=30,
                      headers={"accept": "application/json"},
                      data={
                          "grant_type": "authorization_code",
                          "client_id": _cfg("ML_CLIENT_ID"),
                          "client_secret": _cfg("ML_CLIENT_SECRET"),
                          "code": code,
                          "redirect_uri": _cfg("ML_REDIRECT_URI"),
                      })
    d = _guardar_resposta(r)
    print(f"Token guardado em {ARQUIVO_TOKEN}")
    print(f"  user_id: {d['user_id']}   escopo: {d['scope']}")
    print("  A autorização no navegador não precisa ser repetida.")


def token() -> str:
    d = _ler()
    if time.time() < d["expira_em"] - MARGEM_S:
        return d["access_token"]
    if not d.get("refresh_token"):
        raise SystemExit("Token expirado e sem refresh_token: refaça a autorização.")
    r = requests.post(TOKEN_URL, timeout=30,
                      headers={"accept": "application/json"},
                      data={
                          "grant_type": "refresh_token",
                          "client_id": _cfg("ML_CLIENT_ID"),
                          "client_secret": _cfg("ML_CLIENT_SECRET"),
                          "refresh_token": d["refresh_token"],
                      })
    return _guardar_resposta(r)["access_token"]


def testar() -> None:
    t = token()
    cab = {"Authorization": f"Bearer {t}"}
    r = requests.get("https://api.mercadolibre.com/users/me", headers=cab, timeout=30)
    print(f"/users/me -> {r.status_code} {r.text[:160]}")
    # A pergunta que decide o projeto: a busca aberta por categoria responde?
    r2 = requests.get(
        "https://api.mercadolibre.com/sites/MLB/search?category=MLB1744&limit=1",
        headers=cab, timeout=30)
    print(f"/sites/MLB/search?category -> {r2.status_code} {r2.text[:220]}")
    r3 = requests.get(
        "https://api.mercadolibre.com/items?ids=MLB1234567890&attributes=id,status,price",
        headers=cab, timeout=30)
    print(f"/items?ids (multiget) -> {r3.status_code} {r3.text[:220]}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "autorizar":
        autorizar()
    elif cmd == "trocar" and len(sys.argv) > 2:
        trocar(sys.argv[2])
    elif cmd == "token":
        print(token())
    elif cmd == "testar":
        testar()
    else:
        raise SystemExit(__doc__)
