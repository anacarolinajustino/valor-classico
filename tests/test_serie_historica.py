"""
Testes do fechamento de competência (src/pipeline/serie_historica.py).

O que está em jogo aqui é perda de dado: fechar errado apaga da base ativa
anúncios que não deviam sair, e fechar tarde demais deixa a coleta seguinte
sobrescrever o mês. Por isso quase todo teste aqui é sobre o que NÃO pode
acontecer.
"""
import psycopg2
import pytest

from src.pipeline import serie_historica as sh
from src.pipeline.persistence import _connect, upsert_anuncios
from src.pipeline.schema import Anuncio


def _anuncio(url, visto, fonte="olx", preco=30000.0, marca="VOLKSWAGEN",
             modelo="FUSCA", ano=1975):
    return Anuncio(
        titulo=f"Carro {ano}", preco=preco, marca=marca, modelo=modelo, ano=ano,
        versao=None, url=url, fonte=fonte, data_coleta=visto,
    )


def _forcar_vista(url, quando):
    """
    `upsert_anuncios` carimba a data de hoje; a série depende da
    `ultima_vista`, então os testes precisam plantá-la à mão.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE anuncios SET ultima_vista = %s, primeira_vista = %s "
                "WHERE url = %s",
                (quando, quando, url),
            )


def _semear(linhas):
    """linhas: [(url, ultima_vista, fonte)]"""
    upsert_anuncios([_anuncio(u, v, fonte=f) for u, v, f in linhas])
    for u, v, _ in linhas:
        _forcar_vista(u, v)


def _ativos():
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT url FROM anuncios ORDER BY url")
            return [r["url"] for r in cur.fetchall()]


def _no_snapshot(competencia=None):
    with _connect() as conn:
        with conn.cursor() as cur:
            if competencia:
                cur.execute("SELECT url FROM anuncios_snapshot "
                            "WHERE competencia = %s ORDER BY url", (competencia,))
            else:
                cur.execute("SELECT url FROM anuncios_snapshot ORDER BY url")
            return [r["url"] for r in cur.fetchall()]


@pytest.fixture(autouse=True)
def limpar():
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE anuncios, anuncios_snapshot RESTART IDENTITY")
    yield


class TestValidacao:
    @pytest.mark.parametrize("comp", ["", "2026", "2026-13", "2026-00",
                                      "26-07", "2026/07", "julho"])
    def test_formato_invalido(self, comp):
        with pytest.raises(ValueError, match="formato"):
            sh.validar_competencia(comp)

    def test_formato_valido(self):
        assert sh.validar_competencia(" 2026-07 ") == "2026-07"

    def test_mes_sem_anuncio_nao_fecha(self):
        """Fechar um mês vazio criaria uma competência fantasma na série."""
        _semear([("http://x/1", "2026-07-14", "olx")])
        with pytest.raises(ValueError, match="Nenhum anúncio"):
            sh.fechar("2026-08")


class TestFechar:
    def test_copia_os_vistos_pro_snapshot(self):
        _semear([("http://x/1", "2026-07-14", "olx"),
                 ("http://x/2", "2026-07-23", "olx")])
        r = sh.fechar("2026-07")
        assert r["gravados"] == 2
        assert _no_snapshot("2026-07") == ["http://x/1", "http://x/2"]

    def test_purga_os_nao_vistos(self):
        _semear([("http://x/vivo", "2026-07-14", "olx"),
                 ("http://x/morto", "2026-06-26", "olx")])
        r = sh.fechar("2026-07")
        assert r["purgados"] == 1
        assert _ativos() == ["http://x/vivo"]

    def test_o_purgado_nao_entra_no_snapshot_do_mes(self):
        """Anúncio de junho não é anúncio de julho."""
        _semear([("http://x/vivo", "2026-07-14", "olx"),
                 ("http://x/morto", "2026-06-26", "olx")])
        sh.fechar("2026-07")
        assert _no_snapshot("2026-07") == ["http://x/vivo"]

    def test_o_anuncio_cru_e_preservado(self):
        """É o que permite recalcular o índice do mês com curva nova."""
        upsert_anuncios([_anuncio("http://x/1", "2026-07-14", preco=42500.0,
                                  modelo="OPALA", ano=1980)])
        _forcar_vista("http://x/1", "2026-07-14")
        sh.fechar("2026-07")
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM anuncios_snapshot")
                l = cur.fetchone()
        assert (l["preco"], l["modelo"], l["ano"]) == (42500.0, "OPALA", 1980)
        assert l["ultima_vista"] == "2026-07-14"

    def test_sem_purga_grava_e_nao_apaga(self):
        _semear([("http://x/vivo", "2026-07-14", "olx"),
                 ("http://x/morto", "2026-06-26", "olx")])
        r = sh.fechar("2026-07", purgar=False)
        assert r["purgados"] == 0
        assert len(_ativos()) == 2


class TestTravaDaFonteNaoColetada:
    """
    A trava que evita a perda grande: apagar "tudo que não foi visto"
    varreria uma fonte inteira que simplesmente não foi coletada no mês.
    """

    def test_fonte_sem_anuncio_no_mes_fica_intacta(self):
        _semear([("http://olx/1", "2026-08-10", "olx"),
                 ("http://wm/1", "2026-07-14", "webmotors"),
                 ("http://wm/2", "2026-07-14", "webmotors")])
        r = sh.fechar("2026-08")
        assert r["purgados"] == 0
        assert r["nao_coletadas_total"] == 2
        assert "http://wm/1" in _ativos()

    def test_purga_so_dentro_das_fontes_coletadas(self):
        _semear([("http://olx/novo", "2026-08-10", "olx"),
                 ("http://olx/velho", "2026-07-14", "olx"),
                 ("http://wm/velho", "2026-07-14", "webmotors")])
        r = sh.fechar("2026-08")
        assert r["purgados"] == 1          # só o da OLX
        assert sorted(_ativos()) == ["http://olx/novo", "http://wm/velho"]

    def test_diagnostico_separa_morto_de_nao_coletado(self):
        _semear([("http://olx/novo", "2026-08-10", "olx"),
                 ("http://olx/velho", "2026-07-14", "olx"),
                 ("http://wm/velho", "2026-07-14", "webmotors")])
        d = sh.diagnosticar("2026-08")
        assert d["mortos_total"] == 1
        assert d["nao_coletadas_total"] == 1
        assert [f["fonte"] for f in d["nao_coletadas"]] == ["webmotors"]


class TestColapsoDeFonte:
    """
    A trava que a coleta de 2026-08-17 pediu: o eduardoveiculosantigos
    devolveu zero sem erro (a página veio sem os cards) e nove na tentativa
    seguinte. Zero é pego pela trava da fonte não coletada; UM não seria - a
    fonte entraria em `fontes_coletadas` e os outros seriam purgados.
    """

    def _fonte_com(self, n_julho, n_agosto, fonte="olx"):
        linhas = [(f"http://{fonte}/j{i}", "2026-07-14", fonte) for i in range(n_julho)]
        _semear(linhas)
        if n_agosto:
            _semear([(f"http://{fonte}/j{i}", "2026-08-10", fonte)
                     for i in range(n_agosto)])

    def test_perda_grande_barra_o_fechamento(self):
        self._fonte_com(100, 1)
        with pytest.raises(ValueError, match="perderam mais de"):
            sh.fechar("2026-08")

    def test_nada_e_purgado_quando_barra(self):
        """A exceção não pode deixar meio caminho andado."""
        self._fonte_com(100, 1)
        with pytest.raises(ValueError):
            sh.fechar("2026-08")
        assert len(_ativos()) == 100
        assert _no_snapshot() == []

    def test_permitir_colapso_libera_a_fonte_nomeada(self):
        self._fonte_com(100, 1, fonte="icarros")
        r = sh.fechar("2026-08", permitir_colapso=["icarros"])
        assert r["purgados"] == 99

    def test_permitir_colapso_nao_libera_as_outras(self):
        """
        Liberar em bloco desarmaria a trava na rodada em que ela mais importa:
        a fonte que despencou de verdade e a que quebrou junto, sem avisar.
        """
        self._fonte_com(100, 1, fonte="icarros")
        self._fonte_com(100, 1, fonte="olx")
        with pytest.raises(ValueError, match="olx"):
            sh.fechar("2026-08", permitir_colapso=["icarros"])
        assert len(_ativos()) == 200

    def test_sem_purga_nao_precisa_da_trava(self):
        """Sem purga não há o que perder."""
        self._fonte_com(100, 1)
        assert sh.fechar("2026-08", purgar=False)["purgados"] == 0

    def test_perda_normal_nao_barra(self):
        """Loja pequena vende metade do pátio; travar nisso viraria ruído."""
        self._fonte_com(100, 60)
        assert sh.fechar("2026-08")["purgados"] == 40

    def test_fonte_pequena_nao_dispara(self):
        """Numa fonte de 4 anúncios, vender 3 é 75% e não quer dizer nada."""
        self._fonte_com(4, 1)
        assert sh.fechar("2026-08")["purgados"] == 3

    def test_zero_continua_sendo_fonte_nao_coletada(self):
        """O caso do eduardoveiculosantigos: some de fontes_coletadas."""
        self._fonte_com(100, 0)
        _semear([("http://outra/1", "2026-08-10", "maxicar")])
        r = sh.fechar("2026-08")
        assert r["purgados"] == 0
        assert r["nao_coletadas_total"] == 100
        assert r["colapsadas"] == []

    def test_diagnostico_mostra_sem_alterar(self):
        self._fonte_com(100, 1)
        d = sh.diagnosticar("2026-08")
        assert [c["fonte"] for c in d["colapsadas"]] == ["olx"]
        assert d["colapsadas"][0]["antes"] == 100
        assert d["colapsadas"][0]["vistos"] == 1
        assert len(_ativos()) == 100


class TestFecharDuasVezes:
    def test_segunda_vez_e_erro(self):
        """
        Sem a trava, refechar depois de uma coleta nova sobrescreveria o mês
        em silêncio com preços que já não são os daquele mês.
        """
        _semear([("http://x/1", "2026-07-14", "olx")])
        sh.fechar("2026-07")
        with pytest.raises(ValueError, match="já foi fechada"):
            sh.fechar("2026-07")

    def test_refazer_sobrescreve(self):
        _semear([("http://x/1", "2026-07-14", "olx")])
        sh.fechar("2026-07")
        _semear([("http://x/2", "2026-07-15", "olx")])
        r = sh.fechar("2026-07", refazer=True)
        assert r["gravados"] == 2
        assert _no_snapshot("2026-07") == ["http://x/1", "http://x/2"]

    def test_nao_duplica_linha(self):
        _semear([("http://x/1", "2026-07-14", "olx")])
        sh.fechar("2026-07")
        sh.fechar("2026-07", refazer=True)
        assert len(_no_snapshot("2026-07")) == 1

    def test_indice_unico_barra_duplicata(self):
        """A trava final é do banco, não do código."""
        _semear([("http://x/1", "2026-07-14", "olx")])
        sh.fechar("2026-07")
        with pytest.raises(psycopg2.errors.UniqueViolation):
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO anuncios_snapshot
                           (competencia, fonte, url, titulo, primeira_vista, ultima_vista)
                           VALUES ('2026-07', 'olx', 'http://x/1', 't', 'd', 'd')"""
                    )


class TestMesesConvivem:
    def test_dois_meses_no_snapshot(self):
        _semear([("http://x/1", "2026-07-14", "olx")])
        sh.fechar("2026-07")
        _semear([("http://x/1", "2026-08-10", "olx"),
                 ("http://x/2", "2026-08-10", "olx")])
        sh.fechar("2026-08")
        assert _no_snapshot("2026-07") == ["http://x/1"]
        assert _no_snapshot("2026-08") == ["http://x/1", "http://x/2"]

    def test_o_preco_de_cada_mes_sobrevive(self):
        """
        O ponto inteiro da série: o upsert sobrescreve o preço na base ativa,
        e o snapshot de julho tem que continuar com o preço de julho.
        """
        upsert_anuncios([_anuncio("http://x/1", "2026-07-14", preco=30000.0)])
        _forcar_vista("http://x/1", "2026-07-14")
        sh.fechar("2026-07")

        upsert_anuncios([_anuncio("http://x/1", "2026-08-10", preco=39000.0)])
        _forcar_vista("http://x/1", "2026-08-10")
        sh.fechar("2026-08")

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT competencia, preco FROM anuncios_snapshot "
                            "ORDER BY competencia")
                precos = {r["competencia"]: r["preco"] for r in cur.fetchall()}
        assert precos == {"2026-07": 30000.0, "2026-08": 39000.0}


class TestPanorama:
    def test_competencias_na_base(self):
        _semear([("http://x/1", "2026-07-14", "olx"),
                 ("http://x/2", "2026-07-23", "olx"),
                 ("http://x/3", "2026-06-26", "maxicar")])
        comps = {c["competencia"]: c for c in sh.competencias_na_base()}
        assert comps["2026-07"]["anuncios"] == 2
        assert comps["2026-06"]["anuncios"] == 1
        assert comps["2026-06"]["fontes"] == 1

    def test_competencias_fechadas(self):
        _semear([("http://x/1", "2026-07-14", "olx", )])
        sh.fechar("2026-07")
        f = sh.competencias_fechadas()
        assert len(f) == 1
        assert f[0]["competencia"] == "2026-07"
        assert f[0]["com_preco"] == 1

    def test_nada_fechado_e_lista_vazia(self):
        assert sh.competencias_fechadas() == []


class TestReabrir:
    def test_apaga_o_snapshot(self):
        _semear([("http://x/1", "2026-07-14", "olx")])
        sh.fechar("2026-07")
        assert sh.reabrir("2026-07")["removidos"] == 1
        assert _no_snapshot() == []

    def test_nao_devolve_o_purgado(self):
        """
        Aquilo era anúncio morto; voltar a contá-lo refaria o problema que o
        fechamento resolveu.
        """
        _semear([("http://x/vivo", "2026-07-14", "olx"),
                 ("http://x/morto", "2026-06-26", "olx")])
        sh.fechar("2026-07")
        sh.reabrir("2026-07")
        assert _ativos() == ["http://x/vivo"]

    def test_reabrir_permite_fechar_de_novo(self):
        _semear([("http://x/1", "2026-07-14", "olx")])
        sh.fechar("2026-07")
        sh.reabrir("2026-07")
        assert sh.fechar("2026-07")["gravados"] == 1
