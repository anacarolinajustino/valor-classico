"""
Valor Clássico — servidor web MVP.

Endpoints:
  GET  /                      → serve index.html
  GET  /api/buscar            → busca anúncios e calcula estatísticas
  GET  /api/modelos           → lista modelos disponíveis no catálogo para uma marca
  GET  /api/anos              → lista anos disponíveis no catálogo para marca+modelo

Query params de /api/buscar:
  marca   (str, obrigatório)
  modelo  (str, obrigatório)
  ano     (int, opcional)
  paginas (int, opcional, default=2)
"""
from __future__ import annotations

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

# Garante que o diretório raiz do projeto está no path
sys.path.insert(0, str(Path(__file__).parent))

from src.catalog.loader import carregar_catalogo
from src.connectors.ateliedocarro import buscar as ateliedocarro_buscar
from src.connectors.maxicar import buscar as maxicar_buscar
from src.connectors.superantigo import buscar as superantigo_buscar
from src.pipeline.deduplicator import deduplicar
from src.pipeline.normalizer import normalizar_texto
from src.pipeline.outlier_filter import filtrar_outliers
from src.pipeline.persistence import (
    get_historico,
    get_mais_pesquisados,
    init_db,
    log_search,
    upsert_preco,
)
from src.pipeline.schema import validar
from src.pipeline.stats import calcular

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")

# Pré-carrega catálogo na inicialização para evitar latência na primeira busca
catalogo = carregar_catalogo()
logger.info("Catálogo pronto: %d entradas marca+modelo", len(catalogo))

# Garante que o banco de histórico existe
init_db()
logger.info("Banco de histórico inicializado")


# ──────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────

def _modelos_para_marca(marca_norm: str) -> list[str]:
    """Retorna lista de modelos canônicos para uma marca normalizada."""
    modelos: set[str] = set()
    for (m_norm, mo_norm) in catalogo:
        if m_norm == marca_norm:
            # Recuperar o nome original não é possível só pelo índice normalizado,
            # então devolvemos a chave normalizada em uppercase como proxy MVP.
            modelos.add(mo_norm.upper())
    return sorted(modelos)


def _anos_para_marca_modelo(marca_norm: str, modelo_norm: str) -> list[int]:
    """Retorna lista de anos disponíveis no catálogo para marca+modelo.

    O catálogo CSV pode ter dados até anos anteriores ao limite de 20 anos
    atrás. Quando isso ocorre, o intervalo é estendido até current_year - 20
    para que modelos ainda comercializados naquele período apareçam no filtro.
    """
    anos = catalogo.get((marca_norm, modelo_norm), set())
    if anos:
        ano_limite = date.today().year - 20
        if max(anos) < ano_limite:
            anos = anos | set(range(max(anos) + 1, ano_limite + 1))
    return sorted(anos)


# ──────────────────────────────────────────────────────
# Rotas
# ──────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/marcas")
def api_marcas():
    marcas = sorted(set(
        m.upper()
        for m, _ in catalogo.keys()
    ))
    return jsonify({"marcas": marcas})


@app.route("/api/modelos")
def api_modelos():
    marca = request.args.get("marca", "").strip()
    if not marca:
        return jsonify({"erro": "Parâmetro 'marca' obrigatório"}), 400
    marca_norm = normalizar_texto(marca)
    modelos = _modelos_para_marca(marca_norm)
    return jsonify({"marca": marca.upper(), "modelos": modelos})


@app.route("/api/anos")
def api_anos():
    marca = request.args.get("marca", "").strip()
    modelo = request.args.get("modelo", "").strip()
    if not marca or not modelo:
        return jsonify({"erro": "Parâmetros 'marca' e 'modelo' obrigatórios"}), 400
    marca_norm = normalizar_texto(marca)
    modelo_norm = normalizar_texto(modelo)
    anos = _anos_para_marca_modelo(marca_norm, modelo_norm)
    return jsonify({"marca": marca.upper(), "modelo": modelo.upper(), "anos": anos})


@app.route("/api/buscar")
def api_buscar():
    marca = request.args.get("marca", "").strip()
    modelo = request.args.get("modelo", "").strip()
    ano_raw = request.args.get("ano", "").strip()

    if not marca or not modelo:
        return jsonify({"erro": "Parâmetros 'marca' e 'modelo' são obrigatórios"}), 400

    try:
        paginas = int(request.args.get("paginas", 2))
        paginas = max(1, min(paginas, 10))  # limita entre 1 e 10
    except ValueError:
        paginas = 2

    ano_filtro: int | None = None
    if ano_raw:
        try:
            ano_filtro = int(ano_raw)
        except ValueError:
            return jsonify({"erro": f"Ano inválido: '{ano_raw}'"}), 400

    logger.info("Busca: marca=%s modelo=%s ano=%s paginas=%d", marca, modelo, ano_filtro, paginas)

    anuncios = []
    fontes_com_dados: list[str] = []
    fontes_com_falha: list[str] = []

    # Conectores ativos — rodam em paralelo
    _CONECTORES = [
        ("Maxicar", maxicar_buscar),
        ("Super Antigo", superantigo_buscar),
        ("Ateliê do Carro", ateliedocarro_buscar),
    ]

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(_CONECTORES)) as pool:
        futures = {
            pool.submit(fn, marca, modelo, paginas): nome
            for nome, fn in _CONECTORES
        }
        for future in as_completed(futures):
            nome = futures[future]
            try:
                itens = future.result()
                anuncios.extend(itens)
                if itens:
                    fontes_com_dados.append(nome)
            except Exception as exc:
                logger.warning("[api_buscar] falha em %s: %s", nome, exc)
                fontes_com_falha.append(nome)

    logger.info(
        "[api_buscar] coleta paralela concluída em %.1fs — %d anúncio(s) de %s",
        time.monotonic() - t0, len(anuncios), fontes_com_dados,
    )

    if not anuncios and fontes_com_falha:
        return jsonify({"erro": "Falha em todas as fontes. Tente novamente em instantes."}), 503

    # Filtrar por ano, se solicitado
    if ano_filtro:
        anuncios = [a for a in anuncios if a.ano == ano_filtro]

    # Pipeline de qualidade
    anuncios = [a for a in anuncios if validar(a)]
    anuncios = deduplicar(anuncios)
    anuncios = filtrar_outliers(anuncios)

    # Agrupa por ano e calcula estatísticas por ano
    por_ano: dict = {}
    for a in anuncios:
        if a.ano is not None:
            por_ano.setdefault(a.ano, []).append(a)

    linhas = []
    for ano_key in sorted(por_ano, reverse=True):
        s = calcular(por_ano[ano_key])
        if s["amostra"] > 0:
            linhas.append({
                "ano": ano_key,
                "media": s["media"],
                "mediana": s["mediana"],
                "minimo": s["minimo"],
                "maximo": s["maximo"],
                "amostra": s["amostra"],
            })

    total_amostra = sum(l["amostra"] for l in linhas)

    # Anúncios individuais — só quando o usuário filtrou por ano específico
    anuncios_lista = []
    if ano_filtro and ano_filtro in por_ano:
        for a in por_ano[ano_filtro]:
            url = a.url or ""
            if url.startswith("http://") or url.startswith("https://"):
                anuncios_lista.append({
                    "titulo": a.titulo or "",
                    "preco": a.preco,
                    "url": url,
                    "fonte": a.fonte or "",
                })

    # Persiste histórico e log de busca (fire-and-forget, não bloqueia resposta)
    try:
        for linha in linhas:
            upsert_preco(
                marca=marca,
                modelo=modelo,
                ano=linha["ano"],
                preco_medio=linha["media"],
                preco_mediano=linha["mediana"],
                preco_min=linha["minimo"],
                preco_max=linha["maximo"],
                amostra=linha["amostra"],
            )
        log_search(marca, modelo)
    except Exception as exc:
        logger.warning("Falha ao persistir histórico: %s", exc)

    return jsonify({
        "consulta": {
            "marca": marca.upper(),
            "modelo": modelo.upper(),
            "ano": ano_filtro,
        },
        "linhas": linhas,
        "total_amostra": total_amostra,
        "anuncios": anuncios_lista,
        "fontes_ativas": fontes_com_dados,
        "fontes_com_falha": fontes_com_falha,
    })


@app.route("/api/historico")
def api_historico():
    marca = request.args.get("marca", "").strip()
    modelo = request.args.get("modelo", "").strip()
    if not marca or not modelo:
        return jsonify({"erro": "Parâmetros 'marca' e 'modelo' são obrigatórios"}), 400
    return jsonify(get_historico(marca, modelo))


@app.route("/api/mais-pesquisados")
def api_mais_pesquisados():
    try:
        limit = int(request.args.get("limit", 10))
        limit = max(1, min(limit, 50))
    except ValueError:
        limit = 10
    return jsonify(get_mais_pesquisados(limit=limit))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
