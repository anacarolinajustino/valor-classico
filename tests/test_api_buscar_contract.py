"""
Testes de contrato do endpoint /api/buscar para consistência entre tabela e sinal de leilão.
"""
from __future__ import annotations

from src.pipeline.schema import Anuncio


def _mk_anuncio(
    *,
    titulo: str,
    preco: float,
    ano: int | None,
    fonte: str,
    url: str,
) -> Anuncio:
    return Anuncio(
        titulo=titulo,
        preco=preco,
        marca="FORD",
        modelo="GALAXIE",
        ano=ano,
        versao=None,
        url=url,
        fonte=fonte,
        data_coleta="2026-06-12",
    )


def test_buscar_aplica_filtro_ano_ao_sinal_leilao_e_mantem_metadata(client, monkeypatch):
    classificados = [
        _mk_anuncio(
            titulo="FORD GALAXIE 1968",
            preco=120000.0,
            ano=1968,
            fonte="maxicar",
            url="https://maxicar.com/a",
        ),
        _mk_anuncio(
            titulo="FORD GALAXIE 1970",
            preco=130000.0,
            ano=1970,
            fonte="superantigo",
            url="https://superantigo.com/b",
        ),
    ]
    leilao = [
        _mk_anuncio(
            titulo="FORD/GALAXIE 500 - 1968/1968",
            preco=70000.0,
            ano=1968,
            fonte="circuitodeleiloes",
            url="https://picelli.com/1968",
        ),
        _mk_anuncio(
            titulo="FORD/GALAXIE 500 - 1972/1972",
            preco=75000.0,
            ano=1972,
            fonte="circuitodeleiloes",
            url="https://picelli.com/1972",
        ),
    ]

    monkeypatch.setattr("app.maxicar_buscar", lambda *args, **kwargs: classificados)
    monkeypatch.setattr("app.superantigo_buscar", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.ateliedocarro_buscar", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.circuitodeleiloes_buscar", lambda *args, **kwargs: leilao)

    res = client.get("/api/buscar?marca=ford&modelo=galaxie&ano=1968")
    assert res.status_code == 200
    body = res.get_json()

    assert body["consulta"]["ano"] == 1968
    assert body["sinal_leilao"]["considerado"] is True
    assert body["sinal_leilao"]["filtro_aplicado"]["ano"] == 1968
    assert body["sinal_leilao"]["itens_excluidos_por_filtro"] == 1

    vendas = body["sinal_leilao"]["vendas"]
    assert len(vendas) == 1
    assert all(v["ano"] == 1968 for v in vendas)

    candidatos = body["candidatos"]
    assert candidatos, "Esperado payload de candidatos para inspeção de elegibilidade"

    cands_1968 = [c for c in candidatos if c["url"] == "https://picelli.com/1968"]
    cands_1972 = [c for c in candidatos if c["url"] == "https://picelli.com/1972"]
    assert cands_1968 and cands_1968[0]["match_status"] == "signal_only"
    assert cands_1968[0]["has_auction_signal"] is True
    assert cands_1968[0]["auction_signal_reason"] == "auction_signal_secondary"

    assert cands_1972 and cands_1972[0]["match_status"] == "excluded_by_filters"
    assert "year_mismatch" in cands_1972[0]["filter_reasons"]


def test_buscar_sem_ano_permite_sinal_leilao_e_registra_status(client, monkeypatch):
    classificados = [
        _mk_anuncio(
            titulo="FORD GALAXIE 1968",
            preco=120000.0,
            ano=1968,
            fonte="maxicar",
            url="https://maxicar.com/a",
        ),
    ]
    leilao = [
        _mk_anuncio(
            titulo="FORD/GALAXIE 500 - 1968/1968",
            preco=70000.0,
            ano=1968,
            fonte="circuitodeleiloes",
            url="https://picelli.com/1968",
        )
    ]

    monkeypatch.setattr("app.maxicar_buscar", lambda *args, **kwargs: classificados)
    monkeypatch.setattr("app.superantigo_buscar", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.ateliedocarro_buscar", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.circuitodeleiloes_buscar", lambda *args, **kwargs: leilao)

    res = client.get("/api/buscar?marca=ford&modelo=galaxie")
    assert res.status_code == 200
    body = res.get_json()

    assert body["sinal_leilao"]["considerado"] is True
    assert body["sinal_leilao"]["filtro_aplicado"]["ano"] is None
    assert body["fontes_ativas"]
    assert "Circuito de Leilões" in body["fontes_ativas"]

    cand = next(c for c in body["candidatos"] if c["url"] == "https://picelli.com/1968")
    assert cand["match_status"] == "signal_only"
    assert cand["has_auction_signal"] is True


def test_buscar_ano_com_lote_sem_ano_marca_como_signal_only_missing_year(client, monkeypatch):
    classificados = []
    leilao = [
        _mk_anuncio(
            titulo="LOTE ANTIGO SEM ANO",
            preco=50000.0,
            ano=None,
            fonte="circuitodeleiloes",
            url="https://picelli.com/sem-ano",
        )
    ]

    monkeypatch.setattr("app.maxicar_buscar", lambda *args, **kwargs: classificados)
    monkeypatch.setattr("app.superantigo_buscar", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.ateliedocarro_buscar", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.circuitodeleiloes_buscar", lambda *args, **kwargs: leilao)

    res = client.get("/api/buscar?marca=ford&modelo=galaxie&ano=1968")
    assert res.status_code == 200
    body = res.get_json()

    assert body["sinal_leilao"]["considerado"] is False
    assert body["sinal_leilao"]["itens_sem_ano"] == 1

    cand = next(c for c in body["candidatos"] if c["url"] == "https://picelli.com/sem-ano")
    assert cand["match_status"] == "signal_only"
    assert cand["has_auction_signal"] is True
    assert cand["auction_signal_reason"] == "missing_year_outside_filter"
