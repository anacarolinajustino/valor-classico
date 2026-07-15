"""
Testes da ficha técnica (página de detalhe) do conector Mercado Livre.

Auditoria 2026-07-15: marca/modelo vinham só de adivinhar o título, o que
falha quando o título começa por algo que não é a marca (ex.: "AP 2000..."
é o código do motor, a marca real — Ford Versailles — só está na ficha
técnica). O snapshot foi coletado ao vivo desse anúncio exato.
"""
from pathlib import Path

from src.connectors.mercadolivre import _extrair_ficha_tecnica, _enriquecer_com_ficha_tecnica
from src.pipeline.schema import Anuncio

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mercadolivre_detalhe_sample.html"

_HTML_FICHA_MINIMA = """
<!DOCTYPE html>
<html><body>
<div class="ui-pdp-specs__table">
  <table class="andes-table">
    <tbody class="andes-table__body">
      <tr class="andes-table__row">
        <th class="andes-table__header"><div class="andes-table__header__container">Marca</div></th>
        <td class="andes-table__column"><span class="andes-table__column--value">Ford</span></td>
      </tr>
      <tr class="andes-table__row">
        <th class="andes-table__header"><div class="andes-table__header__container">Modelo</div></th>
        <td class="andes-table__column"><span class="andes-table__column--value">Versailles</span></td>
      </tr>
      <tr class="andes-table__row">
        <th class="andes-table__header"><div class="andes-table__header__container">Ano</div></th>
        <td class="andes-table__column"><span class="andes-table__column--value">1996</span></td>
      </tr>
    </tbody>
  </table>
</div>
</body></html>
"""


def _anuncio_ap() -> Anuncio:
    return Anuncio(
        titulo="Ap 2000,injeção,4 Portas,ar,direção,trio Elétrico,gasolina",
        preco=25000.0,
        marca="AP",
        modelo="2000INJECAO4 PORTASARDIRECAOTRIO ELETRICOGASOLINA",
        ano=1996,
        versao=None,
        url="https://carro.mercadolivre.com.br/MLB-7057209540-ap-2000injeco4-portasardirecotrio-eletricogasolina-_JM",
        fonte="mercadolivre",
        data_coleta="2026-07-15",
    )


class TestExtrairFichaTecnica:
    def test_html_minimo(self):
        ficha = _extrair_ficha_tecnica(_HTML_FICHA_MINIMA)
        assert ficha["MARCA"] == "Ford"
        assert ficha["MODELO"] == "Versailles"
        assert ficha["ANO"] == "1996"

    def test_sem_tabela_retorna_vazio(self):
        assert _extrair_ficha_tecnica("<html><body>sem ficha aqui</body></html>") == {}

    def test_snapshot_real_caso_ap(self):
        # O anúncio que motivou a auditoria: título começa com "AP" (código
        # do motor VW), a ficha técnica revela a marca real.
        html = FIXTURE_PATH.read_text(encoding="utf-8")
        ficha = _extrair_ficha_tecnica(html)
        assert ficha["MARCA"] == "Ford"
        assert ficha["MODELO"] == "Versailles"
        assert ficha["ANO"] == "1996"


class TestEnriquecerComFichaTecnica:
    def test_sobrescreve_marca_modelo_do_titulo(self, monkeypatch):
        html = FIXTURE_PATH.read_text(encoding="utf-8")
        monkeypatch.setattr(
            "src.connectors.mercadolivre._buscar_ficha_tecnica",
            lambda url: _extrair_ficha_tecnica(html),
        )
        resultado = _enriquecer_com_ficha_tecnica(_anuncio_ap())
        assert resultado.marca == "FORD"
        assert resultado.modelo == "VERSAILLES"
        assert resultado.ano == 1996

    def test_sem_ficha_mantem_anuncio_original(self, monkeypatch):
        monkeypatch.setattr(
            "src.connectors.mercadolivre._buscar_ficha_tecnica", lambda url: None,
        )
        original = _anuncio_ap()
        resultado = _enriquecer_com_ficha_tecnica(original)
        assert resultado == original

    def test_ficha_com_ano_acima_do_corte_descarta_anuncio(self, monkeypatch):
        from src.pipeline.persistence import ANO_CORTE_CLASSICO

        ano_moderno = str(ANO_CORTE_CLASSICO + 5)
        monkeypatch.setattr(
            "src.connectors.mercadolivre._buscar_ficha_tecnica",
            lambda url: {"MARCA": "Ford", "MODELO": "Ka", "ANO": ano_moderno},
        )
        assert _enriquecer_com_ficha_tecnica(_anuncio_ap()) is None
