"""
Testes de regressão dos parsers do Ateliê do Carro.

Cobre parsear_listagem_html() e parsear_detalhe_html() com:
- HTML mínimo inline (testes rápidos, sem dependência externa)
- Fixtures reais salvas em tests/fixtures/ (pulados se não existirem)
"""
import pytest
from pathlib import Path

from src.connectors.ateliedocarro import parsear_detalhe_html, parsear_listagem_html
from src.pipeline.schema import validar

# ── Fixtures de arquivo ──────────────────────────────────────────────────────

FIXTURE_LISTAGEM = Path(__file__).parent / "fixtures" / "ateliedocarro_listagem_sample.html"
FIXTURE_DETALHE = Path(__file__).parent / "fixtures" / "ateliedocarro_detalhe_sample.html"


@pytest.fixture(scope="module")
def html_listagem():
    if not FIXTURE_LISTAGEM.exists():
        pytest.skip("Fixture ateliedocarro_listagem_sample.html não encontrada.")
    return FIXTURE_LISTAGEM.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html_detalhe():
    if not FIXTURE_DETALHE.exists():
        pytest.skip("Fixture ateliedocarro_detalhe_sample.html não encontrada.")
    return FIXTURE_DETALHE.read_text(encoding="utf-8")


# ── HTML mínimo — listagem com dois cards ────────────────────────────────────

_HTML_LISTAGEM_MINIMO = """
<!DOCTYPE html>
<html><body>
<article>
  <header>
    <h2 class="entry-title">
      <a href="https://ateliedocarro.com.br/carro/kombi-1972/">Kombi 1500 1972</a>
    </h2>
  </header>
</article>
<article>
  <header>
    <h2 class="entry-title">
      <a href="https://ateliedocarro.com.br/carro/fusca-1975/">Fusca 1300 1975</a>
    </h2>
  </header>
</article>
<nav>
  <a class="next page-numbers" href="/carros-a-venda/page/2/">Próxima</a>
</nav>
</body></html>
"""

# HTML mínimo — listagem SEM próxima página
_HTML_LISTAGEM_ULTIMA_PAG = """
<!DOCTYPE html>
<html><body>
<article>
  <header>
    <h2 class="entry-title">
      <a href="/carro/maverick-v8-1977/">Maverick V8 1977</a>
    </h2>
  </header>
</article>
</body></html>
"""

# ── HTML mínimo — detalhe com tabela estruturada ─────────────────────────────

_HTML_DETALHE_COMPLETO = """
<!DOCTYPE html>
<html><body>
<h1>Kombi Luxo 1500 1972</h1>
<table>
  <tr><th>Marca/Modelo</th><td>Volkswagen / Kombi</td></tr>
  <tr><th>Ano/Modelo</th><td>1972/72</td></tr>
  <tr><th>Motor</th><td>1.5 6V</td></tr>
  <tr><th>Quilometragem</th><td>não informada</td></tr>
  <tr><th>Cor</th><td>Bege</td></tr>
  <tr><th>Valor</th><td>R$ 148.000</td></tr>
</table>
<div class="descricao">
  <p>Disponível em São Paulo – SP.</p>
</div>
</body></html>
"""

# Detalhe sem linha "Valor" mas com R$ na descrição (fallback)
_HTML_DETALHE_PRECO_DESCRICAO = """
<!DOCTYPE html>
<html><body>
<h1>Fusca Itamar Conversível 1996</h1>
<table>
  <tr><th>Marca/Modelo</th><td>Volkswagen / Fusca</td></tr>
  <tr><th>Ano/Modelo</th><td>1996/96</td></tr>
  <tr><th>Cor</th><td>Branco</td></tr>
</table>
<div class="descricao">
  <p>Fusca único! Valor: R$ 95.000. Contato: (11) 98888-7777.</p>
</div>
</body></html>
"""

# Detalhe sem preço — deve retornar None
_HTML_DETALHE_SEM_PRECO = """
<!DOCTYPE html>
<html><body>
<h1>Carro Sem Preço</h1>
<table>
  <tr><th>Marca/Modelo</th><td>Ford / Del Rey</td></tr>
  <tr><th>Ano/Modelo</th><td>1982/82</td></tr>
</table>
<div class="descricao"><p>Preço sob consulta.</p></div>
</body></html>
"""

# Detalhe com acento no label da tabela
_HTML_DETALHE_LABEL_ACENTO = """
<!DOCTYPE html>
<html><body>
<h1>Maverick V8 1977</h1>
<table>
  <tr><th>Marca/Modelo</th><td>Ford / Maverick</td></tr>
  <tr><th>Ano/Modelo</th><td>1977/77</td></tr>
  <tr><th>Valor</th><td>R$ 185.000,00</td></tr>
</table>
</body></html>
"""


# ════════════════════════════════════════════════
# Testes: parsear_listagem_html — HTML mínimo
# ════════════════════════════════════════════════

class TestListagemMinimo:
    @pytest.fixture(scope="class")
    def cards(self):
        return parsear_listagem_html(_HTML_LISTAGEM_MINIMO, data_coleta="2026-05-30")

    def test_retorna_dois_cards(self, cards):
        assert len(cards) == 2

    def test_titulos(self, cards):
        titulos = [c.titulo for c in cards]
        assert any("Kombi" in t for t in titulos)
        assert any("Fusca" in t for t in titulos)

    def test_urls_absolutas(self, cards):
        for c in cards:
            assert c.url.startswith("https://")

    def test_urls_apontam_para_carro(self, cards):
        for c in cards:
            assert "/carro/" in c.url

    def test_anos_extraidos(self, cards):
        anos = [c.ano for c in cards]
        assert 1972 in anos
        assert 1975 in anos

    def test_fonte(self, cards):
        for c in cards:
            assert c.fonte == "ateliedocarro"

    def test_preco_none_na_listagem(self, cards):
        for c in cards:
            assert c.preco is None

    def test_sem_duplicatas(self, cards):
        urls = [c.url for c in cards]
        assert len(urls) == len(set(urls))


class TestListagemUltimaPagina:
    def test_link_relativo_vira_absoluto(self):
        cards = parsear_listagem_html(_HTML_LISTAGEM_ULTIMA_PAG, data_coleta="2026-05-30")
        assert len(cards) == 1
        assert cards[0].url.startswith("https://ateliedocarro.com.br")

    def test_ano_extraido_do_titulo(self):
        cards = parsear_listagem_html(_HTML_LISTAGEM_ULTIMA_PAG, data_coleta="2026-05-30")
        assert cards[0].ano == 1977


# ════════════════════════════════════════════════
# Testes: parsear_detalhe_html — HTML mínimo
# ════════════════════════════════════════════════

_URL_KOMBI = "https://ateliedocarro.com.br/carro/kombi-1972/"
_URL_FUSCA = "https://ateliedocarro.com.br/carro/fusca-1996/"
_URL_MAVERICK = "https://ateliedocarro.com.br/carro/maverick-1977/"
_URL_DEL_REY = "https://ateliedocarro.com.br/carro/del-rey-1982/"


class TestDetalheCompleto:
    @pytest.fixture(scope="class")
    def anuncio(self):
        return parsear_detalhe_html(_HTML_DETALHE_COMPLETO, _URL_KOMBI, "2026-05-30")

    def test_retorna_anuncio(self, anuncio):
        assert anuncio is not None

    def test_titulo(self, anuncio):
        assert "Kombi" in anuncio.titulo

    def test_marca(self, anuncio):
        assert anuncio.marca == "VOLKSWAGEN"

    def test_modelo(self, anuncio):
        assert anuncio.modelo == "KOMBI"

    def test_ano(self, anuncio):
        assert anuncio.ano == 1972

    def test_preco(self, anuncio):
        assert anuncio.preco == 148_000.0

    def test_url(self, anuncio):
        assert anuncio.url == _URL_KOMBI

    def test_fonte(self, anuncio):
        assert anuncio.fonte == "ateliedocarro"

    def test_valido(self, anuncio):
        assert validar(anuncio)


class TestDetalhePrecoNaDescricao:
    @pytest.fixture(scope="class")
    def anuncio(self):
        return parsear_detalhe_html(_HTML_DETALHE_PRECO_DESCRICAO, _URL_FUSCA, "2026-05-30")

    def test_retorna_anuncio(self, anuncio):
        assert anuncio is not None

    def test_preco_extraido_da_descricao(self, anuncio):
        assert anuncio.preco == 95_000.0

    def test_marca_e_modelo(self, anuncio):
        assert anuncio.marca == "VOLKSWAGEN"
        assert anuncio.modelo == "FUSCA"

    def test_ano(self, anuncio):
        assert anuncio.ano == 1996


class TestDetalheSemPreco:
    def test_retorna_none(self):
        resultado = parsear_detalhe_html(_HTML_DETALHE_SEM_PRECO, _URL_DEL_REY, "2026-05-30")
        assert resultado is None


class TestDetalheLabelComAcento:
    @pytest.fixture(scope="class")
    def anuncio(self):
        return parsear_detalhe_html(_HTML_DETALHE_LABEL_ACENTO, _URL_MAVERICK, "2026-05-30")

    def test_preco_formato_brasileiro(self, anuncio):
        assert anuncio is not None
        assert anuncio.preco == 185_000.0

    def test_marca_modelo(self, anuncio):
        assert anuncio.marca == "FORD"
        assert anuncio.modelo == "MAVERICK"


# ════════════════════════════════════════════════
# Testes com fixtures salvas em disco
# ════════════════════════════════════════════════

class TestListagemFixture:
    @pytest.fixture(scope="class")
    def cards(self, html_listagem):
        return parsear_listagem_html(html_listagem, data_coleta="2026-05-30")

    def test_retorna_cards(self, cards):
        assert len(cards) >= 1, "Esperado ao menos 1 card na fixture de listagem"

    def test_todos_tem_titulo(self, cards):
        for c in cards:
            assert c.titulo, f"Card sem título: {c}"

    def test_todos_tem_url_absoluta(self, cards):
        for c in cards:
            assert c.url.startswith("https://"), f"URL inválida: {c.url}"

    def test_todos_tem_fonte(self, cards):
        for c in cards:
            assert c.fonte == "ateliedocarro"

    def test_sem_duplicatas(self, cards):
        urls = [c.url for c in cards]
        assert len(urls) == len(set(urls))


class TestDetalheFixture:
    @pytest.fixture(scope="class")
    def anuncio(self, html_detalhe):
        return parsear_detalhe_html(
            html_detalhe,
            "https://ateliedocarro.com.br/carro/kombi-luxo-1972/",
            data_coleta="2026-05-30",
        )

    def test_retorna_anuncio(self, anuncio):
        assert anuncio is not None, "parsear_detalhe_html retornou None para a fixture"

    def test_tem_titulo(self, anuncio):
        assert anuncio.titulo

    def test_marca_volkswagen(self, anuncio):
        assert anuncio.marca == "VOLKSWAGEN"

    def test_modelo_kombi(self, anuncio):
        assert anuncio.modelo == "KOMBI"

    def test_ano_1972(self, anuncio):
        assert anuncio.ano == 1972

    def test_preco_positivo(self, anuncio):
        assert anuncio.preco is not None and anuncio.preco > 0

    def test_fonte(self, anuncio):
        assert anuncio.fonte == "ateliedocarro"

    def test_valido(self, anuncio):
        assert validar(anuncio)
