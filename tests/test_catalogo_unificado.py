"""
Testes do catálogo unificado (src/catalog/unificado.py).

As sete fontes reais somam 40 mil linhas de CSV e uma consulta ao banco — o
que se testa aqui é a UNIFICAÇÃO e a curadoria, não a leitura dos arquivos
de produção. Por isso a fixture monta um data/ de mentira com quatro linhas
por fonte: cabe na cabeça, e um caso a mais é uma linha a mais.
"""
import csv
from pathlib import Path

import pytest

from src.catalog import unificado as u


def _csv(caminho: Path, colunas: list[str], linhas: list[dict]) -> None:
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=colunas)
        w.writeheader()
        w.writerows(linhas)


@pytest.fixture()
def catalogo(tmp_path, monkeypatch):
    """
    Um data/ de mentira + banco de mentira. Devolve o módulo já isolado.

    O FUSCA aparece em quatro fontes com faixas diferentes de propósito: é o
    caso que prova a união dos anos e a preservação da faixa de cada uma.
    """
    monkeypatch.setattr(u, "DATA", tmp_path)
    monkeypatch.setattr(u, "CATALOGO_DEFINITIVO_CSV", tmp_path / "catalogo_definitivo.csv")

    _csv(tmp_path / "base_marcamodelo.csv",
         ["nome_marca", "nome_modelo", "ano_modelo", "nome_versao", "data_coleta"],
         [
             {"nome_marca": "Volkswagen", "nome_modelo": "Fusca", "ano_modelo": "1970",
              "nome_versao": "1300", "data_coleta": ""},
             {"nome_marca": "Volkswagen", "nome_modelo": "Fusca", "ano_modelo": "1983",
              "nome_versao": "1300", "data_coleta": ""},
             # ano 0 é o "sem ano" da Webmotors: a linha vale, o ano não.
             {"nome_marca": "Ford", "nome_modelo": "Corcel", "ano_modelo": "0",
              "nome_versao": "GT", "data_coleta": ""},
         ])
    _csv(tmp_path / "base_dados_webmotors.csv",
         ["nome_marca", "nome_modelo", "ano_modelo", "nome_versao", "data_coleta"],
         [{"nome_marca": "Volkswagen", "nome_modelo": "Fusca", "ano_modelo": "1968",
           "nome_versao": "1300", "data_coleta": ""}])
    _csv(tmp_path / "base_marcamodelo_intl.csv",
         ["marca", "modelo", "ano_min", "ano_max", "anos_distintos", "versoes", "fonte"],
         [
             {"marca": "Volkswagen", "modelo": "Fusca", "ano_min": "1959",
              "ano_max": "1986", "anos_distintos": "", "versoes": "1300|1500",
              "fonte": "the-oldtimers.com"},
             {"marca": "Porsche", "modelo": "911", "ano_min": "1964",
              "ano_max": "1998", "anos_distintos": "", "versoes": "",
              "fonte": "classic.com"},
         ])
    _csv(tmp_path / "suplemento_manual.csv",
         ["marca", "modelo", "ano_min", "ano_max"],
         [{"marca": "Gurgel", "modelo": "XEF", "ano_min": "1980", "ano_max": "1990"}])
    _csv(tmp_path / "vocabulario_geracao_trim.csv",
         ["marca", "modelo", "geracoes", "trims", "carrocerias", "n_urls", "fonte"],
         [{"marca": "Volkswagen", "modelo": "Fusca", "geracoes": "",
           "trims": "1300|ITAMAR", "carrocerias": "", "n_urls": "3",
           "fonte": "classic.com"}])

    monkeypatch.setattr(u, "_do_suplemento_codigo",
                        lambda indice: u._registrar(indice, "PUMA", "GTB", "",
                                                    "suplemento_codigo", 1970, 1980))

    def banco_falso(indice):
        u._registrar(indice, "VOLKSWAGEN", "FUSCA", "1300", "anuncios", 1962, 1996, 120)
        u._registrar(indice, "VOLKSWAGEN", "BRASILIA", "", "anuncios", 1973, 1982, 40)

    monkeypatch.setattr(u, "_do_banco", banco_falso)

    u.invalidar_cache()
    yield u
    u.invalidar_cache()


def _linha(cat, marca, modelo, versao=""):
    d = cat.listar(por_pagina=500)
    for l in d["linhas"]:
        if (l["marca_origem"], l["modelo_origem"], l["versao_origem"]) == (marca, modelo, versao):
            return l
    return None


class TestUnificacao:
    def test_mesmo_trio_de_varias_fontes_vira_uma_linha(self, catalogo):
        l = _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")
        assert l is not None
        assert set(l["fontes"]) == {
            "anuncios", "webmotors", "webmotors_bruto", "internacional", "vocab_trim",
        }

    def test_faixa_e_a_uniao_das_fontes(self, catalogo):
        l = _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")
        # internacional começa em 1959, anúncios terminam em 1996
        assert l["ano_min"] == 1959
        assert l["ano_max"] == 1996

    def test_faixa_de_cada_fonte_viaja_junto(self, catalogo):
        """Quando duas discordam, quem tria precisa ver as duas."""
        l = _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")
        assert l["anos_por_fonte"]["anuncios"] == [1962, 1996]
        assert l["anos_por_fonte"]["internacional"] == [1959, 1986]
        assert l["anos_por_fonte"]["webmotors"] == [1970, 1983]

    def test_fonte_sem_anos_nao_estraga_a_faixa(self, catalogo):
        l = _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")
        assert l["anos_por_fonte"]["vocab_trim"] == [None, None]
        assert l["ano_min"] == 1959

    def test_ano_zero_da_webmotors_nao_vira_ano(self, catalogo):
        l = _linha(catalogo, "FORD", "CORCEL", "GT")
        assert l["ano_min"] is None and l["ano_max"] is None

    def test_versoes_do_estrangeiro_viram_linhas(self, catalogo):
        assert _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1500") is not None

    def test_fonte_sem_versao_cai_na_linha_do_modelo(self, catalogo):
        """Suplementos e o estrangeiro sem versões entram com versão vazia."""
        assert _linha(catalogo, "GURGEL", "XEF", "")["fontes"] == ["suplemento_manual"]
        assert _linha(catalogo, "PUMA", "GTB", "")["fontes"] == ["suplemento_codigo"]
        assert _linha(catalogo, "PORSCHE", "911", "")["fontes"] == ["internacional"]

    def test_normaliza_a_grafia_da_fonte(self, catalogo):
        """'Volkswagen' do CSV e 'VOLKSWAGEN' do banco são a mesma marca."""
        assert _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")["n_anuncios"] == 120

    def test_contagem_de_anuncios_so_do_banco(self, catalogo):
        assert _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1500")["n_anuncios"] == 0


class TestResumo:
    def test_contagens(self, catalogo):
        r = catalogo.resumo()
        assert r["total"] == len(catalogo.listar(por_pagina=500)["linhas"])
        assert r["por_situacao"]["pendente"] == r["total"]
        assert r["com_anuncios"] == 2      # FUSCA 1300 e BRASILIA
        assert r["por_fonte"]["anuncios"] == 2

    def test_uma_fonte_so(self, catalogo):
        r = catalogo.resumo()
        # BRASILIA, GURGEL, PUMA, PORSCHE, CORCEL, FUSCA 1500, FUSCA ITAMAR
        assert r["uma_fonte"] == 7


class TestFiltros:
    def test_por_marca(self, catalogo):
        d = catalogo.listar(marca="volkswagen")
        assert {l["marca"] for l in d["linhas"]} == {"VOLKSWAGEN"}

    def test_busca_pega_versao(self, catalogo):
        d = catalogo.listar(busca="itamar")
        assert [l["versao"] for l in d["linhas"]] == ["ITAMAR"]

    def test_por_fonte(self, catalogo):
        d = catalogo.listar(fonte="suplemento_manual")
        assert [(l["marca"], l["modelo"]) for l in d["linhas"]] == [("GURGEL", "XEF")]

    def test_so_com_anuncios(self, catalogo):
        d = catalogo.listar(so_com_anuncios=True)
        assert all(l["n_anuncios"] > 0 for l in d["linhas"])
        assert d["total"] == 2

    def test_apenas_uma_fonte(self, catalogo):
        d = catalogo.listar(apenas_uma_fonte=True)
        assert all(len(l["fontes"]) == 1 for l in d["linhas"])

    def test_ordem_relevancia_poe_o_maior_primeiro(self, catalogo):
        d = catalogo.listar(ordem="relevancia")
        assert d["linhas"][0]["n_anuncios"] == 120

    def test_paginacao(self, catalogo):
        p1 = catalogo.listar(pagina=1, por_pagina=2)
        p2 = catalogo.listar(pagina=2, por_pagina=2)
        assert len(p1["linhas"]) == 2
        assert p1["paginas"] == (p1["total"] + 1) // 2
        assert p1["linhas"][0] != p2["linhas"][0]


class TestDecidir:
    def test_confirmar_sem_editar_mantem_a_origem(self, catalogo):
        catalogo.decidir("VOLKSWAGEN", "FUSCA", "1300", "confirmado")
        l = _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")
        assert l["situacao"] == "confirmado"
        assert (l["marca"], l["modelo"], l["versao"]) == ("VOLKSWAGEN", "FUSCA", "1300")
        assert l["editado"] is False

    def test_editar_nome_e_anos(self, catalogo):
        catalogo.decidir("VOLKSWAGEN", "FUSCA", "1300", "confirmado",
                         versao="1300 L", ano_min=1965, ano_max=1980)
        l = _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")
        assert l["versao"] == "1300 L"
        assert (l["ano_min"], l["ano_max"]) == (1965, 1980)
        assert l["editado"] is True
        # A origem não muda: é ela que mantém o vínculo com as fontes.
        assert l["versao_origem"] == "1300"

    def test_editar_so_os_anos_herda_o_nome(self, catalogo):
        catalogo.decidir("VOLKSWAGEN", "FUSCA", "1300", "confirmado",
                         ano_min=1960, ano_max=1986)
        l = _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")
        assert (l["marca"], l["modelo"], l["versao"]) == ("VOLKSWAGEN", "FUSCA", "1300")
        assert (l["ano_min"], l["ano_max"]) == (1960, 1986)

    def test_versao_pode_ser_esvaziada(self, catalogo):
        """'Esta linha é o modelo, sem versão' é uma decisão legítima."""
        catalogo.decidir("VOLKSWAGEN", "FUSCA", "1300", "confirmado", versao="")
        assert _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")["versao"] == ""

    def test_descartar(self, catalogo):
        catalogo.decidir("FORD", "CORCEL", "GT", "descartado")
        assert _linha(catalogo, "FORD", "CORCEL", "GT")["situacao"] == "descartado"

    def test_reabrir_apaga_a_decisao(self, catalogo):
        """Voltar atrás tem que devolver a linha ao estado original."""
        catalogo.decidir("VOLKSWAGEN", "FUSCA", "1300", "confirmado",
                         versao="OUTRA COISA", ano_min=1900, ano_max=2000)
        catalogo.decidir("VOLKSWAGEN", "FUSCA", "1300", "pendente")
        l = _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")
        assert l["situacao"] == "pendente"
        assert l["versao"] == "1300"
        assert (l["ano_min"], l["ano_max"]) == (1959, 1996)
        assert catalogo.carregar_decisoes() == {}

    def test_decisao_sobrevive_a_releitura(self, catalogo):
        catalogo.decidir("GURGEL", "XEF", "", "confirmado", ano_min=1981)
        assert catalogo.carregar_decisoes()[("GURGEL", "XEF", "")]["ano_min"] == 1981

    def test_normaliza_a_chave_recebida(self, catalogo):
        catalogo.decidir("volkswagen", "fusca", "1300", "confirmado")
        assert _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")["situacao"] == "confirmado"

    @pytest.mark.parametrize("situacao", ["", "sei la", "CONFIRMADO"])
    def test_situacao_invalida(self, catalogo, situacao):
        with pytest.raises(ValueError, match="Situação inválida"):
            catalogo.decidir("VOLKSWAGEN", "FUSCA", "1300", situacao)

    def test_faixa_invertida(self, catalogo):
        with pytest.raises(ValueError, match="invertida"):
            catalogo.decidir("VOLKSWAGEN", "FUSCA", "1300", "confirmado",
                             ano_min=1990, ano_max=1980)

    def test_trio_inexistente(self, catalogo):
        """Sem isso, um erro de digitação viraria linha órfã no arquivo."""
        with pytest.raises(ValueError, match="não existe"):
            catalogo.decidir("FERRARI", "F40", "", "confirmado")

    def test_marca_ou_modelo_vazios(self, catalogo):
        with pytest.raises(ValueError, match="obrigatórios"):
            catalogo.decidir("", "FUSCA", "", "confirmado")


class TestExportar:
    def test_so_o_confirmado(self, catalogo):
        catalogo.decidir("VOLKSWAGEN", "FUSCA", "1300", "confirmado", ano_min=1960)
        catalogo.decidir("FORD", "CORCEL", "GT", "descartado")
        colunas, linhas = catalogo.exportar_definitivo()
        assert colunas[:3] == ["marca", "modelo", "versao"]
        assert [(l["marca"], l["modelo"], l["versao"]) for l in linhas] == [
            ("VOLKSWAGEN", "FUSCA", "1300")
        ]
        assert linhas[0]["ano_min"] == 1960
        assert "anuncios" in linhas[0]["fontes"]

    def test_descartado_tambem_pode_ser_baixado(self, catalogo):
        catalogo.decidir("FORD", "CORCEL", "GT", "descartado")
        _, linhas = catalogo.exportar_definitivo("descartado")
        assert [l["modelo"] for l in linhas] == ["CORCEL"]

    def test_pendente_e_a_fila_inteira(self, catalogo):
        _, linhas = catalogo.exportar_definitivo("pendente")
        assert len(linhas) == catalogo.resumo()["total"]


class TestRotas:
    """A camada HTTP: o que a tela realmente consome."""

    def test_listagem_traz_resumo_e_marcas(self, client, catalogo):
        r = client.get("/admin/api/catalogo?por_pagina=5")
        assert r.status_code == 200
        d = r.get_json()
        assert d["resumo"]["total"] > 0
        assert any(m["marca"] == "VOLKSWAGEN" for m in d["marcas"])
        assert len(d["linhas"]) <= 5

    def test_so_linhas_omite_o_resumo(self, client, catalogo):
        """O resumo custa varrer o índice; a paginação não pode pagar isso."""
        d = client.get("/admin/api/catalogo?so_linhas=1").get_json()
        assert "resumo" not in d and "marcas" not in d

    def test_situacao_invalida_e_400(self, client, catalogo):
        r = client.get("/admin/api/catalogo?situacao=talvez")
        assert r.status_code == 400

    def test_fonte_invalida_e_400(self, client, catalogo):
        assert client.get("/admin/api/catalogo?fonte=chute").status_code == 400

    def test_decidir_pela_rota(self, client, catalogo):
        r = client.post("/admin/api/catalogo-decidir", json={
            "marca_origem": "VOLKSWAGEN", "modelo_origem": "FUSCA",
            "versao_origem": "1300", "situacao": "confirmado",
            "ano_min": "1960", "ano_max": "1986",
        })
        assert r.status_code == 200 and r.get_json()["ok"] is True
        l = _linha(catalogo, "VOLKSWAGEN", "FUSCA", "1300")
        assert l["situacao"] == "confirmado" and l["ano_min"] == 1960

    def test_decidir_trio_inexistente_e_400(self, client, catalogo):
        r = client.post("/admin/api/catalogo-decidir", json={
            "marca_origem": "FERRARI", "modelo_origem": "F40",
            "versao_origem": "", "situacao": "confirmado",
        })
        assert r.status_code == 400

    def test_decidir_ano_nao_numerico_e_400(self, client, catalogo):
        r = client.post("/admin/api/catalogo-decidir", json={
            "marca_origem": "VOLKSWAGEN", "modelo_origem": "FUSCA",
            "versao_origem": "1300", "situacao": "confirmado",
            "ano_min": "mil novecentos",
        })
        assert r.status_code == 400

    def test_exportar_csv(self, client, catalogo):
        catalogo.decidir("VOLKSWAGEN", "FUSCA", "1300", "confirmado")
        r = client.get("/admin/api/exportar-catalogo")
        assert r.status_code == 200
        assert r.headers["X-Total-Linhas"] == "1"
        corpo = r.get_data().decode("utf-8-sig")
        assert corpo.splitlines()[0].startswith("marca;modelo;versao")
        assert "FUSCA" in corpo

    def test_pagina_carrega(self, client):
        r = client.get("/admin/catalogo")
        assert r.status_code == 200
        assert b"Cat\xc3\xa1logo definitivo" in r.get_data()
