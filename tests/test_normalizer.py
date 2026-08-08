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
    decompor_versao,
    MARCA_NAO_IDENTIFICADA,
    VERSAO_AGREGADA,
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
        # Entra sem hífen, sai na grafia canônica do catálogo ("KARMANN-GHIA")
        # — agora sanear_modelo também canoniza a grafia, não só
        # separar_modelo_versao_obs (auditoria 2026-07-21, 2ª passada).
        marca, modelo, ano = inferir_marca_modelo_ano("Karmann Ghia 1969")
        assert marca == "VOLKSWAGEN"
        assert modelo == "KARMANN-GHIA"
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
        # "Overland" é só a 2ª metade do nome composto — não é modelo, e
        # descartar os 2 tokens inteiros (não só "Willys") é o que corrige
        # o bug achado na auditoria de existência 2026-07-21 (ver abaixo).
        marca, modelo, ano = inferir_marca_modelo_ano("Willys Overland 1958")
        assert marca == "WILLYS"
        assert "OVERLAND" not in modelo
        assert ano == 1958

    def test_willys_overland_nao_engole_o_modelo_real(self):
        # Bug encontrado na auditoria de existência 2026-07-21: "Overland"
        # sobrava do nome composto da marca e virava o modelo sozinho,
        # perdendo o carro real (Jeep) — 105 anúncios afetados.
        marca, modelo, ano = inferir_marca_modelo_ano(
            "Willys Overland Jeep 2.6 12V Gasolina 2P 1959"
        )
        assert marca == "WILLYS"
        assert modelo == "JEEP"
        assert ano == 1959

    def test_dkw_vemag_nao_engole_o_modelo_real(self):
        # Mesmo bug do Willys Overland, achado no mesmo par de marca
        # composta: "Vemag" é o nome da joint-venture (não um modelo) e
        # sobrava sozinho no lugar de Belcar/Vemaguet (10 anúncios).
        marca, modelo, ano = inferir_marca_modelo_ano(
            "DKW Vemag Vemaguet 1.0 3 Cilindros 2P Manual 1963"
        )
        assert marca == "DKW"
        assert modelo == "VEMAGUET"
        assert ano == 1963

    def test_chevrolet_gm_nao_vira_modelo(self):
        # "Chevrolet - GM <modelo>" — "GM" é eco da marca (fabricante),
        # não modelo. Sem descartar, "GM" virava o modelo e o carro real
        # (Blazer/Opala/Vectra/etc.) se perdia (12 anúncios, auditoria
        # de existência 2026-07-21).
        marca, modelo, ano = inferir_marca_modelo_ano("Chevrolet - GM Blazer 1996")
        assert marca == "CHEVROLET"
        assert modelo == "BLAZER"
        assert ano == 1996

    def test_mercedes_benz_eco_nao_vira_modelo(self):
        # "Mercedes Bens C180"/"Mercedes-Benz Mercedes E430" — eco informal
        # da marca (typo "Bens" incluído) engolindo o modelo real (8
        # anúncios, auditoria de existência 2026-07-21).
        marca, modelo, _ = inferir_marca_modelo_ano("Mercedes Bens C180 Classic")
        assert marca == "MERCEDES-BENZ"
        assert "C180" in modelo or "C 180" in modelo

        marca2, modelo2, _ = inferir_marca_modelo_ano("Mercedes-Benz Mercedes E430")
        assert marca2 == "MERCEDES-BENZ"
        assert "E430" in modelo2 or "E 430" in modelo2

    def test_ford_willys_rural_usa_ano_pra_decidir_marca(self):
        # Ford comprou a Willys-Overland do Brasil em jan/1967 — o catálogo
        # tem "Rural" cadastrado nas duas marcas. Sem resolver, "Willys"
        # ficava preso no modelo (achado na auditoria de existência
        # 2026-07-21, 52 anúncios).
        marca_antes, modelo_antes, _ = inferir_marca_modelo_ano("Ford Willys Rural 4X4 1950")
        assert (marca_antes, modelo_antes) == ("WILLYS", "RURAL 4X4")

        marca_depois, modelo_depois, _ = inferir_marca_modelo_ano("Ford Willys Rural 4X4 1974")
        assert (marca_depois, modelo_depois) == ("FORD", "RURAL 4X4")

    def test_ford_willys_aero_willys_sempre_marca_willys(self):
        # "Aero Willys" só existe no catálogo como WILLYS, nunca como FORD,
        # independente do ano (30 anúncios, auditoria 2026-07-21).
        marca, modelo, _ = inferir_marca_modelo_ano("Ford Willys Aero Willys 2.6 1965")
        assert marca == "WILLYS"
        assert modelo == "AERO-WILLYS"

    def test_jeep_willys_overland_vira_willys_jeep(self):
        # "Jeep Willys Overland"/"Jeep Willys" sem outra pista -> o carro
        # real é o Willys Jeep (9 anúncios, auditoria 2026-07-21).
        marca, modelo, _ = inferir_marca_modelo_ano("Jeep Willys Overland - 1951")
        assert (marca, modelo) == ("WILLYS", "JEEP")

        marca2, modelo2, _ = inferir_marca_modelo_ano("Jeep Willys 1970")
        assert (marca2, modelo2) == ("WILLYS", "JEEP")

    def test_jeep_willys_cj_mantem_marca_jeep(self):
        # Quando o título já nomeia o chassi (CJ-5/CJ6), mantém JEEP e só
        # descarta o eco "Willys".
        marca, modelo, _ = inferir_marca_modelo_ano("Jeep Willys CJ-5 1965")
        assert marca == "JEEP"
        assert "CJ" in modelo

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
        assert sanear_modelo("CHEVROLET", "D-10 Cabine Dupla") == "D10"  # canonizado p/ grafia do catálogo
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

    def test_ss10_vira_s10_versao_ss(self):
        # A usuária apontou (2026-07-23): "SS10" é a S10 com acabamento SS —
        # modelo S10, versão SS (ver _MODELO_EXPANSAO). O token fundido expande
        # pra "S10 SS" na tokenização.
        assert separar_modelo_versao_obs("CHEVROLET", "SS10") == ("S10", "SS", None)
        assert separar_modelo_versao_obs("CHEVROLET", "SS10 Americana") == (
            "S10", "SS AMERICANA", None
        )
        # Não afeta a S10 comum.
        assert separar_modelo_versao_obs("CHEVROLET", "S10 Executive") == (
            "S10", "EXECUTIVE", None
        )

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
        # "D-10" é canonizado pra grafia do catálogo ("D10") — ver
        # canonizar_modelo em catalog/loader.py (auditoria 2026-07-21, 2ª
        # passada: unifica hífen/espaço do mesmo modelo).
        assert separar_modelo_versao_obs("CHEVROLET", "D-10 Cabine Dupla") == (
            "D10", None, "CABINE DUPLA"
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

    def test_carroceria_depois_da_spec_vai_pra_obs(self):
        # Mudou em 2026-08-05: antes o CONVERSIVEL era descartado só por vir
        # DEPOIS da cilindrada — o corte de spec parava ali e a cauda inteira
        # sumia. Agora a cauda é pescada pelo vocabulário do catálogo (ver
        # `_trims_na_cauda`) e a carroceria vai pro campo que sempre foi dela.
        assert separar_modelo_versao_obs("FORD", "Escort Xr3 1.8 Conversivel") == (
            "ESCORT", "XR3", "CONVERSIVEL"
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
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Fusca Verde") == ("FUSCA", None, None)

    def test_cor_que_e_trim_do_catalogo_e_edicao_nao_pintura(self):
        # Mudou em 2026-08-05: "Tempra Ouro" e "Gol Ouro" são edições reais de
        # fábrica, e o catálogo lista OURO como trim desses carros — antes o
        # nome caía na regra geral de cor e sumia (456 anúncios). A exceção é
        # estreita de propósito: vale só pros 11 pares do catálogo em que uma
        # cor é trim (OURO, METAL, PRATA, PRETO). PRATA na Caravan e VERDE no
        # Fusca, acima, continuam descartados — não são trim desses carros.
        assert separar_modelo_versao_obs("FIAT", "Tempra Ouro") == ("TEMPRA", "OURO", None)
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Gol Geracao III Ouro") == (
            "GOL", "GERACAO III OURO", None
        )

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


class TestModeloPuroLixoOuMotorizacao:
    """Usuária pediu (2026-07-20): revisar anúncios com modelo em branco ou
    só motorização — "V8"/"Modelo"/"Com..." sozinho não pode virar modelo."""

    def test_lixo_puro_sem_nada_mais_vira_modelo_vazio(self):
        assert separar_modelo_versao_obs("FORD", "V8") == ("", None, None)
        assert separar_modelo_versao_obs("MERCURY", "V8") == ("", None, None)
        assert separar_modelo_versao_obs("FORD", "Modelo Antigo") == ("", None, None)
        assert sanear_modelo("FORD", "V8") == ""

    def test_numero_ambiguo_sem_mais_nada_continua_protegido(self):
        # "Zetor 5211" — 4 dígitos, mas é o único token: continua sendo o
        # nome do modelo (comportamento já testado antes desta rodada).
        assert separar_modelo_versao_obs("ZETOR", "5211") == ("5211", None, None)
        assert sanear_modelo("ZETOR", "5211") == "5211"

    def test_pula_cilindrada_na_frente_pra_achar_nome_real_no_catalogo(self):
        # "Puma 1.6 Gte" — a cilindrada vem ANTES do nome real (Gte, Gts,
        # Gtb são trims cadastrados no catálogo da Puma).
        assert separar_modelo_versao_obs("PUMA", "Puma 1976 1.6 Gte 2p") == (
            "GTE", None, None
        )
        assert separar_modelo_versao_obs("PUMA", "Puma 1980 4.1 Gtb 2p") == (
            "GTB", None, None
        )

    def test_numero_e_nome_comercial_real_fica_protegido_no_catalogo(self):
        # 2CV/4CV/Jaguar 3.4-3.8/Santa Matilde 4.1: o número É o nome do
        # modelo por convenção histórica da marca, não motorização. O ponto
        # do teste é que sobrevivem como modelo (não viram vazio); a grafia
        # segue o catálogo — o CSV base grafa "2 CV" com espaço.
        assert separar_modelo_versao_obs("CITROEN", "2CV") == ("2 CV", None, None)
        assert separar_modelo_versao_obs("RENAULT", "4CV") == ("4CV", None, None)
        assert separar_modelo_versao_obs("JAGUAR", "3.4") == ("3.4", None, None)
        assert separar_modelo_versao_obs("JAGUAR", "3.8") == ("3.8", None, None)
        assert separar_modelo_versao_obs("SANTA MATILDE", "4.1") == ("4.1", None, None)


class TestCanonizacaoGrafiaModelo:
    """
    Auditoria 2026-07-21 (2ª passada): unificar as grafias hífen/espaço do
    mesmo modelo na grafia do catálogo, pra não fragmentar os grupos
    (a usuária apontou 'várias grafias de Willys', VW-FUSCA-1300 etc.).
    """

    def test_hifen_vira_grafia_do_catalogo(self):
        # Chevrolet grafa D20/C10 juntos no catálogo; anúncios usam D-20/C-10.
        assert sanear_modelo("CHEVROLET", "D-20") == "D20"
        assert sanear_modelo("CHEVROLET", "C-10") == "C10"
        assert separar_modelo_versao_obs("CHEVROLET", "D-20")[0] == "D20"

    def test_junto_vira_grafia_espacada_do_catalogo(self):
        # Mercedes grafa "C 180" com espaço; anúncios usam C-180/C180.
        assert sanear_modelo("MERCEDES-BENZ", "C-180") == "C 180"
        assert sanear_modelo("MERCEDES-BENZ", "C180") == "C 180"

    def test_belair_deluxe_deville_pickup(self):
        assert sanear_modelo("CHEVROLET", "Belair") == "BEL AIR"
        assert sanear_modelo("CADILLAC", "Deville") == "DE VILLE"
        assert sanear_modelo("FORD", "Pickup") == "PICK UP"

    def test_modelo_com_trim_nao_e_tocado(self):
        # Só o modelo inteiro é canonizado; nome+trim que não bate no
        # catálogo volta inalterado (sem risco de estragar trim).
        assert sanear_modelo("CHEVROLET", "Vectra Gsi") == "VECTRA GSI"


class TestModeloConhecidoGrudado:
    """
    Auditoria 2026-07-21 (2ª passada): modelo do catálogo grudado ao resto
    ('VW-FUSCA-1300', 'ESCORTXR3') — a usuária apontou o VW-FUSCA-1300.
    """

    def test_modelo_grudado_a_cilindrada(self):
        assert inferir_marca_modelo_ano("VW Fusca1300 1975")[1] == "FUSCA"
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Fusca1300") == ("FUSCA", None, None)

    def test_modelo_grudado_a_trim(self):
        assert separar_modelo_versao_obs("FORD", "EscortXr3") == ("ESCORT", "XR3", None)

    def test_modelo_grudado_a_palavra(self):
        assert separar_modelo_versao_obs("CHEVROLET", "ImpalaWagon")[0] == "IMPALA"

    def test_nome_de_modelo_maior_nao_e_quebrado(self):
        # "GOLF" não pode virar "GOL F" (GOL é modelo, mas GOLF também é).
        assert inferir_marca_modelo_ano("Volkswagen Golf 2000")[1] == "GOLF"


class TestTyposWillys:
    """Auditoria 2026-07-21 (2ª passada): 'várias grafias de Willys'."""

    def test_typo_willys_vira_willys_jeep(self):
        assert inferir_marca_modelo_ano("Jeep Wilys Ano 1964")[:2] == ("WILLYS", "JEEP")
        assert inferir_marca_modelo_ano("Jeep Wyllis")[:2] == ("WILLYS", "JEEP")
        assert inferir_marca_modelo_ano("Jeep Willis gasolina 1973")[:2] == ("WILLYS", "JEEP")


class TestVolkswagenRevisaoGeral:
    """Usuária pediu (2026-07-20): revisar todos os modelos Volkswagen."""

    def test_carroceria_na_frente_nao_vira_modelo(self):
        # "Perua Kombi" — a busca de âncora pulava só spec/cilindrada solto
        # na frente, não carroceria; "PERUA" virava modelo em vez de achar
        # "KOMBI" depois.
        # Nota: a carroceria pulada na frente da âncora é descartada, não
        # vira obs (obs só captura o que sobra DEPOIS do nome do modelo) —
        # comportamento aceito dado o volume baixo desse padrão invertido.
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Perua Kombi") == (
            "KOMBI", None, None
        )

    def test_cilindrada_colada_a_trim_na_frente_nao_vira_modelo(self):
        # "Fuscão 1600s" — "1600S" (cilindrada + letra de trim colados) não
        # batia em nenhum padrão de spec por palavra, então quebrava a
        # busca de âncora antes de achar "Fusca" mais à frente no título.
        assert separar_modelo_versao_obs("VOLKSWAGEN", "1600S Fusca") == (
            "FUSCA", None, None
        )

    def test_apelidos_e_typos_convergem_pro_modelo_do_catalogo(self):
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Fuscão") == ("FUSCA", None, None)
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Fusquinha") == ("FUSCA", None, None)
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Apolo Gl") == ("APOLLO", "GL", None)
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Braslia") == ("BRASILIA", None, None)
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Voyagem") == ("VOYAGE", None, None)
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Karmann-guia") == (
            "KARMANN-GHIA", None, None
        )

    def test_duas_grafias_catalogadas_do_mesmo_modelo_convergem(self):
        # "Karmann Ghia" (espaço) e "Karmann-Ghia" (hífen) são as duas
        # formas cadastradas no catálogo — sem canonizar, fragmentavam o
        # mesmo modelo em dois grupos.
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Karmann Ghia Coupe") == (
            "KARMANN-GHIA", None, "COUPE"
        )
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Karmann-Ghia TC") == (
            "KARMANN-GHIA", "TC", None
        )

    def test_voiage_sem_prefixo_de_marca_ainda_vira_modelo_voyage(self):
        # "VOIAGE" tinha alias de MARCA que consumia o token — "Voiage
        # Argentino" perdia "Voyage" do modelo, sobrava só "Argentino".
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Voiage Argentino") == (
            "VOYAGE", "ARGENTINO", None
        )

    def test_modelo_colado_ao_trim_sem_separador(self):
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Golcl 1.6") == ("GOL", None, None)
        assert separar_modelo_versao_obs("VOLKSWAGEN", "Saveirocl 1.6") == (
            "SAVEIRO", None, None
        )


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


# ── decompor_versao (auditoria de versão 2026-08-04) ────────────

class TestDecomporVersaoGeracao:
    def test_geracao_por_extenso_sai_do_campo_versao(self):
        # O caso que motivou a auditoria: o mesmo trim "CL" do Gol aparecia
        # em quatro grupos por vir grudado à geração e à motorização.
        assert decompor_versao("VOLKSWAGEN", "GOL", "GERACAO I CL") == (
            "CL", "I", None, None
        )
        assert decompor_versao("VOLKSWAGEN", "GOL", "GERACAO II CL") == (
            "CL", "II", None, None
        )

    def test_geracao_abreviada_e_apelido_convergem_pro_romano(self):
        # "G.III" é a grafia do catálogo, "G3" a dos anúncios e "quadrado"/
        # "bola" os apelidos populares — todos viram o mesmo romano.
        assert decompor_versao("VOLKSWAGEN", "GOL", "G3")[1] == "III"
        assert decompor_versao("VOLKSWAGEN", "GOL", "G.III")[1] == "III"
        assert decompor_versao("VOLKSWAGEN", "GOL", "BOLA")[1] == "III"
        assert decompor_versao("VOLKSWAGEN", "GOL", "QUADRADO")[1] == "I"

    def test_g_mais_romano_de_uma_letra_colado_nao_e_geracao(self):
        # "GV"/"GI"/"GX" são trim de verdade em vários carros — o Nissan
        # Maxima "30GV/GV" virava "geração V" (achado conferindo as gerações
        # gravadas depois do primeiro reprocessamento). Romano de uma letra
        # só conta com o ponto separando.
        assert decompor_versao("NISSAN", "MAXIMA", "30GV GV AERO")[1] is None
        assert decompor_versao("VOLKSWAGEN", "GOL", "GV")[1] is None
        assert decompor_versao("VOLKSWAGEN", "GOL", "G.V")[1] == "V"
        # Dígito e romano de 2+ letras não têm essa ambiguidade.
        assert decompor_versao("VOLKSWAGEN", "GOL", "GII")[1] == "II"

    def test_apelido_de_geracao_e_scoped_por_modelo(self):
        # "Bola"/"quadrado" só são geração no Gol — noutro carro seguem
        # como texto normal, sem virar geração.
        assert decompor_versao("FORD", "ESCORT", "BOLA")[1] is None


class TestDecomporVersaoMotor:
    def test_spec_da_webmotors_vira_campo_motor(self):
        # A Webmotors gravava `Version.Value` cru: era a única fonte da base
        # com esse formato (5.060 versões). O trim fica na versão e a
        # motorização vai pro campo próprio; câmbio e portas seguem
        # descartados, como sempre foram.
        assert decompor_versao("VOLKSWAGEN", "GOL", "1.6 CL 8V GASOLINA 2P MANUAL") == (
            "CL", None, "1.6 8V GASOLINA", None
        )

    def test_acento_e_barra_da_webmotors_normalizam(self):
        # "ÁLCOOL"/"COUPÉ"/"SL/E" vinham crus e não casavam com nada do
        # resto da base (1.418 com acento, 101 com barra).
        assert decompor_versao("VOLKSWAGEN", "GOL", "1.8 GTS 8V ÁLCOOL 2P MANUAL") == (
            "GTS", None, "1.8 8V ALCOOL", None
        )
        # "SL/E" é nomenclatura de UMA versão (Chevette/Opala): a barra vira
        # espaço e o "E" solto seria descartado como conectivo, sobrando um
        # "SL" que é outra versão. As três grafias da base convergem.
        assert decompor_versao("CHEVROLET", "OPALA", "SL/E")[0] == "SLE"
        assert decompor_versao("CHEVROLET", "OPALA", "SL E")[0] == "SLE"
        assert decompor_versao("CHEVROLET", "OPALA", "SLE")[0] == "SLE"

    def test_cilindrada_em_cc_vira_litros(self):
        # O mesmo Fusca aparecia como "1300" e como "1.3" — mesma
        # informação, unidades diferentes, dois grupos.
        assert decompor_versao("VOLKSWAGEN", "FUSCA", "1300")[2] == "1.3"
        assert decompor_versao("VOLKSWAGEN", "FUSCA", "1.3")[2] == "1.3"
        # Cilindrada grudada na letra de trim: cada uma pro seu campo.
        assert decompor_versao("VOLKSWAGEN", "FUSCA", "1300L") == (
            "L", None, "1.3", None
        )


class TestDecomporVersaoTrimCatalogo:
    def test_abreviacao_canoniza_pela_grafia_do_catalogo(self):
        # Truncamentos que a OLX/Webmotors produzem e que viravam grupos
        # órfãos: o vocabulário de trim do catálogo resolve por prefixo.
        assert decompor_versao("CHEVROLET", "OPALA", "COMOD")[0] == "COMODORO"
        assert decompor_versao("CHEVROLET", "OPALA", "DIPLOM")[0] == "DIPLOMATA"
        assert decompor_versao("VOLKSWAGEN", "PASSAT", "VILL")[0] == "VILLAGE"

    def test_sinonimo_sem_relacao_de_prefixo(self):
        # "STANDARD" x "STD" não é prefixo — precisa da tabela de sinônimo.
        assert decompor_versao("VOLKSWAGEN", "KOMBI", "STANDARD")[0] == "STD"

    def test_truncamento_da_olx_canoniza_pelo_nome_real(self):
        # "Vectra GLS/expres.2.2" — o truncamento vira o nome comercial de
        # verdade (Vectra Expression), que está no catálogo.
        assert decompor_versao("CHEVROLET", "VECTRA", "EXPRES")[0] == "EXPRESSION"

    def test_trim_que_o_catalogo_grafa_junto_e_fundido(self):
        # "Hard Top" separado no anúncio, "HARDTOP" no catálogo. Sem a fusão,
        # o "HARD" expandia por prefixo pra HARDTOP e o "TOP" sobrava
        # ("K CODE HARDTOP TOP" — achado no smoke test).
        assert decompor_versao("FORD", "MUSTANG", "K CODE HARD TOP")[0] == (
            "K CODE HARDTOP"
        )

    def test_trim_desconhecido_do_catalogo_e_preservado(self):
        # O catálogo não cobre tudo; o que ele não conhece segue como está
        # e cai na quarentena do painel, não é apagado nem chutado.
        assert decompor_versao("CHEVROLET", "OPALA", "ITAMAR")[0] == "ITAMAR"


class TestDecomporVersaoSobras:
    def test_carroceria_vai_pra_obs_e_nao_fragmenta_o_trim(self):
        # O mesmo "GL" virava "GL", "GL SW" e "GL HATCH" em três grupos.
        assert decompor_versao("FORD", "ESCORT", "GL SW") == ("GL", None, None, "SW")
        assert decompor_versao("CHEVROLET", "MONZA", "L HATCH") == (
            "L", None, None, "HATCH"
        )

    def test_nome_do_modelo_repetido_na_versao_e_descartado(self):
        # 193 anúncios tinham versao == modelo.
        assert decompor_versao("CHEVROLET", "BLAZER", "BLAZER DLX")[0] == "DLX"
        assert decompor_versao("VOLKSWAGEN", "FUSCA", "FUSCA")[0] is None

    def test_cor_continua_descartada_menos_serie_prata(self):
        # Decisão da usuária de 2026-07-20, preservada aqui.
        assert decompor_versao("VOLKSWAGEN", "GOL", "VERMELHO")[0] is None
        assert decompor_versao("VOLKSWAGEN", "FUSCA", "SERIE OURO")[0] == "SERIE OURO"

    def test_obs_que_ja_vinha_preenchida_e_mantida(self):
        versao, _ger, _mot, obs = decompor_versao(
            "CHEVROLET", "S10", "AMERICANA", "CABINE ESTENDIDA"
        )
        assert versao == "AMERICANA"
        assert obs == "CABINE ESTENDIDA"


class TestVersaoAgregada:
    def test_enumeracao_da_taxonomia_vira_sentinela(self):
        # O título da OLX não é do anúncio: é o rótulo da linha inteira,
        # enumerando todas as versões. A versão real não existe (7.823
        # anúncios) — melhor a sentinela do que fingir que "L SL" é um trim.
        assert decompor_versao(
            "VOLKSWAGEN", "PASSAT", "L LS LSE GL GLS TS FLA VILL PLUS",
            titulo="Volkswagen Passat L/ LS/ LSE/ GL/ GLS/ TS/ FLA/ VILL/ PLUS 1984",
        )[0] == VERSAO_AGREGADA
        assert decompor_versao(
            "CHEVROLET", "CHEVETTE", "L SL",
            titulo="Chevrolet Chevette L / SL / Sl/e / DL / SE 1.6 1987",
        )[0] == VERSAO_AGREGADA

    def test_geracao_e_motor_sobrevivem_a_enumeracao(self):
        # A fonte agrupa o TRIM, não a geração nem o motor — esses dois
        # continuam válidos e não devem ser perdidos junto.
        versao, geracao, motor, _obs = decompor_versao(
            "VOLKSWAGEN", "GOL", "GERACAO I CL GTI 1.6",
            titulo="Volkswagen Gol Geração I CL/ GTI 1.6 1991",
        )
        assert versao == VERSAO_AGREGADA
        assert (geracao, motor) == ("I", "1.6")

    def test_barra_entre_cilindradas_nao_e_enumeracao(self):
        # "4.1/2.5" e "1.8i / 1.8" são motorização, não lista de versões.
        assert decompor_versao(
            "FORD", "PAMPA", "L", titulo="Ford Pampa L 1.8i / 1.8 1997",
        )[0] == "L"
        assert decompor_versao(
            "CHEVROLET", "CARAVAN", "COMODORO",
            titulo="Chevrolet Caravan Comodoro 4.1/2.5 1988",
        )[0] == "COMODORO"

    def test_abreviacao_da_mesma_versao_nao_e_enumeracao(self):
        # "Diplomata/diplom." é a mesma versão escrita duas vezes — os dois
        # lados canonizam pro mesmo trim, então não conta como lista.
        assert decompor_versao(
            "CHEVROLET", "OPALA", "DIPLOMATA DIPLOM SLE",
            titulo="Chevrolet Opala Diplomata/diplom. SLE 4.1/2.5 1988",
        )[0] == "DIPLOMATA SLE"

    def test_barra_como_com_ou_separador_solto_nao_e_enumeracao(self):
        # Achados no smoke test do reprocessamento: a barra também é usada
        # como "com" ("C/ reboque") e como separador qualquer ("JrP/
        # restauração"). Nenhum dos lados é trim do catálogo.
        assert decompor_versao(
            "JEEP", "MUTT4CC", "C REBOQUE", titulo="Jeep Mutt4cc - C/ reboque",
        )[0] == "C REBOQUE"
        assert decompor_versao(
            "KAISER", "HENRY", "JRP RESTAURACAO", titulo="Henry  JrP/ restauração",
        )[0] == "JRP RESTAURACAO"

    def test_nomenclatura_de_uma_versao_com_barra_nao_e_enumeracao(self):
        # "R/T" (Road/Track da Dodge) é UMA versão, como o "SL/E" — vira um
        # token só antes de o detector rodar.
        assert decompor_versao(
            "DODGE", "CHARGER", "R T", titulo="Dodge Charger R/T 1970",
        )[0] == "RT"

    def test_marca_barra_modelo_nao_e_enumeracao(self):
        # "Vw/gol" é a grafia de marca/modelo da OLX, não uma lista.
        assert decompor_versao(
            "VOLKSWAGEN", "GOL", "CL", titulo="Vw/gol Cl 1.6 1991",
        )[0] == "CL"

    def test_sentinela_e_preservada_em_reprocessamento(self):
        # Idempotência: rodar de novo sobre o que já foi gravado não pode
        # reinterpretar a sentinela como se fosse um trim chamado "VERSAO".
        assert decompor_versao("VOLKSWAGEN", "GOL", VERSAO_AGREGADA) == (
            VERSAO_AGREGADA, None, None, None
        )


class TestDecomporVersaoIdempotente:
    # Casos que exercitam os quatro eixos e as duas rodadas de canonização.
    CASOS = [
        ("VOLKSWAGEN", "GOL", "GERACAO I CL", None, None),
        ("VOLKSWAGEN", "GOL", "1.6 CL 8V GASOLINA 2P MANUAL", None, None),
        ("FORD", "ESCORT", "GL SW", None, None),
        ("CHEVROLET", "OPALA", "COMOD", None, None),
        ("VOLKSWAGEN", "FUSCA", "1300L", None, None),
        ("FIAT", "FIORINO", "FURG", None, None),
        ("CHEVROLET", "CAMARO", "Z-28 TARGA CONV", None, None),
        ("VOLKSWAGEN", "PASSAT", "L LS GL", None,
         "Volkswagen Passat L/ LS/ GL 1984"),
    ]

    def test_segunda_passada_devolve_o_mesmo_resultado(self):
        # O reprocessamento retroativo roda em cima do que já está gravado,
        # realimentando os QUATRO campos — é assim que a estabilidade tem de
        # ser medida. Comparar só versão/obs escondia dois bugs reais: a
        # geração e o motor sumiam por não voltarem como entrada, e a
        # carroceria que só aparece depois de canonizada ("FURG" -> FURGAO,
        # "CONV" -> CONVERSIVEL) migrava pra obs só na 2ª rodada.
        for marca, modelo, versao, obs, titulo in self.CASOS:
            r1 = decompor_versao(marca, modelo, versao, obs, titulo)
            r2 = decompor_versao(marca, modelo, r1[0], r1[3], titulo, r1[1], r1[2])
            assert r1 == r2, f"{marca} {modelo} {versao!r}: {r1} != {r2}"

    def test_geracao_e_motor_ja_gravados_sobrevivem(self):
        # O caso direto do que o reprocessamento faz: a versão já está limpa
        # e os eixos moram nas colunas próprias.
        assert decompor_versao(
            "VOLKSWAGEN", "GOL", "CL", None, None, "I", "1.6 8V GASOLINA"
        ) == ("CL", "I", "1.6 8V GASOLINA", None)

    def test_eixo_vindo_da_versao_vence_o_ja_gravado(self):
        # Se a versão traz o eixo de novo (recoleta com dado melhor), o que
        # sai dela é o que vale.
        assert decompor_versao(
            "VOLKSWAGEN", "GOL", "GERACAO II CL", None, None, "I", None
        ) == ("CL", "II", None, None)

    def test_carroceria_canonizada_sai_da_versao_na_primeira_passada(self):
        # "Furg."/"conv." são expandidos pelo vocabulário do catálogo; depois
        # de expandidos são carroceria, e carroceria vai pra obs.
        assert decompor_versao("FIAT", "FIORINO", "FURG") == (
            None, None, None, "FURGAO"
        )
        assert decompor_versao("CHEVROLET", "CAMARO", "Z-28 TARGA CONV") == (
            "Z-28 TARGA", None, None, "CONVERSIVEL"
        )

    def test_numero_baixo_nao_vira_cilindrada(self):
        # "500"/"600"/"964" são nome de modelo ou código de chassi, não motor
        # (Honda CB 500, Yamaha Teneré 600, Porsche 911 "964").
        assert decompor_versao("HONDA", "CB 500", "500 FOUR")[2] is None
        assert decompor_versao("PORSCHE", "911", "CARRERA 4 964")[2] is None
        # Quatro dígitos a partir de 1000 continuam sendo cilindrada.
        assert decompor_versao("VOLKSWAGEN", "FUSCA", "1600")[2] == "1.6"

    def test_versao_vazia_ou_none(self):
        assert decompor_versao("VOLKSWAGEN", "GOL", None) == (None, None, None, None)
        assert decompor_versao("VOLKSWAGEN", "GOL", "") == (None, None, None, None)
        assert decompor_versao("VOLKSWAGEN", "GOL", "  ") == (None, None, None, None)


# ── auditoria de versão 2026-08-05: bugs achados cruzando o campo `versao`
#    do banco com o vocabulário de trim do catálogo ────────────────────────

class TestVersaoConectivoSolto:
    """
    "Toyota Band.Jipe Cap.de Aço Chas. Curto Diesel" gravava versão "DE" em
    83 anúncios: o corte de spec comia CAPOTA e AÇO e sobrava a preposição.
    Nenhum trim começa ou termina com preposição.
    """

    def test_preposicao_sozinha_nao_e_versao(self):
        assert decompor_versao("TOYOTA", "BANDEIRANTE", "DE")[0] is None

    def test_preposicao_na_ponta_e_aparada(self):
        assert decompor_versao("DODGE", "DART", "DE LUXO")[0] == "LUXO"

    def test_preposicao_no_meio_fica(self):
        # Só as pontas são aparadas — frase composta continua inteira.
        assert decompor_versao("FORD", "GALAXIE", "LTD LANDAU")[0] == "LTD LANDAU"

    def test_nome_de_carro_com_preposicao_nao_vira_trim_inventado(self):
        # "Cadillac Sedan de Ville": podar o DE primeiro criaria o trim
        # 'VILLE', que nunca existiu. A checagem de modelo vazado roda antes
        # justamente por isso (dry-run 2026-08-05).
        assert decompor_versao("CADILLAC", "SEDAN", "DE VILLE")[0] is None
        assert decompor_versao("CADILLAC", "COUPE", "DE VILLE")[0] is None


class TestVersaoMarcaOuModeloVazando:
    def test_alias_de_marca_nao_e_versao(self):
        # "Volkswagen Fusca 1965 Vw Fusca 1200": a marca gravada é
        # VOLKSWAGEN, o título escreve "Vw" — sem o alias, virava versão.
        assert decompor_versao("VOLKSWAGEN", "FUSCA", "VW")[0] is None

    def test_modelo_com_hifen_nao_e_versao(self):
        # 'AERO-WILLYS' era um token só; 'AERO' não era visto como repetição.
        assert decompor_versao("WILLYS", "AERO-WILLYS", "AERO")[0] is None

    def test_outro_modelo_da_marca_nao_e_versao(self):
        assert decompor_versao("CHEVROLET", "BLAZER", "S-10")[0] is None

    def test_mas_nome_que_e_trim_legitimo_sobrevive(self):
        # Guarda contra a regra acima virar destruidora: o catálogo lista
        # BLAZER como trim real da F-1000 (existiu uma F-1000 Blazer).
        assert decompor_versao("FORD", "F-1000", "BLAZER")[0] == "BLAZER"

    def test_nome_de_modelo_dentro_de_frase_maior_sobrevive(self):
        # Achado no smoke test: a 1ª versão da regra testava token a token e
        # comia o CHEYENNE de "Suburban Cheyenne Super 20" (Cheyenne é
        # modelo Chevrolet E trim de Suburban). Só a versão INTEIRA conta.
        assert (decompor_versao("CHEVROLET", "SUBURBAN", "CHEYENNE SUPER 20V8")[0]
                == "CHEYENNE SUPER 20V8")
        assert (decompor_versao("CHEVROLET", "VERANEIO", "CUSTOM DELUXE")[0]
                == "CUSTOM DELUXE")

    def test_vazamento_de_duas_palavras(self):
        assert decompor_versao("FORD", "BELINA", "DEL REY")[0] is None
        assert decompor_versao("VOLKSWAGEN", "SANTANA", "QUANTUM")[0] is None


class TestVersaoSeparadorNoCatalogo:
    """
    O CSV do catálogo grafa "R/T" e "SL/E"; a barra virava espaço e o
    vocabulário ficava com 'R'+'T' e 'SL'+'E' soltos, enquanto o anúncio
    chegava como 'RT'/'SLE' e não casava com nada (112 anúncios).
    """

    def test_rt_casa_no_catalogo(self):
        assert decompor_versao("DODGE", "CHARGER", "R/T")[0] == "RT"
        assert decompor_versao("DODGE", "CHARGER", "RT")[0] == "RT"

    def test_sle_casa_no_catalogo(self):
        assert decompor_versao("CHEVROLET", "MONZA", "SL/E")[0] == "SLE"
        assert decompor_versao("CHEVROLET", "MONZA", "SLE")[0] == "SLE"

    def test_frase_composta_com_separador(self):
        assert decompor_versao("CHEVROLET", "OPALA", "COMODORO SL/E")[0] == "COMODORO SLE"


class TestVersaoInjecaoAgregada:
    def test_ia_e_spec_nao_trim(self):
        # "BMW 328I /IA (modelo Antigo)" — forma agregada da OLX pro câmbio.
        assert decompor_versao("BMW", "328I", "IA")[0] is None


class TestVersaoTrimForaDoCatalogoPreservado:
    """
    O catálogo da Webmotors é incompleto: Corcel II L, Belina L e S10 Luxe
    são trims reais de fábrica que ele não lista. Nenhuma das regras novas
    pode apagá-los — não casar com o catálogo não é motivo pra descartar.
    """

    def test_corcel_ii_l(self):
        assert decompor_versao("FORD", "CORCEL II", "L")[0] == "L"

    def test_belina_l(self):
        assert decompor_versao("FORD", "BELINA", "L")[0] == "L"

    def test_s10_luxe(self):
        assert decompor_versao("CHEVROLET", "S10", "LUXE")[0] == "LUXE"


class TestVersaoRegrasNovasIdempotentes:
    CASOS = [
        ("TOYOTA", "BANDEIRANTE", "DE"),
        ("DODGE", "DART", "DE LUXO"),
        ("VOLKSWAGEN", "FUSCA", "VW"),
        ("WILLYS", "AERO-WILLYS", "AERO"),
        ("CHEVROLET", "BLAZER", "S-10"),
        ("DODGE", "CHARGER", "R/T"),
        ("CHEVROLET", "MONZA", "SL/E"),
        ("FORD", "F-1000", "BLAZER"),
        ("FORD", "CORCEL II", "L"),
    ]

    def test_segunda_passada_devolve_o_mesmo(self):
        for marca, modelo, versao in self.CASOS:
            r1 = decompor_versao(marca, modelo, versao)
            r2 = decompor_versao(marca, modelo, r1[0], r1[3], None, r1[1], r1[2])
            assert r1 == r2, f"{marca} {modelo} {versao!r}: {r1} != {r2}"


class TestTrimNaCaudaDaSpec:
    """
    O corte de spec para no primeiro token de spec, porque é ali que o NOME
    do modelo acaba. Mas em muitos títulos o trim vem DEPOIS da cilindrada e
    ficava perdido — 3.284 anúncios (23% dos que estavam sem versão) na
    medição de 2026-08-05. `_trims_na_cauda` pesca esses de volta.
    """

    def test_trim_depois_da_cilindrada_e_recuperado(self):
        assert inferir_marca_modelo_versao_obs_ano(
            "Chevrolet Blazer 1997 4.3 V6 Dlx 5p")[2] == "DLX"
        assert inferir_marca_modelo_versao_obs_ano(
            "Volkswagen Gol 1.8 Mi Gl 8v Gasolina 2p Manual")[2] == "GL"
        assert inferir_marca_modelo_versao_obs_ano(
            "Honda Civic 1.6 Lx 16v Gasolina 4p Automatico")[2] == "LX"
        assert inferir_marca_modelo_versao_obs_ano(
            "Chevrolet Opala 4.1 Diplomata 12v Gasolina 4p")[2] == "DIPLOMATA"

    def test_trim_antes_da_spec_segue_funcionando(self):
        assert inferir_marca_modelo_versao_obs_ano(
            "Ford Escort Xr3 1.6 Alcool")[2] == "XR3"

    def test_titulo_so_com_spec_nao_ganha_versao(self):
        """A regra não pode INVENTAR versão onde a fonte não deu nenhuma."""
        for titulo in (
            "Volkswagen Fusca 1.3 8V Gasolina 2P Manual 1981",
            "VOLKSWAGEN FUSCA 1.6 8V GASOLINA 2P MANUAL 1986",
            "Toyota Paseo 1994 1.5 16v",
            "Volkswagen Fusca 1300 1970",
        ):
            assert inferir_marca_modelo_versao_obs_ano(titulo)[2] is None, titulo

    def test_lixo_da_cauda_nao_entra(self):
        """
        A cauda é onde mora o texto de venda. Só entra o que o catálogo
        avaliza como trim daquele carro — é essa exigência que permite
        pescar ali sem trazer o resto.
        """
        for titulo in (
            "Chevrolet Opala 4.1 Aceito troca parcelo entrada",
            "Ford Corcel II 1.6 Otimo estado documentado 1980",
        ):
            assert inferir_marca_modelo_versao_obs_ano(titulo)[2] is None, titulo

    def test_cilindrada_nao_casa_por_prefixo_com_trim(self):
        """
        Regressão: o catálogo tem o trim '1.8S' no Gol, e a expansão por
        prefixo de `canonizar_trim` casava a cilindrada '1.8' com ele,
        devolvendo versão '1.8 GL'.
        """
        assert inferir_marca_modelo_versao_obs_ano(
            "Volkswagen Gol 1.8 Mi Gl 8v Gasolina 2p Manual")[2] == "GL"

    def test_conectivo_entre_dois_trims_e_preservado(self):
        """
        'CUSTOM DE LUXE' é o nome real do trim da D20/Veraneio/Bonanza. O DE
        não está no vocabulário — sozinho não é trim nenhum, e enquanto
        esteve lá virou versão "DE" na Bandeirante —, mas tirá-lo daqui
        produziria "CUSTOM LUXE", nome de carro que não existe. A ponte só
        vale entre dois trims aceitos e adjacentes (2026-08-07).
        """
        assert inferir_marca_modelo_versao_obs_ano(
            "Chevrolet D20 4.0 Custom De Luxe Cs 8v Diesel 2p Manual"
        )[2] == "CUSTOM DE LUXE CS"
        assert inferir_marca_modelo_versao_obs_ano(
            "CHEVROLET VERANEIO 4.1 CUSTOM DE LUXE 12V GASOLINA 4P MANUAL 1993"
        )[2] == "CUSTOM DE LUXE"


class TestLixoDoVocabularioDeTrim:
    """
    O vocabulário sai da coluna `nome_versao` da Webmotors, e três formas de
    spec escapavam dos filtros dela porque só se reconhecem pelo token
    VIZINHO. `_trims_na_cauda` então pescava o lixo de volta, porque a regra
    dele é justamente "confio no que o catálogo avaliza" (auditoria
    2026-08-07, achada ao exportar a aba "Sem versão": os trims "perdidos"
    que sobravam eram '6', 'I' e 'DE').

    Estes casos são de ponta a ponta de propósito: o que importa não é o
    conteúdo do índice, é que o título deixe de virar versão errada.
    """

    def test_numero_de_cilindros_nao_e_versao(self):
        for titulo in (
            "WILLYS JEEP 2.6 6 CILINDROS 12V GASOLINA 2P MANUAL 1942",
            "MERCEDES-BENZ 280 SE 2.8 6 CILINDROS GASOLINA 4P AUTOMATICO 1968",
            "PUMA GTB 4.1 COUPE 6 CILINDROS 12V GASOLINA 2P MANUAL 1977",
        ):
            assert inferir_marca_modelo_versao_obs_ano(titulo)[2] is None, titulo

    def test_numero_que_e_trim_de_verdade_continua(self):
        """
        Por isso a regra é posicional e não "dígito solto nunca é trim":
        'CARRERA 4' (tração integral) e 'MACH 1' são nome de versão, e o que
        separa do '6' de '6 CILINDROS' é só o vizinho.
        """
        assert inferir_marca_modelo_versao_obs_ano(
            "PORSCHE 911 3.6 CARRERA 4 COUPE 6 CILINDROS 24V GASOLINA 2P MANUAL 1990"
        )[2] == "CARRERA 4"
        assert inferir_marca_modelo_versao_obs_ano(
            "FORD A 0.8 4 CILINDROS PHAETON 4P GASOLINA MANUAL 1929"
        )[2] == "PHAETON"

    def test_i_de_injecao_depois_da_cilindrada_nao_e_versao(self):
        """'1.0 i', '2.0 i' é injeção — irmã de MI/MPI/IE, que já eram spec."""
        assert inferir_marca_modelo_versao_obs_ano("Volkswagen Gol 1995 1.0 I")[2] is None
        assert inferir_marca_modelo_versao_obs_ano(
            "Ford Escort 1993 2.0 I Xr3 8v")[2] == "XR3"
        assert inferir_marca_modelo_versao_obs_ano(
            "Ford Escort 1.8 I Gl 16v Gasolina 4p Manual")[2] == "GL"
