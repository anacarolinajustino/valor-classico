"""
Testes do normalizer (preço e texto).
"""
import pytest
from src.pipeline.normalizer import (
    normalizar_preco,
    normalizar_texto,
    remover_acentos,
    inferir_marca_modelo_ano,
    inferir_marca_modelo_versao_obs_ano,
    sanear_marca_modelo,
    sanear_modelo,
    separar_modelo_versao_obs,
    MARCA_NAO_IDENTIFICADA,
)


# ── normalizar_preco ────────────────────────────

class TestNormalizarPreco:
    def test_formato_brasileiro_completo(self):
        assert normalizar_preco("R$180.000,00") == 180000.0

    def test_formato_sem_simbolo(self):
        assert normalizar_preco("180.000,00") == 180000.0

    def test_formato_inteiro_sem_centavos(self):
        assert normalizar_preco("25000") == 25000.0

    def test_formato_com_espaco(self):
        assert normalizar_preco("R$ 35.000,00") == 35000.0

    def test_string_vazia_retorna_none(self):
        assert normalizar_preco("") is None

    def test_string_consulte_retorna_none(self):
        assert normalizar_preco("Consulte") is None

    def test_valor_zero_retorna_none(self):
        assert normalizar_preco("0") is None

    def test_somente_simbolo_retorna_none(self):
        assert normalizar_preco("R$") is None

    def test_preco_pequeno(self):
        assert normalizar_preco("1.500,00") == 1500.0

    def test_preco_sem_centavos_virgula(self):
        assert normalizar_preco("50.000") == 50000.0


# ── remover_acentos ─────────────────────────────

class TestRemoverAcentos:
    def test_vogais_acentuadas(self):
        assert remover_acentos("ação") == "acao"

    def test_cedilha(self):
        assert remover_acentos("Volkswagen") == "Volkswagen"

    def test_texto_sem_acento_inalterado(self):
        assert remover_acentos("KOMBI") == "KOMBI"

    def test_string_vazia(self):
        assert remover_acentos("") == ""


# ── normalizar_texto ────────────────────────────

class TestNormalizarTexto:
    def test_converte_para_maiusculo(self):
        assert normalizar_texto("volkswagen") == "VOLKSWAGEN"

    def test_remove_acentos_e_maiuscula(self):
        assert normalizar_texto("ção") == "CAO"

    def test_colapsa_espacos(self):
        assert normalizar_texto("VW  Kombi  ") == "VW KOMBI"

    def test_string_vazia(self):
        assert normalizar_texto("") == ""


# ── inferir_marca_modelo_ano ────────────────────

class TestInferirMarcaModeloAno:
    def test_kombi(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Volkswagen Kombi 1975")
        assert marca == "VOLKSWAGEN"
        assert modelo == "KOMBI"
        assert ano == 1975

    def test_fusca_com_versao_na_titulo(self):
        marca, modelo, ano = inferir_marca_modelo_ano("VW Fusca 1200 1962")
        assert marca == "VOLKSWAGEN"  # alias VW resolvido pro nome oficial
        assert "FUSCA" in modelo
        assert ano == 1962

    def test_alias_gm(self):
        marca, modelo, ano = inferir_marca_modelo_ano("GM Chevette Luxo 1.4 1985")
        assert marca == "CHEVROLET"
        assert "CHEVETTE" in modelo
        assert ano == 1985

    def test_alias_mercedes_benz_dois_tokens(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Mercedes Benz 280 SL 1970")
        assert marca == "MERCEDES-BENZ"
        assert "280" in modelo
        assert ano == 1970

    def test_marca_composta_land_rover(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Land Rover Defender 110 1998")
        assert marca == "LAND ROVER"
        assert "DEFENDER" in modelo
        assert ano == 1998

    def test_marca_composta_mp_lafer(self):
        marca, modelo, ano = inferir_marca_modelo_ano("MP Lafer 1976")
        assert marca == "MP LAFER"
        assert ano == 1976

    def test_titulo_comeca_pelo_modelo(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Fusca 1600 1985")
        assert marca == "VOLKSWAGEN"
        # "1600" é cilindrada, sai do modelo no saneamento (2026-07-17)
        assert modelo == "FUSCA"
        assert ano == 1985

    def test_modelo_ambiguo_usa_marca_dominante_no_brasil(self):
        # CARAVAN existe em mais de uma marca no catálogo geral, mas no
        # recorte de clássico brasileiro é sempre Chevrolet (perua do Opala)
        # — auditoria 2026-07-15, 2ª rodada: usuária pediu pra resolver em
        # vez de deixar como marca=lixo (ver _MODELO_AMBIGUO_MARCA).
        marca, modelo, ano = inferir_marca_modelo_ano("Caravan Comodoro 1985")
        assert marca == "CHEVROLET"

    def test_ano_grudado_em_palavra(self):
        # brunelli concatena modelo e ano sem espaço
        marca, modelo, ano = inferir_marca_modelo_ano("VW Saveiro Summer1996 / Prata")
        assert marca == "VOLKSWAGEN"
        assert ano == 1996

    def test_ano_grudado_em_numero(self):
        # "16001995" separa em cilindrada 1600 + ano 1995; a cilindrada depois
        # sai do modelo no saneamento, sobrando só o nome (2026-07-17).
        marca, modelo, ano = inferir_marca_modelo_ano("VW Fusca 16001995 / Bege Urano")
        assert marca == "VOLKSWAGEN"
        assert modelo == "FUSCA"
        assert ano == 1995

    def test_ano_duplicado_colapsado(self):
        # "1983/83" vira "198383" depois que a normalização remove a barra
        marca, modelo, ano = inferir_marca_modelo_ano("Vw Voyage Ls 1983/83 87.000km")
        assert ano == 1983

    def test_faixa_de_ano_dois_digitos(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Caravam Diplomata 87-88")
        assert ano == 1987

    def test_ano_dois_digitos_no_fim(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Escort Ghia 86")
        assert marca == "FORD"
        assert ano == 1986

    def test_dois_digitos_no_meio_nao_e_ano(self):
        # "1.6" e números no meio não podem virar ano
        marca, modelo, ano = inferir_marca_modelo_ano("Gol 1.6 Power")
        assert ano is None

    def test_marca_do_suplemento_dkw(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Dkw Belcar 4 Portas 1964")
        assert marca == "DKW"
        assert ano == 1964

    def test_prefixo_vendo_ignorado(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Vendo Ford F-75 Cabine Estendida")
        assert marca == "FORD"

    def test_prefixo_moto_ignorado(self):
        marca, modelo, ano = inferir_marca_modelo_ano("MOTO HARLEY-DAVIDSON SPRINGER - 1997")
        assert marca == "HARLEY-DAVIDSON"
        assert ano == 1997

    def test_rolls_royce_sem_hifen(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Rolls Royce Silver Shadow 1973")
        assert marca == "ROLLS-ROYCE"
        assert ano == 1973

    def test_grafia_errada_volkswagen(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Volksvagem Fusca 1986")
        assert marca == "VOLKSWAGEN"
        assert ano == 1986

    def test_alias_gm_seguido_de_marca_real(self):
        # "GM" é só um selo: a marca real vem depois
        marca, modelo, ano = inferir_marca_modelo_ano("GM Oldsmobile Tornado – 1969")
        assert marca == "OLDSMOBILE"
        assert ano == 1969

    def test_karmann_ghia_sem_hifen(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Karmann Ghia 1969")
        assert marca == "VOLKSWAGEN"
        assert modelo == "KARMANN GHIA"
        assert ano == 1969

    # ── auditoria 2026-07-15: marca=ano, marca=lixo, "VW/Fusca" grudado ──

    def test_barra_como_separador_marca_modelo(self):
        # "Vw/fusca" virava um token só ("VWFUSCA") e não casava com nada
        marca, modelo, ano = inferir_marca_modelo_ano("Vw/fusca 1600 S")
        assert marca == "VOLKSWAGEN"
        assert "FUSCA" in modelo

    def test_barra_gm_chevrolet(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Gm/chevrolet C10")
        assert marca == "CHEVROLET"

    def test_barra_alias_seguido_de_marca_real(self):
        # Puma é marca própria (usava motor VW) — "Vw/" aqui é só o selo
        # do motor, igual ao caso já existente "GM Oldsmobile"
        marca, modelo, ano = inferir_marca_modelo_ano("Vw/puma Gtc Conversivel 1981")
        assert marca == "PUMA"

    def test_hifen_colado_alias_marca_real(self):
        # "Vw-volkswagen" sem espaço vira um único token
        marca, modelo, ano = inferir_marca_modelo_ano("Vw-volkswagen Santana Cd 1.8 1984/85")
        assert marca == "VOLKSWAGEN"

    def test_ano_solto_no_inicio_nao_vira_marca(self):
        # "1929" na frente sobrava como marca quando outro número no fim
        # ("1930") já tinha sido consumido como ano
        marca, modelo, ano = inferir_marca_modelo_ano("1929 Pickup Ford 1930 Hotrod Motor Opala")
        assert marca == "FORD"
        assert ano == 1930

    def test_ano_solto_alfa_romeo(self):
        marca, modelo, ano = inferir_marca_modelo_ano("1972 Alfa Romeo Spider Veloce 2000")
        assert marca == "ALFA ROMEO"

    def test_modelo_numerico_147_sem_marca_no_titulo(self):
        # "147" é ambíguo no catálogo geral (Fiat e Alfa Romeo), mas neste
        # recorte de clássico brasileiro é sempre o Fiat 147
        marca, modelo, ano = inferir_marca_modelo_ano("147 1.3L")
        assert marca == "FIAT"
        assert "147" in modelo

    def test_alias_fordinho(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Fordinho 29 Hotrod Pickup 1930")
        assert marca == "FORD"

    def test_alias_for_abreviado(self):
        marca, modelo, ano = inferir_marca_modelo_ano("For Mustang Gt 5.0 302 V8")
        assert marca == "FORD"

    def test_grafias_erradas_diversas(self):
        assert inferir_marca_modelo_ano("Chrevolet Opala 1978")[0] == "CHEVROLET"
        assert inferir_marca_modelo_ano("Dogde Dart 1974")[0] == "DODGE"
        assert inferir_marca_modelo_ano("Hoonda Civic 1994")[0] == "HONDA"
        assert inferir_marca_modelo_ano("Porche 356 1962")[0] == "PORSCHE"
        assert inferir_marca_modelo_ano("Guegel X12 1980")[0] == "GURGEL"
        assert inferir_marca_modelo_ano("Mercuri Heigt 1948")[0] == "MERCURY"

    def test_willys_overland_canonicaliza_pra_willys(self):
        # Catálogo tem "WILLYS" e "WILLYS OVERLAND" como marcas separadas
        # pro mesmo fabricante — usuária pediu (2026-07-15) pra manter só
        # "WILLYS", sem fragmentar o grupo já estabelecido de 117 anúncios.
        marca, modelo, ano = inferir_marca_modelo_ano("Willys Overland 1958")
        assert marca == "WILLYS"
        assert "OVERLAND" in modelo
        assert ano == 1958

    def test_modelo_ford_ausente_do_catalogo(self):
        # F100/F150/F1000/F75/XR3 não estão no CSV mas não são ambíguos no Brasil
        assert inferir_marca_modelo_ano("F150 Xlt S 1988")[0] == "FORD"
        assert inferir_marca_modelo_ano("Xr3 Conversivel 1990")[0] == "FORD"

    def test_modelo_chevrolet_ausente_do_catalogo(self):
        assert inferir_marca_modelo_ano("Diplomata 6cc Placa Preta 1985")[0] == "CHEVROLET"
        assert inferir_marca_modelo_ano("Cheyenne Super 10 1974")[0] == "CHEVROLET"

    # ── auditoria 2026-07-15, 2ª rodada: marcas fora do CSV de carros
    # (motos/caminhões/tratores/marcas raras) e mais modelos ambíguos ──

    def test_prefixo_tipo_veiculo_com_marca_propria_depois(self):
        assert inferir_marca_modelo_ano("Trator Zetor")[0] == "ZETOR"
        assert inferir_marca_modelo_ano("Onibus Chevrolet 6100 Boca de Sapo 1952")[0] == "CHEVROLET"
        assert inferir_marca_modelo_ano("Caminhao Chevrolet Coe 46")[0] == "CHEVROLET"
        # Sem marca real depois de "Caminhoneta" — "Aberta" é adjetivo, não
        # nome de marca (ver test_marca_nao_identificada_quando_so_sobra_palavra_comum)
        assert inferir_marca_modelo_ano("Caminhoneta Aberta Cabine Dupla")[0] == MARCA_NAO_IDENTIFICADA

    def test_marca_fora_do_catalogo_de_carros_via_fallback(self):
        # Moto/trator/marca rara: não estão no CSV de carros, mas o
        # fallback "primeiro token" já acerta — usuária decidiu (2ª rodada,
        # 2026-07-15) manter esses veículos na base.
        assert inferir_marca_modelo_ano("Yamaha Tenere 600 1991")[0] == "YAMAHA"
        assert inferir_marca_modelo_ano("Austin Imp A40 1982")[0] == "AUSTIN"
        assert inferir_marca_modelo_ano("Reo 1928 Street Rod")[0] == "REO"

    def test_marca_duas_palavras_fora_do_catalogo(self):
        # Sem alias, o fallback pegaria só o 1º token ("AM"/"DIAMOND"/
        # "PIERCE"/"HARLEY") e devolveria o resto como modelo
        assert inferir_marca_modelo_ano("1982 AM General Humvee")[0] == "AM GENERAL"
        assert inferir_marca_modelo_ano("Diamond T Model 969-A 1943")[0] == "DIAMOND T"
        assert inferir_marca_modelo_ano("Pierce Arrow Bombeiros")[0] == "PIERCE-ARROW"
        assert inferir_marca_modelo_ano("Harley Davidson Sportster 1998")[0] == "HARLEY-DAVIDSON"

    def test_alias_sinca_wyllis_alfa_caloicross(self):
        assert inferir_marca_modelo_ano("Sinca esplanada 1969")[0] == "SIMCA"
        assert inferir_marca_modelo_ano("Rural Wyllis 4 Cilindros 4x4")[0] == "WILLYS"
        assert inferir_marca_modelo_ano("Alfa Rtomeu Spider Veloce 2000")[0] == "ALFA ROMEO"
        assert inferir_marca_modelo_ano("Caloicross Freestyle")[0] == "CALOI"

    def test_modelo_ambiguo_marca_dominante_ampliado(self):
        assert inferir_marca_modelo_ano("Kadett Gsi 1993")[0] == "CHEVROLET"
        assert inferir_marca_modelo_ano("Silverado Z88 1991 Cabine Estendida")[0] == "CHEVROLET"
        assert inferir_marca_modelo_ano("Blazer DLX 96 placa preta")[0] == "CHEVROLET"
        assert inferir_marca_modelo_ano("Ranger 4.0 XLT CS 1998")[0] == "FORD"
        assert inferir_marca_modelo_ano("Rural Willys")[0] == "WILLYS"
        assert inferir_marca_modelo_ano("Rural 4x4")[0] == "WILLYS"
        assert inferir_marca_modelo_ano("D-10 3.9 Diesel 1982")[0] == "CHEVROLET"
        assert inferir_marca_modelo_ano("D-20 Custom S 4.0 Diesel 1995")[0] == "CHEVROLET"
        assert inferir_marca_modelo_ano("C-10 Ano 1971 6cc Alcool")[0] == "CHEVROLET"
        assert inferir_marca_modelo_ano("C1500 Silverado Pace Car")[0] == "CHEVROLET"
        assert inferir_marca_modelo_ano("Premio Sl 1992 Motor 1.6 Alcool")[0] == "FIAT"

    def test_prefixo_e_sem_acento_e_adjetivos_de_venda(self):
        # "É Dauphine..." perde o acento na normalização e vira "E" sozinho
        marca, _, _ = inferir_marca_modelo_ano("E Puma Gts Conversivel Nao Gtb Santa Matilde")
        assert marca == "PUMA"
        assert inferir_marca_modelo_ano("Rara Mobylette Caloi CX 1985")[0] == "MOBYLETTE"
        assert inferir_marca_modelo_ano("Lindo Buggy 1975 Polauto")[0] == "BUGGY"

    def test_prefixo_outros_duplicado_do_ml(self):
        # Categoria do Mercado Livre colada 2x ao título; Santa Matilde é
        # marca real (clássico brasileiro) já no catálogo
        marca, _, ano = inferir_marca_modelo_ano("Outros Outros 1985 Santa Matilde Sm 4.1")
        assert marca == "SANTA MATILDE"
        assert ano == 1985

    # ── verificação geral 2026-07-15: hífen solto e preposição escondendo marca ──

    def test_hifen_solto_nao_vira_marca(self):
        # "Raridade - Volkswagen..." — o hífen cercado de espaços sobra
        # como token próprio (normalizar_texto preserva hífen)
        marca, modelo, ano = inferir_marca_modelo_ano(
            "Raridade - Volkswagen Golf GTI 2.0 1995 (Consigo dividir no cartao em ate 21x)"
        )
        assert marca == "VOLKSWAGEN"
        assert ano == 1995

    def test_prefixo_colecao_mas_nao_de(self):
        # "COLECAO" é pulado, mas "DE" propositalmente não entra em
        # _PREFIXOS_NAO_MARCA (colidiria com "De Soto"/"De Tomaso") — este
        # título específico ("Carro de Coleção! Escort...") só resolve com
        # correção manual pontual, não regra genérica.
        marca, modelo, ano = inferir_marca_modelo_ano("Carro Colecao Escort GL 1.6 Alcool 1985")
        assert marca == "FORD"

    def test_de_soto_de_tomaso_nao_perdem_o_de(self):
        assert inferir_marca_modelo_ano("De Soto Firedome Coupe 1951")[0] == "DE SOTO"
        assert inferir_marca_modelo_ano("De Tomaso Pantera 5.8 Coupe")[0] == "DE TOMASO"

    def test_marca_nao_identificada_quando_so_sobra_palavra_comum(self):
        # Título não cita marca nenhuma — em vez de aceitar a 1ª palavra
        # como se fosse marca real, sinaliza pra revisão manual (usuária
        # pediu 2026-07-15, 3ª rodada, como critério geral)
        casos = [
            "Veiculo Otimo Estado De Conservacao",
            "Veiculo Muito Bem Conservado Com Manutencoes Em Ordem",
            "Placa Preta",
            "Cautelar Aprovado Esta Com 75.000km Os Pneus Novos.",
            "Todo Original, Pertenceu 30 Anos Numa Familia.",
            "Para Reforma",
            "Com Direcao Hidraulica",
        ]
        for titulo in casos:
            marca, _, _ = inferir_marca_modelo_ano(titulo)
            assert marca == MARCA_NAO_IDENTIFICADA, titulo

    def test_marca_real_nao_vira_nao_identificada(self):
        # Guarda contra falso positivo: a stoplist só pega quando é o
        # ÚNICO candidato, marca real continua reconhecida normalmente
        assert inferir_marca_modelo_ano("Yamaha Tenere 600 1991")[0] == "YAMAHA"
        assert inferir_marca_modelo_ano("Austin Imp A40 1982")[0] == "AUSTIN"

    def test_cilindros_solto_no_inicio_nao_vira_marca(self):
        # "6" sobraria como marca se não fosse pulado como o ano já é
        marca, _, ano = inferir_marca_modelo_ano("Hotrod 1930 6 Cilindros Pickup Ford 1929")
        assert marca == "FORD"
        assert ano == 1929

    def test_prefixo_hotrod_ignorado(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Hotrod 1932 Ford 1929 Conversível Roadster 32")
        assert marca == "FORD"
        assert ano == 1929

    def test_sem_ano(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Ford Mustang")
        assert marca == "FORD"
        assert modelo == "MUSTANG"
        assert ano is None

    def test_titulo_vazio(self):
        marca, modelo, ano = inferir_marca_modelo_ano("")
        assert marca == ""
        assert modelo == ""
        assert ano is None

    def test_chevrolet_biscayne(self):
        marca, modelo, ano = inferir_marca_modelo_ano("Chevrolet Biscayne Sedan 1963")
        assert marca == "CHEVROLET"
        assert "BISCAYNE" in modelo
        assert ano == 1963


# ── sanear_marca_modelo (ficha técnica crua do Mercado Livre) ────────────────

class TestSanearMarcaModelo:
    def test_marca_modelo_colados_no_campo_marca(self):
        # O anunciante põe "Marca Modelo" junto no campo "Marca" do ML — o
        # catálogo separa: CHEVROLET é a marca, OPALA vai pro modelo.
        # "4 Portas" é contagem de portas — sai no saneamento do modelo.
        assert sanear_marca_modelo("Chevrolet Opala", "De Luxe 4 Portas") == (
            "CHEVROLET", "OPALA DE LUXE",
        )
        assert sanear_marca_modelo("Ford Mustang", "GT500") == ("FORD", "MUSTANG GT500")
        # "Cabine estendida" é tipo de cabine, não o modelo — sai no saneamento.
        assert sanear_marca_modelo("Dodge Dakota", "Cabine estendida") == ("DODGE", "DAKOTA")

    def test_modelo_repete_a_marca_sem_duplicar(self):
        # Campo "Modelo" do ML costuma repetir marca+modelo inteiros
        # ("Fiat tipo 1.6 ie") — não pode duplicar, e cilindrada/injeção saem.
        assert sanear_marca_modelo("Fiat tipo", "Fiat tipo 1.6 ie") == ("FIAT", "TIPO")
        assert sanear_marca_modelo("Ford Mustang", "Mustang 3.0 V6") == ("FORD", "MUSTANG")

    def test_typo_de_marca_canonizado(self):
        assert sanear_marca_modelo("Alfa Romeu", "Spider")[0] == "ALFA ROMEO"
        assert sanear_marca_modelo("Volkswagem", "Fusca")[0] == "VOLKSWAGEN"
        assert sanear_marca_modelo("Volkwagen", "Parati")[0] == "VOLKSWAGEN"
        assert sanear_marca_modelo("Porsch", "944 S2")[0] == "PORSCHE"
        assert sanear_marca_modelo("Crysler", "Chambord")[0] == "CHRYSLER"
        assert sanear_marca_modelo("Cadilac Gm", "Fleetwood")[0] == "CADILLAC"

    def test_marca_lixo_recuperada_pelo_modelo(self):
        # Campo "Marca" inútil ("."), mas o "Modelo" tem a marca real.
        assert sanear_marca_modelo(".", "Lincoln Zephyr") == ("LINCOLN", "ZEPHYR")
        assert sanear_marca_modelo("GTW3D80", "Uno ELX 2p")[0] == "FIAT"

    def test_alias_como_selo_marca_real_prevalece(self):
        # "VW Puma" — VW é só o selo do motor; PUMA é a marca real.
        assert sanear_marca_modelo("VW Puma", "GTI")[0] == "PUMA"
        # "1300" é cilindrada — sai do modelo no saneamento (2026-07-17).
        assert sanear_marca_modelo("VW", "Fusca 1300") == ("VOLKSWAGEN", "FUSCA")

    def test_sentinela_e_buggy_preservadas(self):
        # Nunca reinterpretar a sentinela nem a decisão deliberada de BUGGY.
        # Marca preservada, mas o modelo ainda é limpo (2.0 = cilindrada).
        assert sanear_marca_modelo("NAO IDENTIFICADA", "Gsi Gs 2.0") == (
            "NAO IDENTIFICADA", "GSI GS",
        )
        assert sanear_marca_modelo("Buggy", "BRM M8") == ("BUGGY", "BRM M8")

    def test_marca_composta_legitima_preservada(self):
        # Marcas reais de 2 palavras não são quebradas.
        assert sanear_marca_modelo("Am General", "Humvee")[0] == "AM GENERAL"
        assert sanear_marca_modelo("Diamond T", "Model 969-A")[0] == "DIAMOND T"

    def test_marca_ja_limpa_inalterada(self):
        # O saneamento é idempotente pra quem já está correto.
        assert sanear_marca_modelo("Volkswagen", "Fusca") == ("VOLKSWAGEN", "FUSCA")
        assert sanear_marca_modelo("Fiat", "147") == ("FIAT", "147")

    def test_marca_fora_do_catalogo_preservada(self):
        # Marca legítima que não está no CSV de carros (moto/trator/rara)
        # não pode virar lixo nem sentinela.
        assert sanear_marca_modelo("Kawasaki", "Z1000")[0] == "KAWASAKI"
        assert sanear_marca_modelo("Zetor", "5211")[0] == "ZETOR"


# ── sanear_modelo (tirar cauda de spec, manter nome + trim) ──────────────────

class TestSanearModelo:
    def test_corta_cilindrada_valvula_combustivel(self):
        assert sanear_modelo("VOLKSWAGEN", "Gol Geracao III 1.6 Mi 8V Gasolina Mec. 4P") == (
            "GOL GERACAO III"
        )
        assert sanear_modelo("CHEVROLET", "Vectra Gsi 2.0 16V (modelo antigo)") == "VECTRA GSI"
        assert sanear_modelo("FORD", "Escort Xr3 1.8 / 1.6 Conversivel") == "ESCORT XR3"

    def test_fusca_fragmentado_colapsa(self):
        # O caso que motivou a regra: o mesmo Fusca vinha em 5 "modelos".
        assert sanear_modelo("VOLKSWAGEN", "Fusca 1300") == "FUSCA"
        assert sanear_modelo("VOLKSWAGEN", "Fusca 1600") == "FUSCA"
        assert sanear_modelo("VOLKSWAGEN", "Fusca Alcool") == "FUSCA"
        assert sanear_modelo("VOLKSWAGEN", "Fusca Fusca Gasolina") == "FUSCA"
        assert sanear_modelo("VOLKSWAGEN", "Fusca") == "FUSCA"

    def test_portas_por_extenso(self):
        # "4 Portas"/"2 Portas" saem inteiros (número + palavra).
        assert sanear_modelo("CHEVROLET", "Opala De Luxe 4 Portas") == "OPALA DE LUXE"
        assert sanear_modelo("VOLKSWAGEN", "Kombi 2 Portas") == "KOMBI"

    def test_mantem_trim_relevante_pro_preco(self):
        # A usuária decidiu manter trim/versão (pesa no preço de clássico).
        assert sanear_modelo("CHEVROLET", "Vectra Cd") == "VECTRA CD"
        assert sanear_modelo("FORD", "Verona Glx") == "VERONA GLX"
        assert sanear_modelo("VOLKSWAGEN", "Kombi Standard Luxo Serie Prata") == (
            "KOMBI STANDARD LUXO SERIE PRATA"
        )

    def test_numero_que_e_parte_do_nome_e_protegido(self):
        # Número de 2-3 dígitos que é variante do modelo não pode ser cortado
        # como se fosse cilindrada (protegido pelo catálogo ou por ser 1º token).
        assert sanear_modelo("LAND ROVER", "Defender 110") == "DEFENDER 110"
        assert sanear_modelo("MERCEDES-BENZ", "280 SL") == "280 SL"
        assert sanear_modelo("FIAT", "147 1.3") == "147"
        assert sanear_modelo("ZETOR", "5211") == "5211"  # 4 díg. mas é o 1º token

    def test_idempotente(self):
        # Modelo já limpo volta igual.
        assert sanear_modelo("VOLKSWAGEN", "FUSCA") == "FUSCA"
        assert sanear_modelo("FORD", "ESCORT XR3") == "ESCORT XR3"
        assert sanear_modelo("VOLKSWAGEN", "KOMBI STANDARD LUXO SERIE PRATA") == (
            "KOMBI STANDARD LUXO SERIE PRATA"
        )

    def test_cilindrada_colada_ao_nome(self):
        # Cilindrada grudada sem espaço (fonte perdeu o separador) — o ponto
        # decimal denuncia e o corte a remove junto com o resto da cauda.
        assert sanear_modelo("VOLKSWAGEN", "Santana2.0 Gli 8V Gasolina 2P") == "SANTANA"
        assert sanear_modelo("VOLKSWAGEN", "Kombi1.6 Std 8V") == "KOMBI"
        assert sanear_modelo("AUDI", "A62.7 Quattro Avant V6") == "A6"
        assert sanear_modelo("VOLVO", "Xc602.0 T5 Dynamic") == "XC60"

    def test_nome_duplicado_colado(self):
        # Nome do modelo repetido sem espaço num token só.
        assert sanear_modelo("DODGE", "Dartdart") == "DART"
        assert sanear_modelo("FORD", "Belinabelina 1.4 8V") == "BELINA"
        # Trim curto de 2 letras não é colapsado (SS, GT continuam inteiros).
        assert sanear_modelo("CHEVROLET", "Camaro SS") == "CAMARO SS"

    def test_corta_observacao_de_venda_preco_estado(self):
        # Texto livre do anunciante (venda/preço/estado/doc) não é o modelo.
        assert sanear_modelo("CHEVROLET", "Van Preco Promocional") == "VAN"
        assert sanear_modelo("CHEVROLET", "Veraneio Impecavel Carro Reformado") == "VERANEIO"
        assert sanear_modelo("CHEVROLET", "Blazer Dlx 96 Placa Preta") == "BLAZER DLX 96"
        assert sanear_modelo(
            "CHEVROLET", "Opala De Luxo Automatic Original Vende-se Do Atelie Carro"
        ) == "OPALA DE LUXO"
        assert sanear_modelo("BMW", "540i Uma Raridade") == "540I"

    def test_corta_cabine_cilindros_km(self):
        # "cabine estendida" (citada pela usuária), cilindros e km por extenso.
        assert sanear_modelo("CHEVROLET", "S10 Americana Cabine Estendida") == "S10 AMERICANA"
        assert sanear_modelo("CHEVROLET", "D-10 Cabine Dupla") == "D-10"
        assert sanear_modelo("CHEVROLET", "Opala De Luxo 6 Cilindros Com Ar") == "OPALA DE LUXO"
        assert sanear_modelo("CHEVROLET", "Opala 6cc Automatic") == "OPALA"
        assert sanear_modelo("FORD", "Escort Xr3 555 Km") == "ESCORT XR3"

    def test_observacao_nao_destroi_trim_com_de(self):
        # "DE" não é palavra de corte: trims "De Luxo"/"De Luxe" ficam inteiros.
        assert sanear_modelo("CHEVROLET", "Bel Air De Luxe Hardtop") == "BEL AIR DE LUXE HARDTOP"
        assert sanear_modelo("NISSAN", "King Cab") == "KING CAB"  # âncora protege "Cab"

    def test_modelo_vazio(self):
        assert sanear_modelo("FORD", "") == ""
        assert sanear_modelo("", "") == ""


class TestSepararModeloVersaoObs:
    def test_trim_limpo_vira_versao(self):
        assert separar_modelo_versao_obs("CHEVROLET", "Vectra Cd") == ("VECTRA", "CD", None)
        assert separar_modelo_versao_obs("FORD", "Verona Glx") == ("VERONA", "GLX", None)
        assert separar_modelo_versao_obs("CHEVROLET", "Opala De Luxe 4 Portas") == (
            "OPALA", "DE LUXE", None
        )

    def test_sem_trim_versao_e_none(self):
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Fusca") == ("FUSCA", None, None)
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Fusca 1300") == ("FUSCA", None, None)

    def test_geracao_vira_versao_junto_com_trim(self):
        # Usuária decidiu (2026-07-20): geração não é um campo à parte, some
        # dentro da versão.
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Gol Geracao I Cl") == (
            "GOL", "GERACAO I CL", None
        )
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Gol Geracao II") == (
            "GOL", "GERACAO II", None
        )

    def test_carroceria_tracao_vira_obs_nao_descarta(self):
        # Usuária pediu (2026-07-20): carroceria/tração não pode ficar na
        # versão (polui o dropdown) nem ser descartada (perde informação).
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Kombi Pick-Up") == (
            "KOMBI", None, "PICK-UP"
        )
        assert separar_modelo_versao_obs("CHEVROLET", "D-10 Cabine Dupla") == (
            "D-10", None, "CABINE DUPLA"
        )
        assert separar_modelo_versao_obs("CHEVROLET", "S10 Americana Cabine Estendida") == (
            "S10", "AMERICANA", "CABINE ESTENDIDA"
        )

    def test_obs_no_meio_nao_interrompe_captura_da_versao(self):
        # "Sedan" (obs) vem ANTES de "Lx" (versão) — precisa continuar
        # escaneando depois do obs pra não perder o trim.
        assert separar_modelo_versao_obs("HONDA", "Civic Sedan Lx") == ("CIVIC", "LX", "SEDAN")

    def test_cilindrada_grudada_a_letra_de_trim(self):
        # "1300L"/"1600S" (Fusca/Kombi): cilindrada sai, letra de trim fica.
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Fusca 1300L") == ("FUSCA", "L", None)

    def test_spec_pura_e_descartada_nao_vira_obs_nem_versao(self):
        # Cilindrada/válvula/câmbio/combustível continuam sem valor nenhum —
        # obs é só pra carroceria/tração, não vira lixeira geral.
        assert separar_modelo_versao_obs("CHEVROLET", "Vectra Gsi 2.0 16V (modelo antigo)") == (
            "VECTRA", "GSI", None
        )
        assert separar_modelo_versao_obs("FORD", "Escort Xr3 1.8 Conversivel") == (
            "ESCORT", "XR3", None
        )

    def test_bate_com_sanear_modelo_quando_nao_ha_obs(self):
        casos = [
            ("CHEVROLET", "Vectra Cd"),
            ("VOLKSWAGEN", "Fusca 1300"),
            ("CHEVROLET", "Vectra Gsi 2.0 16V (modelo antigo)"),
        ]
        for marca, bruto in casos:
            modelo, versao, obs = separar_modelo_versao_obs(marca, bruto)
            assert obs is None
            combinado = f"{modelo} {versao}".strip() if versao else modelo
            assert combinado == sanear_modelo(marca, bruto)

    def test_digito_solto_como_versao_inteira_e_descartado(self):
        # "Passat 2"/"ES-300 3" vêm assim do próprio título do vendedor
        # (confirmado pela URL do OLX) — um dígito sozinho não é trim de
        # verdade, é ambíguo demais (cilindrada truncada? geração?) pra
        # virar informação de versão.
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Passat 2") == ("PASSAT", None, None)
        assert separar_modelo_versao_obs("MITSUBISHI", "Galant 2") == ("GALANT", None, None)
        # Mas número de 2+ dígitos continua valendo (Galaxie 500, Porsche 964).
        assert separar_modelo_versao_obs("FORD", "Fairlane 500") == ("FAIRLANE", "500", None)

    def test_mercedes_classe_com_letra_fica_no_modelo(self):
        # Auditoria 2026-07-20: só "Classe A" estava no catálogo; as demais
        # letras caíam em modelo="CLASSE" sozinho (e "E" especificamente
        # sumia de vez, colidindo com "E" como conectivo de enumeração).
        assert separar_modelo_versao_obs("MERCEDES-BENZ", "Classe E 3.2 Avantgarde") == (
            "CLASSE E", None, None
        )
        assert separar_modelo_versao_obs("MERCEDES-BENZ", "Classe C Classic") == (
            "CLASSE C", "CLASSIC", None
        )

    def test_numero_colado_a_palavra_e_separado(self):
        # "156Elegant" (espaço perdido no título original) — Elegant é
        # versão, não faz parte do nome "156".
        assert separar_modelo_versao_obs("ALFA ROMEO", "156Elegant") == (
            "156", "ELEGANT", None
        )

    def test_cores_sao_descartadas_nao_viram_versao(self):
        # Usuária pediu (2026-07-20): "cores não são versão, cores não são
        # uma informação aproveitável" — descartada por completo, nem obs.
        assert separar_modelo_versao_obs("CHEVROLET", "Caravan Comodoro Prata") == (
            "CARAVAN", "COMODORO", None
        )
        assert separar_modelo_versao_obs("FIAT", "Tempra Ouro") == ("TEMPRA", None, None)
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Fusca Verde") == ("FUSCA", None, None)

    def test_serie_prata_ouro_sao_edicao_protegida(self):
        # "Série Prata"/"Série Ouro" são edições reais da VW (Fusca/Kombi),
        # não a cor da pintura — só protegidas logo depois de "Série".
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Fusca Serie Ouro") == (
            "FUSCA", "SERIE OURO", None
        )
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Kombi Serie Ouro Verde Nice") == (
            "KOMBI", "SERIE OURO NICE", None
        )

    def test_varredura_geral_palavras_inuteis(self):
        # Motor (spec/sufixo corporativo), aluguel/casamento (frota de
        # eventos, não descreve 1 carro), dono (histórico de venda).
        assert separar_modelo_versao_obs("FORD", "Pampa 93 Motor") == ("PAMPA", "93", None)
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Fusca Itamar 2Dono") == (
            "FUSCA", "ITAMAR 2", None
        )

    def test_titulo_repetido_nao_duplica_modelo_na_versao(self):
        # Título com o modelo mencionado 2x ("Classe Slk ... Classe Slk
        # 230 Kompressor") não pode vazar a repetição pra versão.
        assert separar_modelo_versao_obs(
            "MERCEDES-BENZ", "Classe Slk Mercedes-benz Classe Slk 230 Kompressor"
        ) == ("CLASSE SLK", "230 KOMPRESSOR", None)

    def test_modelo_vazio(self):
        assert separar_modelo_versao_obs("FORD", "") == ("", None, None)


class TestSepararMarcaAsiaKiaMotors:
    def test_asia_motors_absorve_sufixo_na_marca_sempre(self):
        # Usuária pediu (2026-07-20): "no Asia, o nome da marca é Asia
        # Motors" — vale mesmo quando o título não citou "Motors".
        assert inferir_marca_modelo_ano("Asia Motors Hi-Topic Full Diesel") == (
            "ASIA MOTORS", "HI-TOPIC FULL", None
        )
        assert inferir_marca_modelo_ano("Asia Topic 2.7 Luxo") == (
            "ASIA MOTORS", "TOPIC", None
        )

    def test_kia_motors_descarta_sufixo_mantem_marca(self):
        # Mesmo bug do Asia, mas "Kia" já é o nome usual — "Motors" é só
        # ruído a descartar, não vira parte da marca.
        assert inferir_marca_modelo_ano("Kia Motors Besta Gs") == ("KIA", "BESTA GS", None)
        assert inferir_marca_modelo_ano("Kia Besta Gs") == ("KIA", "BESTA GS", None)


class TestToyotaBandeirante:
    def test_grafias_abreviadas_convergem_pro_mesmo_modelo(self):
        # Auditoria 2026-07-20: "Band"/"Band."/"Bandeirantes" fragmentavam
        # o clássico off-road brasileiro em ~240 anúncios de modelos
        # distintos — todas devem convergir pra "BANDEIRANTE".
        casos = [
            "Toyota Band. Jipe 4X4 Sport 3.7 Diesel 1988",
            "Toyota Bandeirantes 4x4 Diesel",
            "Toyota Bandeirante 1991",
        ]
        for titulo in casos:
            marca, modelo, _versao, _obs, _ano = inferir_marca_modelo_versao_obs_ano(titulo)
            assert (marca, modelo) == ("TOYOTA", "BANDEIRANTE")

    def test_abreviacao_colada_com_ponto_e_separada(self):
        # "Band.Picape"/"Band.Jipe" (ponto colado direto na palavra
        # seguinte, sem espaço) — separado antes de canonizar.
        assert separar_modelo_versao_obs("TOYOTA", "Band.Picape Chassi Longo") == (
            "BANDEIRANTE", None, "PICAPE CHASSI LONGO"
        )

    def test_xingu_e_edicao_real_fica_versao(self):
        # "Bandeirante Xingu" foi uma edição real do modelo — não é ruído.
        assert separar_modelo_versao_obs("TOYOTA", "Bandeirante Xingu") == (
            "BANDEIRANTE", "XINGU", None
        )

    def test_abreviacao_e_marca_scoped_nao_vaza_pra_outra_marca(self):
        # "Band" só é abreviação de Bandeirante pra Toyota — outra marca
        # com um token "Band" (hipotético) não deve ser reescrita.
        assert separar_modelo_versao_obs("FORD", "Band Custom") == ("BAND", "CUSTOM", None)
