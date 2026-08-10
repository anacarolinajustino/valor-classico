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
  GET  /admin/api/versoes-do-par          → versões (com geração) de um par (?marca=&modelo=)
  GET  /admin/api/exportar                → baixa snapshot CSV da base (?tipo=anuncios|resumo)
  GET  /admin/api/exportar-pendencias     → baixa uma aba de pendências em CSV (?aba=)
  GET  /admin/api/media-modelo            → estatísticas de preço de um par (?marca=&modelo=&versao=)
  GET  /admin/api/dashboard               → agregados pro dashboard (?fonte=&marca=&modelo=&versao=&ano=&min_anuncios=)
  POST /admin/api/coletar                 → dispara coleta assíncrona de uma fonte
  GET  /admin/api/coletar-status/<id>     → status de uma coleta em andamento
"""
from __future__ import annotations

import csv
import importlib
import io
import logging
import sys
import threading
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, redirect, request, send_from_directory

# Garante que o diretório raiz do projeto está no path
sys.path.insert(0, str(Path(__file__).parent))

# Carrega o .env do projeto (DATABASE_URL, DATAIMPULSE_*) antes do init_db()
# abaixo. Variáveis já definidas no ambiente (ex.: pelo iniciar_app.bat) têm
# precedência — load_dotenv não sobrescreve.
load_dotenv(Path(__file__).parent / ".env")

from src.catalog.externo import registrar_decisao_alias
from src.pipeline.backup import fazer_backup
from src.pipeline.pendencias import (
    ABA_ARQUIVO,
    ABAS_EXPORTAVEIS,
    dispensar as dispensar_pendencia,
    exportar_aba,
    listar_aliases_pendentes,
    listar_pendencias,
    listar_sem_versao,
    listar_versoes_pendentes,
    restaurar as restaurar_pendencia,
)
from src.pipeline.persistence import (
    DESTINOS_VERSAO,
    adicionar_ao_catalogo,
    adicionar_versao_ao_catalogo,
    corrigir_marca_modelo,
    limpar_versao_do_par,
    reclassificar_versao,
    excluir_marca_modelo,
    get_dashboard_stats,
    get_db_stats,
    get_media_modelo,
    init_db,
    listar_anuncios,
    listar_anuncios_a_verificar,
    listar_anuncios_do_par,
    listar_marca_modelo_pares,
    listar_versoes_do_par,
    upsert_anuncios,
    COLUNAS_EXPORT_ANUNCIOS,
    COLUNAS_EXPORT_RESUMO,
    exportar_anuncios,
    exportar_resumo,
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


@app.route("/admin/pendencias")
def admin_pendencias():
    return send_from_directory(".", "pendencias.html")


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
            geracao=_arg_geracao(),
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


# ── Exportação CSV (série histórica) ──────────────────────────────────────
#
# O CSV sai no padrão brasileiro — separador ";" e vírgula decimal — porque o
# destino é abrir no Excel em português com um duplo clique. Com "," de
# separador o Excel pt-BR joga a linha inteira numa coluna só. O BOM
# (utf-8-sig) é o que faz o Excel reconhecer o acento.

def _fmt_csv(valor: Any) -> str:
    """Valor de célula no padrão BR: vazio pra None, vírgula decimal."""
    if valor is None:
        return ""
    if isinstance(valor, float):
        # Preço não tem centavo relevante aqui, mas mantém 2 casas pra não
        # perder precisão de média/mediana.
        return f"{valor:.2f}".replace(".", ",")
    return str(valor)


def _csv_streaming(linhas, colunas: list[str], nome_base: str) -> Response:
    """
    Monta a resposta CSV escrevendo conforme lê do banco (sem materializar o
    arquivo inteiro em memória).
    """
    hoje = date.today().isoformat()

    def drenar(buffer: io.StringIO) -> str:
        """Tira o que o writer acabou de escrever e zera o buffer."""
        conteudo = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return conteudo

    def gerar():
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
        yield "﻿"   # BOM: faz o Excel reconhecer o UTF-8
        writer.writerow(colunas)
        yield drenar(buffer)
        for linha in linhas:
            writer.writerow([_fmt_csv(linha.get(c)) for c in colunas])
            yield drenar(buffer)

    nome = f"{nome_base}_{hoje}.csv"
    return Response(
        gerar(),
        mimetype="text/csv",   # o Flask acrescenta o charset
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@app.route("/admin/api/exportar")
def admin_api_exportar():
    """
    Baixa um snapshot datado da base em CSV, pra empilhar fora do sistema e
    formar a série histórica (o banco guarda só o estado atual — ver o
    comentário em `persistence.exportar_anuncios`).

    ?tipo=anuncios (padrão) — um anúncio por linha, dado granular
    ?tipo=resumo            — uma linha por (marca, modelo, versão, geração,
                              ano) com as estatísticas de preço
    """
    tipo = request.args.get("tipo", "anuncios").strip().lower()
    if tipo not in ("anuncios", "resumo"):
        return jsonify({"erro": "tipo deve ser 'anuncios' ou 'resumo'."}), 400
    try:
        if tipo == "resumo":
            return _csv_streaming(
                exportar_resumo(), COLUNAS_EXPORT_RESUMO, "valor-classico_resumo"
            )
        return _csv_streaming(
            exportar_anuncios(), COLUNAS_EXPORT_ANUNCIOS, "valor-classico_anuncios"
        )
    except Exception as exc:
        logger.error("admin_api_exportar erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/versoes-do-par")
def admin_api_versoes_do_par():
    """
    Versões (com geração) de um par marca/modelo — o detalhe consultável da
    lista "Todas as marcas e modelos", um nível abaixo do par.
    """
    marca  = request.args.get("marca",  "").strip()
    modelo = request.args.get("modelo", "").strip()
    if not marca:
        return jsonify({"erro": "Marca é obrigatória."}), 400
    try:
        return jsonify({"rows": listar_versoes_do_par(marca, modelo)})
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        logger.error("admin_api_versoes_do_par erro: %s", exc, exc_info=True)
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


def _arg_ano_opcional(data: dict, chave: str) -> Optional[int]:
    """Lê um ano opcional do corpo JSON; '' e ausente viram None."""
    bruto = data.get(chave)
    if bruto in (None, ""):
        return None
    try:
        return int(bruto)
    except (TypeError, ValueError):
        raise ValueError(f"{chave} deve ser um ano válido.")


@app.route("/admin/api/adicionar-ao-catalogo", methods=["POST"])
def admin_api_adicionar_ao_catalogo():
    """
    Cadastra um par (marca, modelo) já correto no catálogo (suplemento manual).

    `ano_min`/`ano_max` são opcionais: a tela de pendências manda a faixa que a
    fonte externa conhece; sem eles, a faixa sai dos próprios anúncios do par.
    """
    data = request.get_json(silent=True) or {}
    marca  = (data.get("marca")  or "").strip()
    modelo = (data.get("modelo") or "").strip()
    if not marca or not modelo:
        return jsonify({"erro": "Marca e modelo são obrigatórios."}), 400
    try:
        res = adicionar_ao_catalogo(
            marca, modelo,
            _arg_ano_opcional(data, "ano_min"),
            _arg_ano_opcional(data, "ano_max"),
        )
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


@app.route("/admin/api/pendencias")
def admin_api_pendencias():
    """
    Fila de decisões manuais: pares fora do catálogo, já classificados pela
    evidência das fontes externas (ver src/pipeline/pendencias.py).
    """
    incluir = request.args.get("incluir_dispensadas", "").strip() == "1"
    try:
        return jsonify(listar_pendencias(incluir_dispensadas=incluir))
    except Exception as exc:
        logger.error("admin_api_pendencias erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/dispensar-pendencia", methods=["POST"])
def admin_api_dispensar_pendencia():
    """Tira um par da fila sem alterar anúncio nem catálogo (ou devolve, com restaurar=1)."""
    data = request.get_json(silent=True) or {}
    marca  = (data.get("marca")  or "").strip()
    modelo = (data.get("modelo") or "").strip()
    motivo = (data.get("motivo") or "").strip()
    try:
        if data.get("restaurar"):
            res = restaurar_pendencia(marca, modelo)
            logger.info("restaurar-pendencia: %r/%r", marca, modelo)
        else:
            res = dispensar_pendencia(marca, modelo, motivo)
            logger.info("dispensar-pendencia: %r/%r (motivo=%r)", marca, modelo, motivo)
        return jsonify({"ok": True, **res})
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        logger.error("admin_api_dispensar_pendencia erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/versoes-pendentes")
def admin_api_versoes_pendentes():
    """Versões do banco que o vocabulário de trim do catálogo não reconhece."""
    try:
        return jsonify(listar_versoes_pendentes())
    except Exception as exc:
        logger.error("admin_api_versoes_pendentes erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/decidir-versao", methods=["POST"])
def admin_api_decidir_versao():
    """
    Decide uma versão pendente. `acao`:
      manter     — é trim real; cadastra no suplemento de versão
      limpar     — não é versão nenhuma; apaga o campo nos anúncios do par
      geracao    \
      motor       > o valor está certo, o campo é que estava errado
      obs        /
      agregada   — o título enumerava a linha inteira; grava a sentinela
      corrigir   — o valor precisa de ajuste (exige `valor`)

    Os quatro últimos vêm de 2026-08-10: a fila só tinha "é trim"/"não é
    nada", e metade das decisões reais não cabia nessas duas — ver
    `persistence.DESTINOS_VERSAO`.
    """
    data = request.get_json(silent=True) or {}
    marca  = (data.get("marca")  or "").strip()
    modelo = (data.get("modelo") or "").strip()
    versao = (data.get("versao") or "").strip()
    acao   = (data.get("acao")   or "").strip().lower()
    valor  = (data.get("valor")  or "").strip()
    if not marca or not versao:
        return jsonify({"erro": "Marca e versão são obrigatórias."}), 400
    try:
        if acao == "manter":
            res = adicionar_versao_ao_catalogo(marca, modelo, versao)
            logger.info("decidir-versao manter: %r/%r/%r (ja_existia=%s)",
                        marca, modelo, versao, res["ja_existia"])
        elif acao == "limpar":
            res = limpar_versao_do_par(marca, modelo, versao)
            logger.info("decidir-versao limpar: %r/%r/%r (%d anúncios)",
                        marca, modelo, versao, res["atualizados"])
        elif acao in DESTINOS_VERSAO:
            res = reclassificar_versao(marca, modelo, versao, acao, valor)
            logger.info("decidir-versao %s: %r/%r/%r -> %r (%d anúncios, %d conflitos)",
                        acao, marca, modelo, versao, valor or acao,
                        res["atualizados"], res["conflitos"])
        else:
            return jsonify({
                "erro": "Ação deve ser 'manter', 'limpar' ou uma de: "
                        + ", ".join(DESTINOS_VERSAO)
            }), 400
        return jsonify({"ok": True, "acao": acao, **res})
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        logger.error("admin_api_decidir_versao erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/sem-versao")
def admin_api_sem_versao():
    """
    Anúncios sem versão, agrupados por marca/modelo e classificados entre o
    que é bug de extração e o que é limite da fonte. Aba diagnóstica — ver
    `listar_sem_versao`.
    """
    try:
        return jsonify(listar_sem_versao())
    except Exception as exc:
        logger.error("admin_api_sem_versao erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/aliases-pendentes")
def admin_api_aliases_pendentes():
    """Aliases PT-BR <-> EN de regra fuzzy que ainda precisam de conferência."""
    incluir = request.args.get("incluir_decididos", "").strip() == "1"
    try:
        return jsonify(listar_aliases_pendentes(incluir_decididos=incluir))
    except Exception as exc:
        logger.error("admin_api_aliases_pendentes erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/decidir-alias", methods=["POST"])
def admin_api_decidir_alias():
    """Aprova ou rejeita um alias. Rejeitado deixa de valer como evidência externa."""
    data = request.get_json(silent=True) or {}
    marca  = (data.get("marca")       or "").strip()
    ptbr   = (data.get("modelo_ptbr") or "").strip()
    decisao = (data.get("decisao")    or "").strip().lower()
    if not marca or not ptbr:
        return jsonify({"erro": "Marca e modelo são obrigatórios."}), 400
    try:
        registrar_decisao_alias(marca, ptbr, decisao)
        logger.info("decidir-alias: %r/%r -> %s", marca, ptbr, decisao)
        return jsonify({"ok": True, "marca": marca, "modelo_ptbr": ptbr, "decisao": decisao})
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        logger.error("admin_api_decidir_alias erro: %s", exc, exc_info=True)
        return jsonify({"erro": str(exc)}), 500


@app.route("/admin/api/exportar-pendencias")
def admin_api_exportar_pendencias():
    """
    Baixa uma aba da página de pendências em CSV, no mesmo padrão brasileiro
    da exportação da base.

    Serve pra triar fora do painel — abrir no Excel, marcar o que já foi
    resolvido, dividir a fila com outra pessoa — e pra guardar o retrato de
    uma auditoria antes de começar a mexer.

    ?aba=  corrigir_nome | confirmado | sem_evidencia | versao | sem_versao | alias

    Os filtros da tela vão junto (`busca`, `sugestao`, `so_recuperavel`,
    `incluir_dispensadas`), então o arquivo reflete o que está à vista. O que
    NÃO vai junto é o corte de exibição das listas grandes: o CSV sai
    completo (ver o comentário em `pendencias.exportar_aba`).
    """
    aba = request.args.get("aba", "").strip()
    if aba not in ABAS_EXPORTAVEIS:
        return jsonify({
            "erro": f"aba deve ser uma de: {', '.join(ABAS_EXPORTAVEIS)}."
        }), 400
    try:
        colunas, linhas = exportar_aba(
            aba,
            busca=request.args.get("busca", "").strip(),
            sugestao=request.args.get("sugestao", "").strip(),
            so_recuperavel=request.args.get("so_recuperavel", "").strip() == "1",
            incluir_dispensadas=request.args.get("incluir_dispensadas", "").strip() == "1",
        )
        logger.info("exportar-pendencias: aba=%s (%d linhas)", aba, len(linhas))
        resp = _csv_streaming(linhas, colunas, ABA_ARQUIVO[aba])
        # A tela confirma a contagem ao lado do botão: é como a usuária vê que
        # o arquivo saiu inteiro, e não com o corte de exibição da lista.
        resp.headers["X-Total-Linhas"] = str(len(linhas))
        return resp
    except Exception as exc:
        logger.error("admin_api_exportar_pendencias erro: %s", exc, exc_info=True)
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

    min_raw = request.args.get("min_anuncios", "").strip()
    try:
        min_anuncios = int(min_raw) if min_raw else None
    except ValueError:
        return jsonify({"erro": "Parâmetro min_anuncios inválido"}), 400

    try:
        return jsonify(get_dashboard_stats(
            fonte=fonte, marca=marca, modelo=modelo, ano=ano, versao=_arg_versao(),
            min_anuncios=min_anuncios,
        ))
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
