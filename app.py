"""
Valor Clássico — painel de coleta e administração.

Ferramenta interna: painel de status das fontes, disparo de coleta e
listagem dos anúncios coletados. O site público (busca por marca/modelo/ano)
é um projeto separado (`valor-classico-web`).

Endpoints:
  GET  /                                  → redireciona pro painel (/admin)
  GET  /admin                             → painel de status e coleta
  GET  /admin/anuncios                    → lista/filtra anúncios coletados
  GET  /admin/dashboard                   → dashboard com recortes dos dados
  GET  /admin/calculadora                 → calculadora de média por modelo
  GET  /admin/api/status                  → status do banco + conectores
  GET  /admin/api/anuncios                → dados paginados de /admin/anuncios
  GET  /admin/api/marca-modelo            → todos os pares (marca, modelo) distintos, sem cascata
  GET  /admin/api/media-modelo            → estatísticas de preço de um par (?marca=&modelo=&versao=)
  GET  /admin/api/dashboard               → agregados pro dashboard (?fonte=&marca=&modelo=&ano=)
  POST /admin/api/coletar                 → dispara coleta assíncrona de uma fonte
  GET  /admin/api/coletar-status/<id>     → status de uma coleta em andamento
"""
from __future__ import annotations

import importlib
import logging
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, send_from_directory

# Garante que o diretório raiz do projeto está no path
sys.path.insert(0, str(Path(__file__).parent))

# Carrega o .env do projeto (DATABASE_URL, DATAIMPULSE_*) antes do init_db()
# abaixo. Variáveis já definidas no ambiente (ex.: pelo iniciar_app.bat) têm
# precedência — load_dotenv não sobrescreve.
load_dotenv(Path(__file__).parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.persistence import (
    adicionar_ao_catalogo,
    corrigir_marca_modelo,
    excluir_marca_modelo,
    get_dashboard_stats,
    get_db_stats,
    get_media_modelo,
    init_db,
    listar_anuncios,
    listar_anuncios_a_verificar,
    listar_anuncios_do_par,
    listar_marca_modelo_pares,
    upsert_anuncios,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Armazena tarefas de coleta assíncronas em memória.
# Chave: task_id (UUID). Valor: dict com status, metricas, etc.
_tasks: dict[str, dict[str, Any]] = {}
_tasks_lock = threading.Lock()

app = Flask(__name__, static_folder="static")

# Mapa de todos os conectores disponíveis para o painel admin
CONNECTOR_MODULES: dict[str, str] = {
    "olx":                    "src.connectors.olx",
    "maxicar":                "src.connectors.maxicar",
    "superantigo":            "src.connectors.superantigo",
    "ateliedocarro":          "src.connectors.ateliedocarro",
    "ggsveiculosantigos":     "src.connectors.ggsveiculosantigos",
    "pastorecc":              "src.connectors.pastorecc",
    "jsautosantigos":         "src.connectors.jsautosantigos",
    "franzveiculosantigos":   "src.connectors.franzveiculosantigos",
    "gustavobrasil":          "src.connectors.gustavobrasil",
    "abcclassificados":       "src.connectors.abcclassificados",
    "salvajoli":              "src.connectors.salvajoli",
    "miguelveiculosjf":       "src.connectors.miguelveiculosjf",
    "interclassicos":         "src.connectors.interclassicos",
    "classicospremium":       "src.connectors.classicospremium",
    "brunelliveiculosantigos":"src.connectors.brunelliveiculosantigos",
    "thegarage":              "src.connectors.thegarage",
    "socarrao":               "src.connectors.socarrao",
    "lartdelautomobile":      "src.connectors.lartdelautomobile",
    "webmotors":              "src.connectors.webmotors",
    "mercadolivre":           "src.connectors.mercadolivre",
    # Novas fontes (2026-06-24)
    "classiccarbr":           "src.connectors.classiccarbr",
    "reginaldodecampinas":    "src.connectors.reginaldodecampinas",
    "carangoslegais":         "src.connectors.carangoslegais",
    "armazemdovovo":          "src.connectors.armazemdovovo",
    "eduardoveiculosantigos": "src.connectors.eduardoveiculosantigos",
    "estacaoraridades":       "src.connectors.estacaoraridades",
    # Novas fontes (2026-06-24 — lote 2)
    "berekclassicos":         "src.connectors.berekclassicos",
    "cia66motorsports":       "src.connectors.cia66motorsports",
    "escuderiacoqueiro":      "src.connectors.escuderiacoqueiro",
    "poaparts":               "src.connectors.poaparts",
    "ggworld":                "src.connectors.ggworld",
    # Novas fontes (2026-07-23)
    "icarros":                "src.connectors.icarros",
}

# Fontes bloqueadas ou sem listing de preços (checagem geral 2026-07-09).
# Mantidas no mapa para registro; puladas no "Coletar todos".
FONTES_INATIVAS: set[str] = set()

# Garante que o banco de histórico existe
init_db()
logger.info("Banco de histórico inicializado")


# ──────────────────────────────────────────────────────
# Rotas
# ──────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect("/admin")


# ──────────────────────────────────────────────────────
# Páginas HTML
# ──────────────────────────────────────────────────────

@app.route("/admin")
def admin():
    return send_from_directory(".", "admin.html")


@app.route("/admin/anuncios")
def admin_anuncios():
    return send_from_directory(".", "anuncios.html")


@app.route("/admin/dashboard")
def admin_dashboard():
    return send_from_directory(".", "dashboard.html")


@app.route("/admin/calculadora")
def admin_calculadora():
    return send_from_directory(".", "calculadora.html")


# ──────────────────────────────────────────────────────
# Admin API
# ──────────────────────────────────────────────────────

# "Sem versão informada" é um recorte legítimo (em muitos modelos é o maior
# grupo), e string vazia na query string não distingue "não filtrar" de
# "filtrar pelos sem versão" — daí o sentinela explícito na camada web. A
# persistência usa a convenção do módulo: None = todas, "" = sem versão.
VERSAO_SEM = "__sem__"


def _arg_versao() -> str | None:
    """Lê o filtro de versão da query string, traduzindo o sentinela."""
    valor = request.args.get("versao", "").strip()
    if not valor:
        return None
    return "" if valor == VERSAO_SEM else valor


def _arg_geracao() -> str | None:
    """
    Idem para o filtro de geração, que ganhou campo próprio na auditoria de
    2026-08-04 (antes vinha grudado na versão: "GERACAO I CL").
    """
    valor = request.args.get("geracao", "").strip()
    if not valor:
        return None
    return "" if valor == VERSAO_SEM else valor


@app.route("/admin/api/status")
def admin_status():
    try:
        stats = get_db_stats()
        stats["connectors"] = [
            {"nome": f, "ativo": f not in FONTES_INATIVAS}
            for f in sorted(CONNECTOR_MODULES.keys())
        ]
        return jsonify(stats)
    except Exception as exc:
        logger.warning("admin_status erro: %s", exc)
        return jsonify({"erro": str(exc), "total_anuncios": 0, "por_fonte": [],
                        "connectors": [
                            {"nome": f, "ativo": f not in FONTES_INATIVAS}
                            for f in sorted(CONNECTOR_MODULES.keys())
                        ]}), 500


@app.route("/admin/api/anuncios")
def admin_api_anuncios():
    fonte     = request.args.get("fonte",     "").strip() or None
    marca     = request.args.get("marca",     "").strip() or None
    modelo    = request.args.get("modelo",    "").strip() or None
    q         = request.args.get("q",         "").strip() or None
    order_by  = request.args.get("order_by",  "ultima_vista").strip()
    order_dir = request.args.get("order_dir", "desc").strip()
    try:
        page      = max(1, int(request.args.get("page", 1)))
        page_size = min(200, max(10, int(request.args.get("page_size", 50))))
        ano_raw   = request.args.get("ano", "").strip()
        ano       = int(ano_raw) if ano_raw else None
    except ValueError:
        return jsonify({"erro": "Parâmetros inválidos"}), 400

    try:
        result = listar_anuncios(
            fonte=fonte, marca=marca, modelo=modelo,
            ano=ano, versao=_arg_versao(), q=q,
            order_by=order_by, order_dir=order_dir,
            page=page, page_size=page_size,
        )
        return jsonify(result)
    except Exception as exc:
        logger.error("admin_api_anuncios erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/marca-modelo")
def admin_api_marca_modelo():
    try:
        return jsonify({"pares": listar_marca_modelo_pares()})
    except Exception as exc:
        logger.error("admin_api_marca_modelo erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/anuncios-a-verificar")
def admin_api_anuncios_a_verificar():
    """Quarentena: pares (marca, modelo) fora do catálogo consagrado."""
    try:
        return jsonify(listar_anuncios_a_verificar())
    except Exception as exc:
        logger.error("admin_api_anuncios_a_verificar erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/corrigir-marca-modelo", methods=["POST"])
def admin_api_corrigir_marca_modelo():
    """Reatribui um par (marca, modelo) da quarentena pro par corrigido."""
    data = request.get_json(silent=True) or {}
    marca       = (data.get("marca")       or "").strip()
    modelo      = (data.get("modelo")      or "").strip()
    marca_nova  = (data.get("marca_nova")  or "").strip()
    modelo_nova = (data.get("modelo_nova") or "").strip()
    if not marca or not marca_nova:
        return jsonify({"erro": "Marca atual e marca nova são obrigatórias."}), 400
    try:
        res = corrigir_marca_modelo(marca, modelo, marca_nova, modelo_nova)
        logger.info(
            "corrigir-marca-modelo: %r/%r -> %r/%r (%d anúncios, no_catalogo=%s)",
            marca, modelo, res["marca"], res["modelo"], res["atualizados"], res["no_catalogo"],
        )
        return jsonify({"ok": True, **res})
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        logger.error("admin_api_corrigir_marca_modelo erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/media-modelo")
def admin_api_media_modelo():
    """Estatísticas de preço (média, mediana, faixa) de um par marca+modelo — calculadora de média."""
    marca  = request.args.get("marca",  "").strip()
    modelo = request.args.get("modelo", "").strip()
    if not marca or not modelo:
        return jsonify({"erro": "Marca e modelo são obrigatórios."}), 400
    try:
        return jsonify(get_media_modelo(marca, modelo, _arg_versao(), _arg_geracao()))
    except Exception as exc:
        logger.error("admin_api_media_modelo erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/anuncios-do-par")
def admin_api_anuncios_do_par():
    """
    Anúncios de um par (marca, modelo) exato — inspeção de item da quarentena
    e detalhe das linhas da calculadora (daí os recortes versão/geração/ano/
    fonte).
    """
    marca  = request.args.get("marca",  "").strip()
    modelo = request.args.get("modelo", "").strip()
    fonte  = request.args.get("fonte",  "").strip() or None
    if not marca:
        return jsonify({"erro": "Marca é obrigatória."}), 400
    try:
        ano_raw = request.args.get("ano", "").strip()
        ano = int(ano_raw) if ano_raw else None
    except ValueError:
        return jsonify({"erro": "Parâmetros inválidos"}), 400
    try:
        rows = listar_anuncios_do_par(
            marca, modelo, versao=_arg_versao(), ano=ano, fonte=fonte,
            geracao=_arg_geracao(),
        )
        return jsonify({"rows": rows})
    except Exception as exc:
        logger.error("admin_api_anuncios_do_par erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/excluir-marca-modelo", methods=["POST"])
def admin_api_excluir_marca_modelo():
    """Apaga todos os anúncios de um par (marca, modelo) que não pertence ao acervo."""
    data = request.get_json(silent=True) or {}
    marca  = (data.get("marca")  or "").strip()
    modelo = (data.get("modelo") or "").strip()
    if not marca:
        return jsonify({"erro": "Marca é obrigatória."}), 400
    try:
        res = excluir_marca_modelo(marca, modelo)
        logger.info("excluir-marca-modelo: %r/%r (%d anúncios apagados)", marca, modelo, res["excluidos"])
        return jsonify({"ok": True, **res})
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        logger.error("admin_api_excluir_marca_modelo erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/adicionar-ao-catalogo", methods=["POST"])
def admin_api_adicionar_ao_catalogo():
    """Cadastra um par (marca, modelo) já correto no catálogo (suplemento manual)."""
    data = request.get_json(silent=True) or {}
    marca  = (data.get("marca")  or "").strip()
    modelo = (data.get("modelo") or "").strip()
    if not marca or not modelo:
        return jsonify({"erro": "Marca e modelo são obrigatórios."}), 400
    try:
        res = adicionar_ao_catalogo(marca, modelo)
        logger.info(
            "adicionar-ao-catalogo: %r/%r (ja_existia=%s, anos=%s-%s)",
            res["marca"], res["modelo"], res["ja_existia"], res["ano_min"], res["ano_max"],
        )
        return jsonify({"ok": True, **res})
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        logger.error("admin_api_adicionar_ao_catalogo erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/dashboard")
def admin_api_dashboard():
    fonte  = request.args.get("fonte",  "").strip() or None
    marca  = request.args.get("marca",  "").strip() or None
    modelo = request.args.get("modelo", "").strip() or None
    ano_raw = request.args.get("ano", "").strip()
    try:
        ano = int(ano_raw) if ano_raw else None
    except ValueError:
        return jsonify({"erro": "Parâmetro ano inválido"}), 400

    try:
        return jsonify(get_dashboard_stats(fonte=fonte, marca=marca, modelo=modelo, ano=ano))
    except Exception as exc:
        logger.error("admin_api_dashboard erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/coletar", methods=["POST"])
def admin_coletar():
    """
    Inicia coleta em background e retorna task_id imediatamente.
    O cliente deve consultar /admin/api/coletar-status/<task_id> para obter o resultado.
    """
    body = request.get_json(silent=True) or {}
    fonte = (body.get("fonte") or "").strip()

    if not fonte or fonte not in CONNECTOR_MODULES:
        return jsonify({"erro": f"Fonte desconhecida: '{fonte}'"}), 400

    task_id = str(uuid.uuid4())
    with _tasks_lock:
        _tasks[task_id] = {"status": "running", "fonte": fonte}

    def _run():
        try:
            mod = importlib.import_module(CONNECTOR_MODULES[fonte])
            anuncios_coletados, metricas = mod.coletar_completo()
            resultado_db = upsert_anuncios(anuncios_coletados)
            logger.info("admin_coletar %s concluído: %s → %s", fonte, metricas, resultado_db)
            try:
                fazer_backup()
            except Exception as exc:
                logger.warning("admin_coletar %s: falha ao gerar backup pós-coleta: %s", fonte, exc)
            with _tasks_lock:
                _tasks[task_id] = {
                    "status": "done",
                    "fonte": fonte,
                    "metricas": metricas,
                    "resultado": resultado_db,
                }
        except Exception as exc:
            logger.error("admin_coletar %s erro: %s", fonte, exc, exc_info=True)
            with _tasks_lock:
                _tasks[task_id] = {
                    "status": "error",
                    "fonte": fonte,
                    "erro": str(exc),
                }

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"task_id": task_id, "status": "running"})


@app.route("/admin/api/coletar-status/<task_id>")
def admin_coletar_status(task_id):
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        return jsonify({"erro": "Tarefa não encontrada"}), 404
    return jsonify(task)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
