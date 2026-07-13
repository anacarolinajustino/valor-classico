"""
Valor Clássico — painel de coleta e administração.

Ferramenta interna: painel de status das fontes, disparo de coleta e
listagem dos anúncios coletados. O site público (busca por marca/modelo/ano)
é um projeto separado (`valor-classico-web`).

Endpoints:
  GET  /                                  → redireciona pro painel (/admin)
  GET  /admin                             → painel de status e coleta
  GET  /admin/anuncios                    → lista/filtra anúncios coletados
  GET  /admin/api/status                  → status do banco + conectores
  GET  /admin/api/anuncios                → dados paginados de /admin/anuncios
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

from flask import Flask, jsonify, redirect, request, send_from_directory

# Garante que o diretório raiz do projeto está no path
sys.path.insert(0, str(Path(__file__).parent))

from src.pipeline.backup import fazer_backup
from src.pipeline.persistence import (
    get_db_stats,
    init_db,
    listar_anuncios,
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


# ──────────────────────────────────────────────────────
# Admin API
# ──────────────────────────────────────────────────────

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
            fonte=fonte, marca=marca, modelo=modelo, ano=ano, q=q,
            order_by=order_by, order_dir=order_dir,
            page=page, page_size=page_size,
        )
        return jsonify(result)
    except Exception as exc:
        logger.error("admin_api_anuncios erro: %s", exc, exc_info=True)
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
