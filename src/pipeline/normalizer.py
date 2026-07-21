"""
Normalização de preço e texto para o pipeline do Valor Clássico.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


def normalizar_preco(valor_bruto: str) -> Optional[float]:
    """
    Converte string de preço em float detectando automaticamente o formato.

    Exemplos aceitos:
        'R$180.000,00'  -> 180000.0   (BR: ponto=milhar, vírgula=decimal)
        'R$27,500.00'   -> 27500.0    (US: vírgula=milhar, ponto=decimal)
        '180.000,00'    -> 180000.0
        '180000'        -> 180000.0
        'Consulte'      -> None
    """
    if not valor_bruto or not valor_bruto.strip():
        return None

    # Remove símbolo de moeda, letras e espaços; mantém dígitos, ponto e vírgula
    limpo = re.sub(r"[^\d.,]", "", valor_bruto)
    # Remove ponto/vírgula sobrando nas pontas (ex.: "R$ 95.000." de fim de frase)
    limpo = limpo.strip(".,")

    if not limpo:
        return None

    has_comma = "," in limpo
    has_dot   = "." in limpo

    if has_comma and has_dot:
        # O separador que aparece por último é sempre o decimal
        if limpo.rfind(".") > limpo.rfind(","):
            # Formato americano: 27,500.00 → vírgula=milhar, ponto=decimal
            limpo = limpo.replace(",", "")
        else:
            # Formato brasileiro: 180.000,00 → ponto=milhar, vírgula=decimal
            limpo = limpo.replace(".", "").replace(",", ".")
    elif has_comma:
        after = limpo.rsplit(",", 1)[-1]
        if len(after) == 3:
            # Vírgula de milhar: 27,500 → 27500
            limpo = limpo.replace(",", "")
        else:
            # Vírgula decimal: 27,50 → 27.50
            limpo = limpo.replace(",", ".")
    elif has_dot:
        after = limpo.rsplit(".", 1)[-1]
        if len(after) == 3 and limpo.count(".") == 1:
            # Ponto de milhar ambíguo: 27.500 → 27500 (valores de carro raramente têm casas decimais)
            limpo = limpo.replace(".", "")
        # else: ponto decimal normal, mantém

    try:
        resultado = float(limpo)
        return resultado if resultado > 0 else None
    except ValueError:
        return None


def remover_acentos(texto: str) -> str:
    """
    Remove acentos de uma string para uso em matching/indexação.
    O texto original é preservado para exibição.
    """
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_texto(texto: str) -> str:
    """
    Normalização completa para indexação/matching:
    - Remove acentos
    - Converte para UPPERCASE
    - Trata barra como separador de token (vira espaço)
    - Colapsa espaços duplicados
    - Remove pontuação irrelevante (mantém hífen e ponto)
    """
    sem_acento = remover_acentos(texto)
    maiusculo = sem_acento.upper()
    # Muitos anunciantes usam "/" como separador marca/modelo ("Vw/fusca",
    # "Gm/chevrolet") — sem virar espaço, os tokens grudam ("VWFUSCA",
    # "GMCHEVROLET") e a marca nunca é reconhecida (auditoria 2026-07-15).
    com_espacos = maiusculo.replace("/", " ")
    # Colapsar espaços
    sem_espacos_dup = re.sub(r"\s+", " ", com_espacos).strip()
    # Remover pontuação irrelevante (vírgula, parênteses, etc.), manter hífen e ponto
    limpo = re.sub(r"[^\w\s.\-]", "", sem_espacos_dup)
    return limpo


# Abreviações comuns que os anunciantes usam no lugar do nome oficial da
# marca. Sem isso, "VW Fusca" e "Volkswagen Fusca" viram marcas diferentes
# na busca e nas estatísticas (auditoria 2026-07-14: 795 anúncios afetados).
_ALIASES_MARCA: dict[str, str] = {
    "VW": "VOLKSWAGEN",
    "GM": "CHEVROLET",
    "MERCEDES": "MERCEDES-BENZ",
    "MERCEDES BENZ": "MERCEDES-BENZ",
    # Catálogo grafa hifenizado; anúncios escrevem com espaço
    "ROLLS ROYCE": "ROLLS-ROYCE",
    # Grafias erradas comuns em anúncios reais (auditoria 2026-07-14)
    "ALFA ROMEU": "ALFA ROMEO",
    "VOKSWAGEN": "VOLKSWAGEN",
    "VOLKSWAGEM": "VOLKSWAGEN",
    "VOLKSVAGEM": "VOLKSWAGEN",
    "VOLKWAGEM": "VOLKSWAGEN",
    # Grafias erradas/apelidos comuns (auditoria 2026-07-15: marca=ano ou
    # marca=lixo em ~150 anúncios — ver reprocessar_marca_modelo.py)
    "VOLKS": "VOLKSWAGEN",
    "FOR": "FORD",
    "FORDINHO": "FORD",  # apelido popular do Ford Model A/T no Brasil
    "FUSCAO": "VOLKSWAGEN",  # apelido popular do Fusca "grande"/customizado
    # NB: "VOIAGE" (typo de "Voyage") NÃO fica aqui — como alias de marca ele
    # consumiria o token e "Voiage Argentino" perderia o "Voyage" do modelo
    # (auditoria 2026-07-20). Movido pra _MODELO_AMBIGUO_MARCA, que identifica
    # a marca sem consumir o token — a canonização VOIAGE->VOYAGE acontece
    # depois, em _MODELO_ABREVIACAO, já no pipeline de modelo.
    "CHREVOLET": "CHEVROLET",
    "CHREVROLET": "CHEVROLET",
    "CHVEROLET": "CHEVROLET",
    "DOGDE": "DODGE",
    "HOONDA": "HONDA",
    "HYUNDAY": "HYUNDAI",
    "PORCHE": "PORSCHE",
    "OLSDMOBILE": "OLDSMOBILE",
    "MERCEDENS": "MERCEDES-BENZ",
    "GUEGEL": "GURGEL",
    "STUDBAKER": "STUDEBAKER",
    "DKV": "DKW",
    "VEMAG": "DKW",  # fabricante original do DKW-Vemag no Brasil
    "MERCURI": "MERCURY",
    "DKW-VEMAG": "DKW",  # catálogo tem as duas grafias como marcas separadas
    "AUTO UNION": "DKW",  # holding alemã dona da DKW; "Auto-Union" nos anúncios
    # BELCAR é modelo DKW, mas o catálogo lista o mesmo modelo sob "DKW" E
    # "DKW-VEMAG" (grafias diferentes do mesmo fabricante) — isso faz o
    # modelo parecer ambíguo pro vocabulário automático (passo 3) e cai no
    # fallback errado. Resolvido aqui direto, como os outros modelos-alias.
    "BELCAR": "DKW",
    # Anunciante escreve o alias colado ao nome oficial com hífen, sem
    # espaço ("Vw-volkswagen Santana", "Gm-chevrolet Opala") — vira um
    # único token que não bate nem no alias simples nem no catálogo.
    "VW-": "VOLKSWAGEN",
    "GM-": "CHEVROLET",
    "VW-VOLKSWAGEN": "VOLKSWAGEN",
    "GM-CHEVROLET": "CHEVROLET",
    # Auditoria 2026-07-15 (2ª rodada, marcas fora do CSV base_marcamodelo.csv
    # — motos, caminhões e marcas raras que o catálogo de carros não cobre).
    "SINCA": "SIMCA",  # typo
    "WYLLIS": "WILLYS",  # typo
    "ALFA": "ALFA ROMEO",  # "Alfa Rtomeu..." — typo no 2º token não importa aqui
    "CALOICROSS": "CALOI",  # linha off-road da mesma fabricante
    # Marcas de 2 tokens: sem entrada aqui, o passo 1 (prefixo do catálogo)
    # não as reconhece — o fallback pegaria só o 1º token ("AM"/"DIAMOND"/
    # "PIERCE"/"HARLEY") e devolveria o 2º como se fosse modelo.
    "HARLEY DAVIDSON": "HARLEY-DAVIDSON",
    "AM GENERAL": "AM GENERAL",
    "DIAMOND T": "DIAMOND T",
    "PIERCE ARROW": "PIERCE-ARROW",
    # "MP LAFER" é a grafia do catálogo (e a predominante no banco) do mesmo
    # fabricante brasileiro de kit car — "MP" é a sigla da fábrica. Todas as
    # variações ("Lafer" sozinho, typo "Laffer", hífen do título) unificam
    # nela pra não fragmentar o grupo.
    "MP LAFFER": "MP LAFER",
    "MP LAFER-": "MP LAFER",  # hífen do título original ("Lafer- 1978/78...")
    # Auditoria 2026-07-17 (4ª rodada): marca vinha CRUA da ficha técnica do
    # Mercado Livre — o vendedor digita a grafia que quer no campo "Marca"
    # (typos, "Marca Modelo" junto, apelidos). Estes são os typos de marca
    # simples que apareceram no banco; os casos "Marca Modelo" colada são
    # resolvidos por sanear_marca_modelo() (usa o catálogo pra separar).
    "VOLKWAGEN": "VOLKSWAGEN",
    "VOKSWAGEM": "VOLKSWAGEN",
    "VOLKSVAGEN": "VOLKSWAGEN",
    "WOLKSVAGEM": "VOLKSWAGEN",
    "WOLKSVAGEN": "VOLKSWAGEN",
    "WOLKVAGEN": "VOLKSWAGEN",
    "PORSCH": "PORSCHE",
    "CRYSLER": "CHRYSLER",
    "METCURY": "MERCURY",
    "PUMW": "PUMA",
    "CHEVRO": "CHEVROLET",
    "CADILAC": "CADILLAC",
    # Catálogo grafa "DE SOTO"/"DE TOMASO" com espaço; anúncios colam tudo.
    "DESOTO": "DE SOTO",
    "DETOMASO": "DE TOMASO",
    # "Lafer" sozinho é o mesmo fabricante que "MP LAFER" do catálogo.
    "LAFER": "MP LAFER",
    "WYLLIS": "WILLYS",
    "WILYS": "WILLYS",
    # Trator Heinrich Lanz — comumente citado só como "Lanz".
    "HEINRICH LANZ": "LANZ",
}

# Modelos cujo nome sozinho é ambíguo no catálogo geral (ex.: "147" é Fiat
# E Alfa Romeo; "Caravan"/"Kadett"/"Ranger"/"Silverado"/"Blazer" têm mais de
# uma leitura fora do Brasil) mas que, no recorte de carro clássico
# brasileiro deste projeto, têm uma leitura dominante e seguem sem marca no
# título ("147 1.3L", sem "Fiat" na frente). Diferente de _ALIASES_MARCA
# (marca escrita errado), aqui o token É o nome do modelo — a marca nunca
# apareceu no anúncio.
_MODELO_AMBIGUO_MARCA: dict[str, str] = {
    "147": "FIAT",
    # Picapes/utilitários GM — "D-10"/"D-20"(diesel MWM)/"C-10"/"C1500"
    # nunca vêm com "Chevrolet" no título (auditoria 2026-07-15).
    "CARAVAN": "CHEVROLET",
    "KADETT": "CHEVROLET",
    "SILVERADO": "CHEVROLET",
    "BLAZER": "CHEVROLET",
    "D-10": "CHEVROLET",
    "D-20": "CHEVROLET",
    "D10": "CHEVROLET",  # mesma picape, alguns anúncios sem hífen
    "D20": "CHEVROLET",
    "C-10": "CHEVROLET",
    "C1500": "CHEVROLET",
    "RANGER": "FORD",
    "PREMIO": "FIAT",  # "Prêmio" — ausente do modelo_marca automático
    # "Rural" sozinho é Willys Rural no Brasil (a Ford so herdou a marca
    # depois de comprar a Willys-Overland do Brasil em 1967) — cobre tanto
    # "Rural Willys"/"Rural Wyllis" quanto "Rural 4x4"/"Rural Luxo".
    "RURAL": "WILLYS",
    # "Voiage" (typo de "Voyage") sem "Volkswagen"/"VW" na frente — igual
    # não consome o token, pra _MODELO_ABREVIACAO canonizar pra "VOYAGE"
    # depois (auditoria 2026-07-20, ver comentário em _ALIASES_MARCA).
    "VOIAGE": "VOLKSWAGEN",
}

# Grafia abreviada de modelo que fragmenta o grupo se não for canonizada
# pra forma cheia do catálogo (auditoria 2026-07-20: "Toyota Bandeirante" —
# clássico off-road brasileiro — vinha como "Band"/"Band."/"Bandeirantes"
# em ~240 anúncios, cada grafia virando um modelo distinto). Aplicada por
# token logo após a tokenização, antes da âncora de catálogo — assim
# "BAND." vira "BANDEIRANTE" e a âncora reconhece normalmente.
_MODELO_ABREVIACAO: dict[tuple[str, str], str] = {
    ("TOYOTA", "BAND"): "BANDEIRANTE",
    ("TOYOTA", "BAND."): "BANDEIRANTE",
    ("TOYOTA", "BANDEIRANTES"): "BANDEIRANTE",
    # Auditoria 2026-07-20 (revisão geral dos modelos Volkswagen): apelido,
    # typo ou plural fragmentando o mesmo modelo do catálogo.
    ("VOLKSWAGEN", "FUSCAO"):       "FUSCA",      # apelido popular
    ("VOLKSWAGEN", "FUSQUINHA"):    "FUSCA",      # apelido popular
    ("VOLKSWAGEN", "APOLO"):        "APOLLO",     # grafia sem dobrar o L
    ("VOLKSWAGEN", "BRASLIA"):      "BRASILIA",   # typo (falta o "I")
    ("VOLKSWAGEN", "VOYAGEM"):      "VOYAGE",     # typo
    ("VOLKSWAGEN", "VOYAGES"):      "VOYAGE",     # plural
    ("VOLKSWAGEN", "VOIAGE"):       "VOYAGE",     # typo (mesmo caso do
    # alias de MARCA "VOIAGE"→VOLKSWAGEN — aqui é o token de MODELO)
    ("VOLKSWAGEN", "KARMANN-GUIA"): "KARMANN-GHIA",  # typo (Guia x Ghia)
    # NB: sem alias solto pra "KARMANN" — duplicaria quando o título já diz
    # "Karmann Ghia" por extenso (2 tokens): "KARMANN"->"KARMANN-GHIA" mais
    # o "GHIA" que já vinha depois vira "KARMANN-GHIA GHIA".
    # Modelo colado ao trim sem espaço no título original ("GolCL",
    # "SaveiroCL", "VoyageCL") — sem separador pra descolar tipo
    # _NUMERO_PALAVRA_COLADA (não começa com dígito), então mapeado direto;
    # perde o trim "CL" como versão à parte, aceitável pro volume (1 cada).
    ("VOLKSWAGEN", "GOLCL"):        "GOL",
    ("VOLKSWAGEN", "SAVEIROCL"):    "SAVEIRO",
    ("VOLKSWAGEN", "VOYAGECL"):     "VOYAGE",
    # Duas formas VÁLIDAS no catálogo pro mesmo modelo (a com espaço foi
    # suplementada 2026-07-15 só pra reconhecer, sem virar canônica) —
    # fragmentava 13+26 anúncios em dois grupos. Chave é o modelo JÁ
    # ancorado (2 tokens juntos), não mais um único token cru — reaplicado
    # depois da âncora, não da tokenização (ver sanear_modelo/
    # separar_modelo_versao_obs).
    ("VOLKSWAGEN", "KARMANN GHIA"): "KARMANN-GHIA",
}

# O catálogo geral grafa a mesma marca de mais de um jeito ("WILLYS" e
# "WILLYS OVERLAND" são o mesmo fabricante) — a regra "prefixo mais longo
# primeiro" do passo 1 preferiria a forma composta, fragmentando o grupo já
# estabelecido (usuária pediu 2026-07-15 pra manter só "WILLYS").
#
# IMPORTANTE: o passo 1 (`_separar_marca_core`) precisa CONSUMIR os tokens
# inteiros da chave (não só reconhecer e pular pra forma de 1 token) — senão
# a 2ª palavra da marca composta ("OVERLAND", "VEMAG") sobra e vaza pro
# modelo (bug achado na auditoria de existência 2026-07-21: 105 anúncios
# "Willys/Overland" e 10 "DKW/Vemag" com o modelo real perdido).
_MARCA_CANONICA: dict[str, str] = {
    "WILLYS OVERLAND": "WILLYS",
    # Catálogo grafa "DKW-VEMAG" (hífen) como marca separada de "DKW", mas os
    # títulos reais escrevem "DKW Vemag" com espaço (2 tokens) — sem essa
    # entrada, "Vemag" (nome da joint-venture, não um modelo) vira o modelo.
    "DKW VEMAG": "DKW",
}

# Primeiros tokens que descrevem o anúncio, não o veículo ("Vendo Ford F-75",
# "Moto Harley-Davidson", "Perua Kombi") — pulados antes de inferir a marca.
_PREFIXOS_NAO_MARCA: frozenset = frozenset({
    "VENDO", "VENDE-SE", "VENDESE", "MOTO", "CARRO", "VEICULO",
    "CAMINHONETE", "CAMIONETA", "PERUA", "FURGAO", "PICK-UP", "PICKUP",
    "RARIDADE", "ANTIGO", "ANTIGA", "CLASSICO", "CLASSICA",
    # Descrevem o estilo/preparação do carro, não o veículo em si
    # (auditoria 2026-07-15: "Hotrod 1930 ... Pickup Ford 1929" perdia o
    # Ford pro fallback "primeiro token")
    "HOTROD", "HOT-ROD", "MOTOR",
    # Tipo de veículo fora do catálogo de carros, mas com marca própria
    # depois no título ("Trator Zetor", "Ônibus Chevrolet 6100") — 2ª
    # rodada da auditoria 2026-07-15.
    "TRATOR", "ONIBUS", "CAMINHAO", "CAMINHONETA", "IMPLEMENTO", "PICAPE",
    # "É Dauphine 1961!..." perde o acento na normalização e vira "E" sozinho
    # (artigo, não marca); "Outros Outros ..." é categoria do ML duplicada
    # colada ao título; adjetivos de venda que só atrapalham quando são o
    # 1º token ("Rara Mobylette...", "Lindo Buggy...").
    # NB: "DE" NÃO entra aqui — colide com marcas reais de 2 palavras que
    # começam com "De" ("De Soto", "De Tomaso"); ver correção pontual do
    # único caso ("Carro de Coleção! Escort...") em _EXCLUIR do script.
    "E", "OUTROS", "RARA", "RARO", "LINDO", "COLECAO",
    # Cauda de "N CILINDROS"/"N CC" solto no início (o número é pulado à
    # parte, ver passo 0) — sem isso "CILINDROS" sobra como marca na
    # iteração seguinte do loop.
    "CILINDROS", "CC",
})

# Sentinela pra anúncio cujo título não cita marca identificável nenhuma
# (ex.: "Veículo Ótimo Estado De Conservação", "Placa Preta") — usada em vez
# de aceitar a primeira palavra qualquer como se fosse marca real. Facilita
# achar esses casos pra revisão manual: `WHERE marca = 'NAO IDENTIFICADA'`.
MARCA_NAO_IDENTIFICADA = "NAO IDENTIFICADA"

# Marcas que `sanear_marca_modelo` nunca reinterpreta: a sentinela acima e
# "BUGGY" (kit car sem fabricante único no título — a usuária decidiu manter
# como grupo próprio em vez de adivinhar, auditoria 2026-07-15, 2ª rodada).
_MARCAS_PRESERVADAS: frozenset = frozenset({MARCA_NAO_IDENTIFICADA, "BUGGY"})

# Palavras comuns de português (adjetivo, conectivo, substantivo de venda)
# que nunca são nome de marca — quando são o único candidato restante no
# fallback do passo 4, o anúncio vai para MARCA_NAO_IDENTIFICADA em vez de
# uma palavra-lixo (auditoria 2026-07-15, 3ª rodada). Não inclui "RARA"/
# "RARO"/"LINDO"/"E"/"OUTROS" — esses já são pulados como prefixo no passo 0
# quando seguidos de outro token; ficam aqui só como rede de segurança para
# quando sobram sozinhos.
_PALAVRAS_NAO_MARCA: frozenset = frozenset({
    "MUITO", "PLACA", "COM", "OTIMO", "OTIMA", "PARA", "ABERTA", "ABERTO",
    "VERSAO", "ROBUSTO", "ROBUSTA", "CAUTELAR", "TODO", "TODA", "SO",
    "BONITO", "BONITA", "IMPECAVEL", "EXCELENTE", "COMPLETO", "COMPLETA",
    "ORIGINAL", "DE", "DA", "DO", "EM", "SEM", "RARA", "RARO", "LINDO",
})

# ────────────────────────────────────────────────
# Saneamento do MODELO — tirar poluição de spec (auditoria 2026-07-17)
# ────────────────────────────────────────────────
#
# O campo "modelo" costuma vir com o nome do modelo + versão/trim seguidos de
# uma cauda de especificações que o anunciante despeja no título/ficha:
# cilindrada ("1.6", "2.0", "1300"), válvulas ("8V", "16V"), combustível
# ("Gasolina", "Álcool"), injeção ("MI", "MPFI", "EFI"), câmbio ("Mec.",
# "Manual"), portas ("2P", "4 Portas") e potência ("50cv"). Nada disso
# identifica o modelo — só fragmenta as estatísticas (o mesmo Fusca virava
# "FUSCA", "FUSCA 1300", "FUSCA 1600", "FUSCA ALCOOL"...). A usuária decidiu
# (2026-07-17) MANTER a versão/trim (XR3, GSI, GLX — pesa no preço de clássico)
# e cortar só as specs. Ver sanear_modelo() e feedback correspondente.
#
# Estratégia: mantém o nome do modelo + trim que vêm ANTES da primeira spec e
# corta dali pra frente (o anunciante escreve "Modelo Trim specs...", nessa
# ordem). O catálogo ancora o nome real do modelo pra proteger número que É
# parte do nome (Defender 110, C 1504, RD 350) de ser confundido com
# cilindrada. Número de 4 dígitos solto (1300/1600/2000) é cilindrada/ano;
# 2-3 dígitos podem ser variante de modelo (110, 88, 308) e por isso só saem
# quando não fazem parte de um modelo ancorado no catálogo.

# Palavras que marcam onde começa a cauda de spec (corte daqui pra frente).
_SPEC_COMBUSTIVEL: frozenset = frozenset({
    "GASOLINA", "ALCOOL", "ETANOL", "DIESEL", "FLEX", "GNV", "GAS",
    "BICOMBUSTIVEL", "ELETRICO", "HIBRIDO",
})
_SPEC_CAMBIO: frozenset = frozenset({
    "MEC", "MEC.", "AUT", "AUT.", "AUTOMATICO", "AUTOMATICA", "AUTOMATIC",
    "MECANICO", "MECANICA", "MANUAL", "CAMBIO", "MT", "AT", "SEMI-AUT",
})
_SPEC_INJECAO: frozenset = frozenset({
    "MI", "MPI", "MPFI", "EFI", "IE", "I.E.", "TBI", "TB", "SFI", "MFI",
    "EGI", "INJECAO", "INJETADO", "CARBURADO", "CARBURADA", "CARB",
})
# "(modelo antigo)" e conectivo solto de enumeração de spec ("2p E 4p").
_SPEC_OBSERVACAO: frozenset = frozenset({"MODELO", "ANTIGO", "NOVO", "E"})
_SPEC_PORTAS: frozenset = frozenset({"PORTAS", "PORTA"})

# Observações de texto livre que o anunciante despeja no título/ficha e que NÃO
# são o modelo nem trim: venda, preço, estado/conservação, documentação, tipo de
# cabine e afins. Contaminam o campo e impedem agrupar por modelo pra tirar média
# (usuária pediu 2026-07-18: "no modelo, só informação de modelo e nada mais").
# Cuidado ao ampliar: nada que seja trim/edição real (SPECIAL, SPORT, ATLANTA,
# "ROLLING STONES", COPA...) nem parte de nome de modelo do catálogo. "NOVA" fica
# de fora de propósito (colide com Chevrolet Nova); "CAB"/"CABINE" é protegido pra
# "King Cab" pela âncora do catálogo.
_MODELO_OBSERVACAO: frozenset = frozenset({
    # venda / negociação
    "VENDE-SE", "VENDESE", "VENDE", "VENDO", "VENDA", "VENDAS", "TROCA",
    "TROCO", "TROCAR", "TROCAS", "PARCELO", "PARCELA", "PARCELAMOS",
    "PARCELAMENTO", "FINANCIO", "FINANCIA", "FINANCIAMENTO", "FINANCIADO",
    "ACEITO", "ACEITA", "ACEITAMOS", "OFERTA", "OFERTAS", "ENTRADA",
    "CARTAO", "CREDITO", "CONSORCIO", "REPASSE",
    # preço
    "PRECO", "PROMOCIONAL", "PROMOCAO", "ABAIXO", "TABELA", "FIPE",
    "BARBADA", "OPORTUNIDADE", "IMPERDIVEL", "NEGOCIO", "DESCONTO",
    "VALOR", "BARATO",
    # estado / conservação / elogio
    "RARIDADE", "RARIDADES", "RARISSIMO", "RARISSIMA", "RARO", "RARA",
    "IMPECAVEL", "IMPECAVEIS", "CONSERVADO", "CONSERVADA", "CONSERVADISSIMO",
    "CONSERVADISSIMA", "CONSERVACAO", "RELIQUIA", "RELIGUIA", "ZERADO",
    "ZERADA", "ZERO", "LINDO", "LINDA", "LINDAO", "LINDISSIMO", "LINDISSIMA",
    "COMPLETO", "COMPLETA", "EQUIPADO", "EQUIPADA", "EQUIPADISSIMA",
    "EQUIPADISSIMO", "REVISADO", "REVISADA", "EXCELENTE", "EXCEPCIONAL",
    "PERFEITO", "PERFEITA", "ESTADO", "ORIGINAL", "ORIGINAIS", "INTEIRO",
    "INTEIRA", "LATARIA", "PROCEDENCIA", "COLECIONADOR", "COLECAO",
    "ESPETACULAR", "MARAVILHOSO", "MARAVILHOSA", "BELISSIMO", "BELISSIMA",
    "BONITO", "BONITA", "OTIMO", "OTIMA", "RESTAURADO", "RESTAURADA",
    "MODIFICADO", "MODIFICADA", "DONO", "DONOS", "HOTROD", "HOT-ROD",
    # documentação / legal
    "PLACA", "DOC", "DOCUMENTO", "DOCUMENTACAO", "DOCUMENTOS", "LICENCIADO",
    "IPVA", "QUITADO", "CAUTELAR", "OK",
    # tipo de cabine / carroceria / chassi (usuária citou "cabine estendida")
    "CABINE", "CAB", "CAB.", "CARROCERIA", "CHASSI", "CHAS", "CHAS.", "CURTO", "LONGO",
    # motor por extenso (não é o modelo): "6 cilindros", "6cc"; "Motor"/
    # "Motors" solto é sufixo corporativo vazado ("Kia Motors Besta") ou
    # menção de motor no título ("motor 1.6 AP") — nem um nem outro é
    # trim (auditoria 2026-07-20). "Asia Motors" é exceção: a usuária pediu
    # marca "ASIA MOTORS" inteira — ver _MARCA_SUFIXO_ABSORVE em _separar_marca.
    "CILINDROS", "CILINDRADA", "CC", "CUSTOMIZADO", "CUSTOMIZADA",
    "MOTOR", "MOTORS",
    # aluguel/eventos: anúncio de frota pra casamento/evento, não descreve
    # UM carro específico (usuária pediu 2026-07-20, varredura geral)
    "ALUGUEL", "ALUGA-SE", "CASAMENTO", "CASAMENTOS", "EVENTO", "EVENTOS",
    # estado geral / conforto / conectivos de descrição
    "KM", "EPOCA", "TODO", "TODA", "TODOS", "TODAS", "MUITO", "MUITA", "AR",
    "CONDICIONADO", "DIRECAO", "HIDRAULICA", "COM", "SEM", "PARA", "PRA",
    "POSSUI", "ANO", "ATELIE", "LOJA", "CARRO", "UM", "UMA",
})

# Cores: nunca é informação aproveitável de versão — nem paint job, nem
# acabamento (usuária pediu 2026-07-20: "cores não são versão, na verdade
# cores não são uma informação aproveitável"). Descartada por completo (não
# vira obs — carroceria/tração é atributo do carro, cor não pesa em nada).
# Exceção: "Série Prata"/"Série Ouro" são edições reais da VW (Fusca/Kombi
# "Série Ouro/Prata"), não a cor da pintura — protegidas quando precedidas
# de SERIE (ver o loop de classificação em separar_modelo_versao_obs).
_CORES: frozenset = frozenset({
    "BRANCO", "BRANCA", "PRETO", "PRETA", "PRATA", "CINZA", "VERMELHO",
    "VERMELHA", "AZUL", "VERDE", "AMARELO", "AMARELA", "BEGE", "DOURADO",
    "DOURADA", "OURO", "MARROM", "LARANJA", "ROXO", "ROSA", "GRAFITE",
    "VINHO", "BORDO", "CHAMPAGNE", "PEROLA", "FOSCO", "FOSCA", "METALICO",
    "METALICA", "METAL",
})

_SPEC_PALAVRAS: frozenset = (
    _SPEC_COMBUSTIVEL | _SPEC_CAMBIO | _SPEC_INJECAO | _SPEC_OBSERVACAO
    | _MODELO_OBSERVACAO
)

# Cilindrada em litros (prefixo "1.6", "2.0", "4.1"; pega até grafia colada
# "1.82.0"). Prefixo, não fullmatch, de propósito.
_SPEC_DECIMAL = re.compile(r"^\d[.,]\d")
# Specs reconhecidas pela forma do token (não por dicionário).
_SPEC_REGEX = re.compile(
    r"""^(
        \d{1,2}V |            # válvulas: 8V, 16V, 20V
        V\d{1,2} |            # config. de motor: V6, V8, V12
        \d{1,2}P(\d{1,2}P)? | # portas: 2P, 4P, 2P4P
        \d{1,4}(CV|HP) |      # potência: 50CV, 100HP
        \d{2,7}KM |           # quilometragem colada: 700KM, 50000KM
        \d{1,2}CC |           # cilindros colado: 6CC, 4CC
        \d{4}                 # cilindrada/ano solto: 1300, 1600, 2000
    )$""",
    re.VERBOSE,
)


# Cilindrada colada ao nome/versão sem espaço ("Santana2.0", "A62.7",
# "Xc602.0", "Expres.2.2"). O ponto decimal denuncia a cilindrada — nenhum nome
# de modelo tem "X.Y" —, então separá-la (por espaço) é seguro. Basta estar
# grudada a qualquer não-espaço; "1.6" no início/após espaço não é tocada.
_CILINDRADA_COLADA = re.compile(r"(?<=\S)(\d[.,]\d)")
# Número colado numa palavra por extenso sem espaço ("156Elegant",
# "1500Motor", "6cilindros", "D-20Manual" — perda de espaço no título
# original). Exige 4+ letras pra não colapsar sigla curta de trim ("1300L",
# "505SRI") — essas ficam pro _CILINDRADA_TRIM_GLUED ou seguem intactas.
_NUMERO_PALAVRA_COLADA = re.compile(r"(?<=\d)([A-Z]{4,})\b")
# Abreviação com ponto colada direto na palavra seguinte, sem espaço
# ("Band.Picape", "Cap.de Aço", "Sed.Wind" — auditoria 2026-07-20, achado
# investigando o Toyota Bandeirante fragmentado). Separar é sempre seguro:
# o pior caso é dois tokens tão opacos quanto o blob original; o melhor caso
# destrava um token reconhecível (trim, carroceria) que ficaria perdido.
_ABREVIACAO_COLADA = re.compile(r"(?<=[A-Z])\.(?=[A-Z])")


def _tokenizar_modelo(marca_norm: str, modelo: str) -> list[str]:
    """
    Normaliza e tokeniza `modelo` pra `sanear_modelo`/`separar_modelo_
    versao_obs`: descola cilindrada/número/abreviação colados, colapsa
    token duplicado ("DARTDART"->"DART") e canoniza abreviação de modelo
    conhecida por marca ("BAND."->"BANDEIRANTE" — ver _MODELO_ABREVIACAO).
    """
    modelo_norm = _ABREVIACAO_COLADA.sub(
        ". ",
        _NUMERO_PALAVRA_COLADA.sub(
            r" \1", _CILINDRADA_COLADA.sub(r" \1", normalizar_texto(modelo))
        ),
    )
    tokens = []
    for t in modelo_norm.split():
        t = _TOKEN_DUPLICADO.sub(r"\1", t)
        t = _MODELO_ABREVIACAO.get((marca_norm, t), t)
        # Modelo conhecido grudado ao resto ("FUSCA1300"→"FUSCA 1300",
        # "ESCORTXR3"→"ESCORT XR3") — separa em tokens pra âncora achar o nome.
        tokens.extend(_descolar_modelo_conhecido(marca_norm, t).split())
    return tokens


def _descolar_modelo_conhecido(marca_norm: str, token: str) -> str:
    """
    Separa um nome de modelo do catálogo grudado ao resto do token
    ('FUSCA1300'→'FUSCA 1300', 'IMPALAWAGON'→'IMPALA WAGON'). Guardas contra
    corte errado: (1) o token inteiro não pode ser ele próprio um modelo
    ('GOLF' não vira 'GOL F'); (2) usa o maior prefixo-modelo possível;
    (3) o prefixo precisa ter 4+ letras (evita cortar em modelo curto tipo
    'A'/'KA'/'GOL'). Achado na auditoria 2026-07-21 (2ª passada: 'VW-FUSCA-1300'
    e outros modelos grudados).
    """
    modelos = _modelos_catalogo().get(marca_norm, set())
    if not modelos or token in modelos:
        return token
    # Prefixo-modelo puramente numérico ('1600', '147') é ambíguo com
    # cilindrada colada ('1600S') — deixado pro tratamento de spec/glued.
    candidatos = sorted(
        (
            m for m in modelos
            if " " not in m and len(m) >= 4 and not m.isdigit()
            and len(token) > len(m) and token.startswith(m)
        ),
        key=len,
        reverse=True,
    )
    if candidatos:
        m = candidatos[0]
        return f"{m} {token[len(m):]}"
    return token
# Nome de modelo duplicado colado num token só ("DARTDART", "RURALRURAL",
# "BELINABELINA"). Exige unidade de 3+ chars pra não colapsar trim curto ("SS").
_TOKEN_DUPLICADO = re.compile(r"^(.{3,})\1$")


def _e_token_spec(tok: str, spec_palavras: frozenset = _SPEC_PALAVRAS) -> bool:
    """True se o token é spec (cilindrada, válvula, combustível, câmbio,
    injeção, potência, porta ou observação) — o corte para o modelo."""
    return bool(
        tok in spec_palavras
        or _SPEC_DECIMAL.match(tok)
        or _SPEC_REGEX.match(tok)
    )


def _indice_corte_spec(
    tokens: list[str], inicio: int, spec_palavras: frozenset = _SPEC_PALAVRAS
) -> int:
    """
    Primeiro índice (>= inicio) onde começa a cauda de spec — o modelo é
    tokens[:esse_índice]. Trata "4 Portas"/"2 Portas" por extenso cortando já
    no número (senão o número sobraria órfão no fim do modelo).

    `spec_palavras` é parametrizável pra `separar_modelo_versao_obs` reusar
    este corte com um vocabulário menor (sem carroceria/tração — ver
    `_CARROCERIA_TRACAO`), sem afetar o corte de `sanear_modelo`.
    """
    n = len(tokens)
    for i in range(inicio, n):
        tok = tokens[i]
        prox = tokens[i + 1] if i + 1 < n else ""
        # "4 Portas"/"555 Km"/"6 Cilindros"/"4 Lugares" por extenso: corta já
        # no número (senão sobraria órfão no fim do modelo).
        if tok.isdigit() and (prox in _SPEC_PORTAS or prox in ("KM", "CILINDROS", "LUGARES", "LUGAR")):
            return i
        if tok in _SPEC_PORTAS:
            return i
        if _e_token_spec(tok, spec_palavras):
            return i
    return n


# Cache do vocabulário derivado do catálogo canônico:
# (marcas conhecidas, primeiro-token-de-modelo -> marca exclusiva)
_vocab_catalogo: Optional[tuple[set, dict]] = None
# marca_norm -> set de modelos canônicos (pra ancorar o nome do modelo)
_modelos_catalogo_cache: Optional[dict] = None


def _catalogo_vocab() -> tuple[set, dict]:
    """
    Vocabulário do catálogo pra inferência de marca. Import tardio porque
    catalog.loader importa este módulo (evita import circular). Se o
    catálogo não carregar, degrada pro comportamento antigo (sets vazios).
    """
    global _vocab_catalogo
    if _vocab_catalogo is not None:
        return _vocab_catalogo

    marcas: set = set()
    modelo_marca: dict = {}
    try:
        from src.catalog.loader import carregar_catalogo

        pares = carregar_catalogo().keys()
        marcas = {m for m, _ in pares}
        candidatos: dict[str, set] = {}
        for marca, modelo in pares:
            tok = modelo.split()[0] if modelo.split() else ""
            # Só tokens alfabéticos com 3+ chars: "1600"/"XR3" etc. são
            # ambíguos demais pra identificar marca sozinhos.
            if len(tok) >= 3 and not tok.isdigit():
                candidatos.setdefault(tok, set()).add(marca)
        modelo_marca = {t: next(iter(ms)) for t, ms in candidatos.items() if len(ms) == 1}
    except Exception:  # pragma: no cover - catálogo indisponível
        pass

    _vocab_catalogo = (marcas, modelo_marca)
    return _vocab_catalogo


def _canonizar_grafia(marca_norm: str, modelo: str) -> str:
    """
    Unifica a grafia do modelo com a do catálogo (hífen/espaço): 'D-20'→'D20',
    'C180'→'C 180'. Import tardio (loader importa este módulo). Degrada pro
    modelo original se o catálogo não carregar.
    """
    try:
        from src.catalog.loader import canonizar_modelo

        return canonizar_modelo(marca_norm, modelo)
    except Exception:  # pragma: no cover - catálogo indisponível
        return modelo


def _modelos_catalogo() -> dict:
    """
    marca_norm -> set de modelos canônicos, do catálogo. Usado por
    `sanear_modelo` pra ancorar o nome do modelo (proteger número que é parte
    do nome). Degrada pra dict vazio se o catálogo não carregar.
    """
    global _modelos_catalogo_cache
    if _modelos_catalogo_cache is not None:
        return _modelos_catalogo_cache

    modelos: dict[str, set] = {}
    try:
        from src.catalog.loader import carregar_catalogo

        for marca, modelo in carregar_catalogo().keys():
            modelos.setdefault(marca, set()).add(modelo)
    except Exception:  # pragma: no cover - catálogo indisponível
        pass

    _modelos_catalogo_cache = modelos
    return _modelos_catalogo_cache


def _maior_prefixo_modelo(marca_norm: str, tokens: list[str]) -> int:
    """
    Tamanho (em tokens) do maior prefixo de `tokens` que é um modelo do
    catálogo pra `marca_norm` — cobre nomes de modelo com número ("C 1504",
    "RD 350", "300 ZX"). 0 se nada bate.
    """
    modelos = _modelos_catalogo().get(marca_norm, set())
    if not modelos:
        return 0
    for n in range(min(len(tokens), 4), 0, -1):
        if " ".join(tokens[:n]) in modelos:
            return n
    return 0


def _numero_ambiguo_com_cilindrada(tok: str) -> bool:
    """
    True se `tok` é um número que pode ser cilindrada OU nome de modelo
    (decimal "3.4"/"4.1", 4 dígitos soltos "5211") — protegido como modelo
    quando não há mais nada pra ancorar (ex.: "Zetor 5211"). Marcas onde o
    número decimal É o nome comercial de verdade (Jaguar "3.4", Citroën
    "2CV") ficam no catálogo (ver _SUPLEMENTO) e nem chegam a precisar
    dessa proteção — o catálogo ancora primeiro.
    """
    return bool(_SPEC_DECIMAL.match(tok) or re.fullmatch(r"\d{4}", tok))


def _achar_ancora_modelo(
    marca_norm: str, tokens: list[str], spec_palavras: frozenset
) -> tuple[int, int]:
    """
    Acha onde o nome do modelo começa em `tokens`, tentando o catálogo não
    só na posição 0 mas pulando spec/carroceria/cilindrada-colada solto na
    frente ("Puma 1.6 Gte" — cilindrada antes do nome real "Gte", que está
    no catálogo; "Perua Kombi" — carroceria antes do nome real "Kombi";
    "Fuscão 1600s, fuscão Bizorrão..." — "1600S" glued não é nome de modelo
    mesmo não batendo em nenhum padrão de spec por palavra). Carroceria e
    cilindrada-colada contam como puláveis aqui mesmo quando `spec_palavras`
    não as inclui (`separar_modelo_versao_obs` trata as duas à parte do
    corte de versão — ver ali —, mas nenhuma delas é candidata a nome de
    modelo, então continuam puláveis na busca da âncora). Só pula token que
    É spec/carroceria/cilindrada-colada; token desconhecido que não bate no
    catálogo interrompe a varredura — não é seguro pular por cima de um
    nome de modelo real só por ele não estar catalogado.

    Retorna (posições_puladas, tamanho_da_âncora); tamanho 0 = nada achado
    em posição nenhuma (chamador decide o fallback).
    """
    for pular in range(len(tokens)):
        tam = _maior_prefixo_modelo(marca_norm, tokens[pular:])
        if tam > 0:
            return (pular, tam)
        tok = tokens[pular]
        pulavel = (
            _e_token_spec(tok, spec_palavras)
            or tok in _CARROCERIA_TRACAO
            or _CILINDRADA_TRIM_GLUED.match(tok)
        )
        if not pulavel:
            break
    return (0, 0)


def _localizar_modelo(
    marca_norm: str, tokens: list[str], spec_palavras: frozenset
) -> tuple[int, int]:
    """
    Decide onde o nome do modelo está em `tokens`: (posições_puladas,
    tamanho). Tamanho 0 quer dizer "sem nome de modelo recuperável" — só
    lixo puro (spec/observação) na frente e nada catalogável em nenhuma
    posição (usuária pediu 2026-07-20, revisão de "modelo em branco ou com
    motorização": "V8"/"Modelo"/"Com" sozinho não pode virar o modelo).
    """
    if not tokens:
        return (0, 0)
    pular, tam = _achar_ancora_modelo(marca_norm, tokens, spec_palavras)
    if tam > 0:
        return (pular, tam)
    # Nada no catálogo em posição nenhuma. Fallback: 1º token vira o nome
    # do modelo — MENOS quando é lixo puro não numérico (número ambíguo
    # com cilindrada continua protegido: "Zetor 5211").
    primeiro = tokens[0]
    if _e_token_spec(primeiro, spec_palavras) and not _numero_ambiguo_com_cilindrada(primeiro):
        return (0, 0)
    return (0, 1)


def inferir_marca_modelo_ano(titulo: str) -> tuple[str, str, Optional[int]]:
    """
    Infere marca, modelo e ano a partir do título do anúncio.

    Estratégia:
    - Último token de 4 dígitos (1900-2099) é o ano
    - Marca: prefixo mais longo que seja marca do catálogo (cobre compostas
      como "LAND ROVER" e "MP LAFER"), senão alias comum (VW→VOLKSWAGEN),
      senão modelo exclusivo de uma marca ("FUSCA..."→VOLKSWAGEN), senão o
      primeiro token (comportamento original)
    - Tokens restantes formam o modelo

    Exemplos:
        'Volkswagen Kombi 1975'         -> ('VOLKSWAGEN', 'KOMBI', 1975)
        'VW Fusca 1200 1962'            -> ('VOLKSWAGEN', 'FUSCA 1200', 1962)
        'Land Rover Defender 110 1998'  -> ('LAND ROVER', 'DEFENDER 110', 1998)
        'Fusca 1600 1985'               -> ('VOLKSWAGEN', 'FUSCA 1600', 1985)
        'Chevrolet Biscayne Sedan 1963' -> ('CHEVROLET', 'BISCAYNE SEDAN', 1963)
    """
    marca, modelo_bruto, ano = _inferir_marca_modelo_bruto_ano(titulo)
    if not marca and not modelo_bruto:
        return ("", "", ano)
    # Limpa a cauda de spec do modelo, preservando nome + trim (2026-07-17).
    return (marca, sanear_modelo(marca, modelo_bruto), ano)


def inferir_marca_modelo_versao_obs_ano(
    titulo: str,
) -> tuple[str, str, Optional[str], Optional[str], Optional[int]]:
    """
    Variante de `inferir_marca_modelo_ano` que devolve modelo, versão e obs
    já separados (ver `separar_modelo_versao_obs`), em vez do modelo com
    nome+trim fundidos num string só. Mesma inferência de marca/modelo/ano a
    partir do título — só troca o saneamento final (auditoria 2026-07-20,
    pra conectores que só têm título livre, sem ficha técnica estruturada).

    Exemplos:
        'Chevrolet S10 Americana Cabine Estendida 1998'
            -> ('CHEVROLET', 'S10', 'AMERICANA', 'CABINE ESTENDIDA', 1998)
        'Volkswagen Fusca 1975' -> ('VOLKSWAGEN', 'FUSCA', None, None, 1975)
    """
    marca, modelo_bruto, ano = _inferir_marca_modelo_bruto_ano(titulo)
    if not marca and not modelo_bruto:
        return ("", "", None, None, ano)
    modelo, versao, obs = separar_modelo_versao_obs(marca, modelo_bruto)
    return (marca, modelo, versao, obs, ano)


# Grafias de "Willys" que aparecem coladas ou como modelo — typos frequentes
# do vendedor (auditoria 2026-07-21, 2ª passada: "Jeep Wilys", "Jeep Wyllis").
_GRAFIAS_WILLYS: frozenset = frozenset({
    "WILLYS", "WILYS", "WYLLIS", "WILLIS", "WILLIYS", "WILLYES", "WYLLYS", "WILYES",
})


def _resolver_willys_composto(
    marca: str, resto: list[str], ano: Optional[int]
) -> tuple[str, list[str]]:
    """
    "Willys" (ou um typo dele — ver `_GRAFIAS_WILLYS`) logo depois de FORD ou
    JEEP já identificados é resquício da história dupla do fabricante — sem
    resolver, ficava preso no modelo e o carro real (Rural/Aero-Willys/Jeep/CJ)
    se perdia (achado na auditoria de existência 2026-07-21: 92 anúncios
    "Ford Willys"/"Jeep Willys", mais os typos "Jeep Wilys"/"Jeep Wyllis").

    Ford comprou a Willys-Overland do Brasil em jan/1967 — o catálogo tem
    RURAL cadastrado nas duas marcas (WILLYS antes da compra, FORD depois),
    então usa o ano do anúncio pra decidir. AERO-WILLYS só existe no
    catálogo como WILLYS, não como FORD, independente do ano.
    """
    if marca not in ("FORD", "JEEP") or not resto or resto[0] not in _GRAFIAS_WILLYS:
        return (marca, resto)

    # Hífen solto ("Jeep Willys Overland - 1951") não é informação.
    cauda = [t for t in resto[1:] if t != "-"]
    # Cauda sem spec/lixo ("Ano", "Gasolina", "Diesel"...) pra decidir se
    # sobra algum modelo real — "Jeep Wilys Ano 1964" não tem modelo, é só
    # o Willys Jeep genérico.
    cauda_util = [t for t in cauda if not _e_token_spec(t)]

    if cauda_util[:1] == ["AERO"]:
        return ("WILLYS", ["AERO-WILLYS"])

    if cauda_util[:1] == ["RURAL"]:
        if ano is not None and ano < 1967:
            return ("WILLYS", cauda)
        return ("FORD", cauda)

    if any(t.startswith("CJ") for t in cauda_util):
        # "Jeep Willys CJ-5/CJ6" -> mantém JEEP, só descarta o eco "Willys".
        return (marca, cauda)

    if not cauda_util or cauda_util[:1] == ["OVERLAND"]:
        # "Jeep Willys [Overland] 1970"/"Ford Willys"/"Jeep Wilys Ano" sem
        # outra pista -> o carro é o Willys Jeep.
        return ("WILLYS", ["JEEP"])

    return (marca, cauda)


def _inferir_marca_modelo_bruto_ano(titulo: str) -> tuple[str, str, Optional[int]]:
    """
    Núcleo compartilhado de `inferir_marca_modelo_ano` e
    `inferir_marca_modelo_versao_obs_ano`: acha marca, ano e o modelo AINDA
    CRU (com a cauda de spec, sem separar versão/obs) — cada função pública
    aplica o saneamento final que precisa (`sanear_modelo` ou
    `separar_modelo_versao_obs`) por cima deste resultado.
    """
    titulo_norm = normalizar_texto(titulo)
    tokens = titulo_norm.split()

    if not tokens:
        return ("", "", None)

    # Detectar ano, do último token pro primeiro:
    # - token de 4 dígitos ("1975");
    # - ano duplicado colapsado ("1983/83" vira "198383" na normalização);
    # - ano grudado no fim de outro token ("Summer1996", "16001995");
    # - faixa de 2 dígitos ("87-88" → 1987).
    ano: Optional[int] = None
    tokens_sem_ano = tokens[:]
    for i in range(len(tokens) - 1, -1, -1):
        tok = tokens[i]
        if re.fullmatch(r"(19|20)\d{2}", tok):
            ano = int(tok)
            tokens_sem_ano = tokens[:i] + tokens[i + 1 :]
            break
        m = re.fullmatch(r"((19|20)\d{2})(\d{2})", tok)
        if m and int(m.group(1)) % 100 == int(m.group(3)):
            ano = int(m.group(1))
            tokens_sem_ano = tokens[:i] + tokens[i + 1 :]
            break
        m = re.fullmatch(r"(.*?[^\s])((19|20)\d{2})", tok)
        if m and len(m.group(1)) >= 2:
            ano = int(m.group(2))
            tokens_sem_ano = tokens[:i] + [m.group(1)] + tokens[i + 1 :]
            break
        m = re.fullmatch(r"(\d{2})-\d{2}", tok)
        if m and 30 <= int(m.group(1)) <= 99:
            ano = 1900 + int(m.group(1))
            tokens_sem_ano = tokens[:i] + tokens[i + 1 :]
            break

    # Último recurso: título termina com ano de 2 dígitos ("Escort Ghia 86").
    # Só o último token, e só 30-99, pra não confundir com cilindrada/versão.
    if ano is None and len(tokens_sem_ano) >= 2:
        m = re.fullmatch(r"(\d{2})", tokens_sem_ano[-1])
        if m and 30 <= int(m.group(1)) <= 99:
            ano = 1900 + int(m.group(1))
            tokens_sem_ano = tokens_sem_ano[:-1]

    if not tokens_sem_ano:
        return ("", "", ano)

    marcas_catalogo, modelo_marca = _catalogo_vocab()

    # 0) Pula prefixos descritivos ("Vendo...", "Moto..."), ano solto no
    #    início do título ("1929 Pickup Ford 1930" — o ano de trás já foi
    #    capturado acima; sem isso "1929" sobra e vira marca no fallback),
    #    contagem de cilindros solta ("6 Cilindros Pickup Ford 1929" — sem
    #    isso "6" sobra e vira marca) e "Hot Rod(s)" com espaço ("HOTROD"
    #    grudado já está em _PREFIXOS_NAO_MARCA, mas a maioria escreve
    #    separado — aqui pula os 2 tokens de uma vez).
    while len(tokens_sem_ano) > 1:
        if tokens_sem_ano[0] == "HOT" and tokens_sem_ano[1] in ("ROD", "RODS"):
            tokens_sem_ano = tokens_sem_ano[2:]
        elif (
            tokens_sem_ano[0] in _PREFIXOS_NAO_MARCA
            or re.fullmatch(r"(19|20)\d{2}", tokens_sem_ano[0])
            or (tokens_sem_ano[0].isdigit() and tokens_sem_ano[1] in ("CILINDROS", "CC"))
            # Hífen solto sobra como token próprio ("Raridade - Volkswagen
            # Golf GTI..." — normalizar_texto mantém hífen, então "-" vira
            # um token isolado quando cercado de espaços).
            or tokens_sem_ano[0] == "-"
        ):
            tokens_sem_ano = tokens_sem_ano[1:]
        else:
            break
        if not tokens_sem_ano:
            break

    # Passos 1-3.5: identificar a marca no prefixo dos tokens (catálogo,
    # alias, modelo-exclusivo, modelo-ambíguo). Extraído pra _separar_marca
    # porque a mesma lógica sanea marca/modelo vindos crus de ficha técnica.
    marca, resto = _separar_marca(tokens_sem_ano)
    if marca is not None:
        marca, resto = _resolver_willys_composto(marca, resto, ano)
        modelo = " ".join(resto)
    # 4) Fallback: primeiro token é a marca — mas só quando ele não é uma
    # palavra comum de português (adjetivo/conectivo/substantivo de venda)
    # que nunca é nome de marca. Sem essa guarda, "Veículo Ótimo Estado De
    # Conservação" virava marca="OTIMO" (usuária pediu 2026-07-15, 3ª
    # rodada: todo anúncio sem marca explícita no título deve cair em
    # MARCA_NAO_IDENTIFICADA — sinalizado pra revisão manual — em vez de
    # aceitar qualquer primeiro token como se fosse marca real).
    elif tokens_sem_ano[0] in _PALAVRAS_NAO_MARCA:
        marca = MARCA_NAO_IDENTIFICADA
        modelo = " ".join(tokens_sem_ano)
    else:
        marca = tokens_sem_ano[0]
        modelo = " ".join(tokens_sem_ano[1:]) if len(tokens_sem_ano) > 1 else ""

    return (marca, modelo, ano)


# Sufixo corporativo que vaza pro modelo quando a marca é 1 token só
# ("Kia Motors Besta", "Asia Motors Topic"). Regra geral: descartado (ver
# "MOTOR"/"MOTORS" em _MODELO_OBSERVACAO). Exceção: marcas onde o sufixo É
# parte do nome usual (usuária pediu 2026-07-20: "no Asia, o nome da marca
# é Asia Motors") — aqui ele é absorvido na marca em vez de descartado.
_MARCA_SUFIXO_ABSORVE: dict[str, str] = {
    "ASIA": "ASIA MOTORS",
}
_SUFIXO_CORPORATIVO: frozenset = frozenset({"MOTORS", "MOTOR"})

# Eco da marca (ou de um apelido/parte dela) logo depois da marca já
# identificada — "Chevrolet - GM Blazer", "Mercedes-Benz Mercedes E430",
# "Mercedes Bens C180" — sem descartar, o eco vira o "modelo" e o carro real
# (Blazer/E430/C180) se perde (achado na auditoria de existência 2026-07-21:
# 20 anúncios agrupados errado por isso). Mesmo mecanismo de
# `_SUFIXO_CORPORATIVO`, mas o token descartável depende de qual é a marca.
_MODELO_ECO_MARCA: dict[str, frozenset[str]] = {
    "CHEVROLET": frozenset({"GM"}),
    "MERCEDES-BENZ": frozenset({"BENZ", "BENS", "MERCEDES"}),
}


def _separar_marca(tokens: list[str]) -> tuple[Optional[str], list[str]]:
    """
    Identifica a marca canônica no prefixo de `tokens` (já normalizados, sem
    ano) e retorna (marca, tokens_restantes). Retorna (None, tokens) quando
    nenhuma marca é reconhecida — o chamador decide o fallback.

    Absorve ou descarta sufixo corporativo solto logo após a marca ("Kia
    Motors", "Asia Motors") — ver `_MARCA_SUFIXO_ABSORVE` — antes de aplicar
    a precedência normal (catálogo/alias/modelo-exclusivo). Também descarta
    hífen solto ("Chevrolet - GM Blazer") e eco da marca (ver
    `_MODELO_ECO_MARCA`) que sobrariam no início do modelo.
    """
    marca, resto = _separar_marca_core(tokens)
    if marca is not None:
        # Tira o sufixo do modelo se ele apareceu (independente de a marca
        # estar no dict de absorção — cobre "Kia Motors" também).
        if resto and resto[0] in _SUFIXO_CORPORATIVO:
            resto = resto[1:]
        # Renomeação incondicional: mesmo quando o título não citou o
        # sufixo ("Asia Topic", sem "Motors"), a usuária pediu a marca
        # canônica "Asia Motors" sempre — não só quando o sufixo apareceu.
        if marca in _MARCA_SUFIXO_ABSORVE:
            marca = _MARCA_SUFIXO_ABSORVE[marca]
        # Hífen solto e eco da marca logo no início do modelo (loop porque
        # podem aparecer juntos: "Chevrolet - GM Blazer" tem os dois).
        eco = _MODELO_ECO_MARCA.get(marca, frozenset())
        while resto and (resto[0] == "-" or resto[0] in eco):
            resto = resto[1:]
    return (marca, resto)


def _separar_marca_core(tokens: list[str]) -> tuple[Optional[str], list[str]]:
    """
    Núcleo de `_separar_marca` (ver docstring lá pra ordem de precedência
    completa: prefixo de catálogo, alias, modelo exclusivo, modelo ambíguo).
    """
    if not tokens:
        return (None, [])
    marcas_catalogo, modelo_marca = _catalogo_vocab()

    # 1) Prefixo de catálogo (3, 2, 1 tokens). Checa _MARCA_CANONICA ANTES de
    # marcas_catalogo pra cada tamanho de prefixo: se bater, consome os N
    # tokens inteiros e retorna a forma canônica — nunca cai pro prefixo mais
    # curto deixando o resto da marca composta sobrar como "modelo" (bug da
    # auditoria 2026-07-21, ver comentário de _MARCA_CANONICA acima).
    for n in (3, 2, 1):
        if len(tokens) >= n:
            prefixo = " ".join(tokens[:n])
            if prefixo in _MARCA_CANONICA:
                return (_MARCA_CANONICA[prefixo], tokens[n:])
            if prefixo in marcas_catalogo:
                return (prefixo, tokens[n:])

    # 2) Alias de marca
    alias_alvo: Optional[str] = None
    consumidos = 0
    if len(tokens) >= 2 and f"{tokens[0]} {tokens[1]}" in _ALIASES_MARCA:
        alias_alvo, consumidos = _ALIASES_MARCA[f"{tokens[0]} {tokens[1]}"], 2
    elif tokens[0] in _ALIASES_MARCA:
        alias_alvo, consumidos = _ALIASES_MARCA[tokens[0]], 1
    if alias_alvo is not None:
        resto = tokens[consumidos:]
        for n in (2, 1):
            if len(resto) >= n and " ".join(resto[:n]) in marcas_catalogo:
                return (" ".join(resto[:n]), resto[n:])
        return (alias_alvo, resto)

    # 3) Modelo exclusivo de uma marca ("Fusca 1600")
    if tokens[0] in modelo_marca:
        return (modelo_marca[tokens[0]], tokens)

    # 3.5) Modelo ambíguo com marca dominante no clássico BR
    if tokens[0] in _MODELO_AMBIGUO_MARCA:
        return (_MODELO_AMBIGUO_MARCA[tokens[0]], tokens)

    return (None, tokens)


def sanear_marca_modelo(marca_bruta: str, modelo_bruto: str) -> tuple[str, str]:
    """
    Sanea marca/modelo vindos CRUS de uma ficha técnica estruturada (hoje só o
    Mercado Livre), onde o campo "Marca" é preenchido à mão pelo anunciante e
    costuma trazer marca+modelo junto ("Chevrolet Opala"), grafia errada
    ("Alfa Romeu", "Volkswagem") ou até lixo ("."). Usa o catálogo como fonte
    de verdade pra separar o que é marca do que é modelo — o mesmo vocabulário
    e aliases de `inferir_marca_modelo_ano`, via `_separar_marca`.

    Retorna (marca, modelo) já normalizados (maiúsculo, sem acento). Regras:
      - MARCA_NAO_IDENTIFICADA e BUGGY são preservadas (sentinela / decisão
        deliberada de não adivinhar) — nunca reinterpretadas.
      - Se a marca não é reconhecida no campo "Marca", tenta identificá-la no
        campo "Modelo" (ex.: marca="." mas modelo="Lincoln Zephyr").
      - Se nada é reconhecido, mantém o 1º token como marca (marca legítima
        fora do catálogo, ex.: KAWASAKI), ou MARCA_NAO_IDENTIFICADA se for
        palavra comum de português.

    O modelo resultante passa por `sanear_modelo` (tira a cauda de spec,
    mantém nome + trim), então a marca+modelo colados no campo "Modelo" já
    saem limpos de cilindrada/válvula/combustível etc.

    Exemplos:
        ('Chevrolet Opala', 'De Luxe 4 Portas') -> ('CHEVROLET', 'OPALA DE LUXE')
        ('Ford Mustang', 'GT500')               -> ('FORD', 'MUSTANG GT500')
        ('Alfa Romeu', 'Spider')                -> ('ALFA ROMEO', 'SPIDER')
        ('Volkswagem', 'Fusca')                 -> ('VOLKSWAGEN', 'FUSCA')
        ('.', 'Lincoln Zephyr')                 -> ('LINCOLN', 'ZEPHYR')
    """
    marca, modelo_bruto_final = _sanear_marca_modelo_bruto(marca_bruta, modelo_bruto)
    return (marca, sanear_modelo(marca, modelo_bruto_final))


def separar_marca_modelo_versao_obs(
    marca_bruta: str, modelo_bruto: str
) -> tuple[str, str, Optional[str], Optional[str]]:
    """
    Variante de `sanear_marca_modelo` que devolve modelo, versão e obs já
    separados (ver `separar_modelo_versao_obs`), em vez do modelo com
    nome+trim fundidos num string só. Mesma identificação de marca a partir
    de ficha técnica estruturada — só troca o saneamento final (auditoria
    2026-07-20, pra conectores com marca/modelo em campos próprios: ML,
    Webmotors, Superantigo, Ateliê do Carro, Armazém do Vovô, Socarrão).

    Exemplos:
        ('Chevrolet Opala', 'De Luxe 4 Portas')
            -> ('CHEVROLET', 'OPALA', 'DE LUXE', None)
        ('Volkswagem', 'Kombi Pick-Up')
            -> ('VOLKSWAGEN', 'KOMBI', None, 'PICK-UP')
    """
    marca, modelo_bruto_final = _sanear_marca_modelo_bruto(marca_bruta, modelo_bruto)
    modelo, versao, obs = separar_modelo_versao_obs(marca, modelo_bruto_final)
    return (marca, modelo, versao, obs)


def _sanear_marca_modelo_bruto(marca_bruta: str, modelo_bruto: str) -> tuple[str, str]:
    """
    Núcleo compartilhado de `sanear_marca_modelo` e
    `separar_marca_modelo_versao_obs`: identifica a marca e monta o modelo
    AINDA CRU (com a cauda de spec, sem separar versão/obs) — cada função
    pública aplica o saneamento final que precisa por cima deste resultado.
    """
    marca_norm = normalizar_texto(marca_bruta)
    modelo_toks = normalizar_texto(modelo_bruto).split()

    # Sentinela / decisão preservada: não reinterpretar a MARCA (o modelo
    # ainda é limpo — a poluição de spec independe de conhecer a marca).
    if marca_norm in _MARCAS_PRESERVADAS:
        return (marca_norm, " ".join(modelo_toks))

    marca_toks = marca_norm.split()
    marca, sobra = _separar_marca(marca_toks)

    if marca is None:
        # Campo "Marca" não reconhecido — a marca real pode estar no "Modelo".
        marca2, sobra2 = _separar_marca(modelo_toks)
        if marca2 is not None:
            return (marca2, " ".join(sobra2))
        # Nada reconhecido: 1º token vira marca (legítima fora do catálogo),
        # ou sentinela se for palavra comum / campo vazio.
        if not marca_toks or marca_toks[0] in _PALAVRAS_NAO_MARCA:
            return (
                MARCA_NAO_IDENTIFICADA,
                " ".join(marca_toks + modelo_toks),
            )
        return (
            marca_toks[0],
            " ".join(marca_toks[1:] + modelo_toks),
        )

    # Marca reconhecida. Modelo = o que sobrou do campo "Marca" + campo
    # "Modelo", sem repetir a marca canônica nem duplicar a sobra (o campo
    # "Modelo" do ML costuma repetir a marca e/ou o modelo).
    marca_set = set(marca.split())
    modelo_limpo = [t for t in modelo_toks if t not in marca_set]
    modelo_limpo_set = set(modelo_limpo)
    sobra_filtrada = [t for t in sobra if t not in marca_set and t not in modelo_limpo_set]
    return (marca, " ".join(sobra_filtrada + modelo_limpo))


def sanear_modelo(marca: str, modelo: str) -> str:
    """
    Remove a cauda de especificação do modelo (cilindrada, válvulas,
    combustível, injeção, câmbio, portas, potência e observações do
    anunciante), preservando o nome do modelo + versão/trim. Ver o bloco de
    comentário "Saneamento do MODELO" acima pra estratégia.

    `marca` serve só pra ancorar o nome do modelo no catálogo (proteger número
    que é parte do nome, tipo "Defender 110" ou "C 1504"). Idempotente: modelo
    já limpo volta igual.

    Exemplos (marca, modelo bruto -> modelo limpo):
        ('VOLKSWAGEN', 'FUSCA 1300')                 -> 'FUSCA'
        ('VOLKSWAGEN', 'FUSCA FUSCA GASOLINA')       -> 'FUSCA'
        ('VOLKSWAGEN', 'GOL GERACAO III 1.6 MI 8V')  -> 'GOL GERACAO III'
        ('CHEVROLET',  'VECTRA GSI 2.0 16V MODELO ANTIGO') -> 'VECTRA GSI'
        ('CHEVROLET',  'OPALA DE LUXE 4 PORTAS')     -> 'OPALA DE LUXE'
        ('FORD',       'ESCORT XR3 1.8 CONVERSIVEL') -> 'ESCORT XR3'
        ('LAND ROVER', 'DEFENDER 110')               -> 'DEFENDER 110'
        ('FIAT',       '147')                         -> '147'
    """
    marca_norm = normalizar_texto(marca)
    tokens = _tokenizar_modelo(marca_norm, modelo)
    if not tokens:
        return ""

    # Tira tokens da marca que vazaram pro modelo ("Fiat" repetido no modelo
    # do ML, "Motors" de "Kia Motors"), sem nunca esvaziar o modelo.
    marca_set = set(marca_norm.split())
    sem_marca = [t for t in tokens if t not in marca_set]
    if sem_marca:
        tokens = sem_marca

    # Ancora o nome do modelo no catálogo, pulando spec solto na frente se
    # precisar (protege número que é parte do nome; "Puma 1.6 Gte" acha
    # "Gte" pulando a cilindrada); na falta de qualquer âncora, mantém o
    # 1º token — exceto se ele mesmo for lixo puro (ver _localizar_modelo).
    pular, tam_ancora = _localizar_modelo(marca_norm, tokens, _SPEC_PALAVRAS)
    if tam_ancora == 0:
        return ""
    inicio = pular + tam_ancora

    corte = _indice_corte_spec(tokens, inicio)
    resultado = " ".join(_limpar_tokens(tokens[pular:corte]))
    return _canonizar_grafia(marca_norm, resultado)


def _limpar_tokens(tokens: list[str]) -> list[str]:
    """
    Apara pontuação solta nas pontas de cada token ("Expres." -> "Expres",
    "-" -> ""), descarta vazios e faz dedup preservando a ordem ("Fusca
    Fusca" -> "Fusca"). Compartilhado por `sanear_modelo` e
    `separar_modelo_versao_obs`.
    """
    vistos: set = set()
    final: list[str] = []
    for t in tokens:
        t = t.strip(".-")
        if t and t not in vistos:
            vistos.add(t)
            final.append(t)
    return final


# ────────────────────────────────────────────────
# Separação VERSÃO / OBS dentro do que `sanear_modelo` mantém como modelo
# (auditoria 2026-07-20)
# ────────────────────────────────────────────────
#
# `sanear_modelo` mantém nome+trim juntos num string só (decisão de
# 2026-07-17). Agora a usuária quer o trim/versão (GLX, SS, "Geração I CL")
# em campo próprio — e pediu também que o residual que não é trim nem spec
# (carroceria/tração: "Cabine Estendida", "Pick-Up", "4x4", "Sedan") não seja
# descartado como as demais observações de venda/estado, e sim preservado
# num campo "obs" à parte, pra não poluir o dropdown de versão.
#
# Reaproveita a mesma âncora de catálogo (`_maior_prefixo_modelo`) e o mesmo
# corte de spec (`_indice_corte_spec`) de `sanear_modelo` — a diferença é que
# aqui o corte usa um vocabulário de spec SEM as palavras de carroceria (elas
# não devem interromper a busca por specs de verdade: em "Civic Sedan Lx" o
# "Lx" vem DEPOIS de "Sedan" e precisa continuar sendo capturado). O que
# sobra entre a âncora e o corte é então repartido token a token: carroceria/
# tração vai pra obs, o resto vira versão.

# Carroceria/tração/chassi — atributo real do carro, mas não é trim que pesa
# no preço como GLX/SS/COMODORO. Cobre o mesmo campo semântico que uma parte
# de `_MODELO_OBSERVACAO` já cortava (CABINE, CARROCERIA, CURTO, LONGO) mais
# o vocabulário achado na auditoria de carroceria (PICK-UP, SEDAN, FURGAO,
# 4X4...). Deliberadamente não reaproveita `_MODELO_OBSERVACAO` porque
# `sanear_modelo` continua descartando essas palavras (não muda de
# comportamento) — aqui elas só mudam de destino (obs em vez de lixo).
_CARROCERIA_TRACAO: frozenset = frozenset({
    "CABINE", "CAB", "CAB.", "CARROCERIA", "CHASSI", "CHAS", "CHAS.",
    "CURTO", "LONGO", "ESTENDIDA", "DUPLA", "SIMPLES",
    "PICK-UP", "PICKUP", "SEDAN", "SED", "SED.", "FURGAO", "FURGONETE", "PERUA",
    "COUPE", "CUPE", "WEEKEND", "CABRIO", "CABRIOLET", "CONVERSIVEL",
    "4X4", "4X2", "TRACAO",
    # Português (auditoria 2026-07-20, achado investigando Toyota
    # Bandeirante: "Band.Jipe Cap.de Aço", "Band.Picape") — mesmo campo
    # semântico das entradas em inglês acima. Forma sem ponto também
    # precisa estar aqui: _limpar_tokens tira o ponto ao gravar, então um
    # reprocessamento futuro que recombine essas colunas já vê "CAP" sem
    # ponto (achado reprocessando de novo nesta mesma rodada).
    "JIPE", "PICAPE", "CAP", "CAP.", "CAPOTA", "LONA", "ACO", "TETO",
})

# Cilindrada grudada numa letra de trim sem espaço ("1300L", "1600S" — Fusca/
# Kombi clássicos). \d{4} solto já é cilindrada pura (ver _SPEC_REGEX) e sai
# inteiro; aqui, quando vem com letra grudada, separa: cilindrada descartada,
# letra vira versão (é o mesmo "L"/"S" que apareceria solto noutra fonte).
# Não confundir com nomenclatura tipo Mercedes/BMW ("160", "230CE") — essas
# não batem aqui por serem 2-3 dígitos, não 4 (ver docstring da função).
_CILINDRADA_TRIM_GLUED = re.compile(r"^(\d{4})([A-Z]{1,3})$")


def separar_modelo_versao_obs(marca: str, modelo: str) -> tuple[str, Optional[str], Optional[str]]:
    """
    Variante granular de `sanear_modelo`: separa nome do modelo, versão/trim
    (GLX, SS, "Geração I CL"...) e observação residual de carroceria/tração
    ("Cabine Estendida", "Pick-Up", "Sedan", "4x4") em três campos, em vez de
    devolver tudo junto num string só. Reaproveita a mesma âncora de
    catálogo e o mesmo corte de spec de `sanear_modelo` — só reparte o que
    sobra entre "versao" e "obs" ao invés de manter junto.

    Números de motor colados a uma letra de trim (Fusca/Kombi "1300L",
    "1600S") são divididos: a cilindrada é descartada, a letra vira versão.
    Números de 2-3 dígitos que são nome comercial (Mercedes "Classe A 160",
    BMW "328i") não batem nesse padrão e ficam intactos na versão — não há
    tabela por marca pra isso porque a ambiguidade real só aparece na forma
    grudada de 4 dígitos, e essa é sempre cilindrada nos clássicos BR do
    banco (nenhuma marca do catálogo usa código comercial de 4 dígitos+letra
    grudados). Se aparecer um caso assim, tratar em rodada futura.

    Retorna (modelo, versao, obs); versao/obs são None quando não há nada
    nessa categoria. Quando não há obs, `f"{modelo} {versao}".strip()` bate
    com `sanear_modelo(marca, modelo_bruto)` (a diferença entre as duas
    funções é só o que cada uma faz com a carroceria/tração: uma descarta,
    a outra preserva à parte).

    Exemplos:
        ('VOLKSWAGEN', 'Gol Geracao I Cl')              -> ('GOL', 'GERACAO I CL', None)
        ('CHEVROLET', 'S10 Americana Cabine Estendida') -> ('S10', 'AMERICANA', 'CABINE ESTENDIDA')
        ('VOLKSWAGEN', 'Fusca 1300L')                   -> ('FUSCA', 'L', None)
        ('VOLKSWAGEN', 'Kombi Pick-Up')                 -> ('KOMBI', None, 'PICK-UP')
        ('HONDA', 'Civic Sedan Lx')                     -> ('CIVIC', 'LX', 'SEDAN')
    """
    marca_norm = normalizar_texto(marca)
    tokens = _tokenizar_modelo(marca_norm, modelo)
    if not tokens:
        return ("", None, None)

    # Tira tokens da marca que vazaram pro modelo, igual sanear_modelo.
    marca_set = set(marca_norm.split())
    sem_marca = [t for t in tokens if t not in marca_set]
    if sem_marca:
        tokens = sem_marca

    spec_sem_carroceria = _SPEC_PALAVRAS - _CARROCERIA_TRACAO
    pular, tam_ancora = _localizar_modelo(marca_norm, tokens, spec_sem_carroceria)
    if tam_ancora == 0:
        return ("", None, None)
    inicio = pular + tam_ancora

    # Corte de spec sem carroceria/tração — essas palavras não devem
    # interromper a varredura (senão trim que vem depois delas, tipo "Sedan
    # Lx", ficaria fora do alcance do corte e seria perdido).
    corte = _indice_corte_spec(tokens, inicio, spec_sem_carroceria)

    modelo_final = " ".join(_limpar_tokens(tokens[pular:inicio]))
    # Duas grafias válidas no catálogo pro mesmo modelo (ex.: "Karmann
    # Ghia"/"Karmann-Ghia") — reaplica a canonização por cima do nome JÁ
    # ancorado (chave é a frase inteira, não mais um token cru).
    modelo_final = _MODELO_ABREVIACAO.get((marca_norm, modelo_final), modelo_final)
    # Unifica grafia hífen/espaço com a do catálogo ('C-180'→'C 180').
    modelo_final = _canonizar_grafia(marca_norm, modelo_final)

    # Título repetido colado ("Mercedes-Benz Classe Slk ... Mercedes-Benz
    # Classe Slk 230 Kompressor") faz o nome do modelo vazar de novo na
    # cauda — filtrado aqui como o "Fiat"/"Motors" que vaza da marca.
    modelo_tokens_set = set(tokens[pular:inicio])

    versao_tokens: list[str] = []
    obs_tokens: list[str] = []
    for i in range(inicio, corte):
        t = tokens[i]
        if t in modelo_tokens_set:
            continue
        glued = _CILINDRADA_TRIM_GLUED.match(t)
        if glued:
            versao_tokens.append(glued.group(2))
        elif t in _CARROCERIA_TRACAO:
            obs_tokens.append(t)
        elif t in _CORES:
            # Cor nunca é informação de versão (usuária pediu 2026-07-20) —
            # descartada, nem versão nem obs. Exceção: "Série Prata"/"Série
            # Ouro" são edições reais da VW, não a cor da pintura; só
            # protegida quando vem logo depois de "Série".
            if i > 0 and tokens[i - 1] == "SERIE":
                versao_tokens.append(t)
        else:
            versao_tokens.append(t)

    versao_limpa = _limpar_tokens(versao_tokens)
    # Dígito solto sozinho como versão inteira ("Passat 2", "ES-300 3",
    # "300-E 3") não é trim de verdade — ninguém nomeia uma versão só de
    # "3". É ambiguidade da própria fonte (poderia ser "2.0"/"3.0" truncado
    # no anúncio original, geração abreviada, etc.) sem contexto suficiente
    # pra resolver; melhor descartar do que preservar como se fosse
    # informação (auditoria 2026-07-20, achado ao revisar os casos "número
    # virou versão" — confirmado batendo a URL original do OLX: o "2"/"3"
    # já vem assim no título digitado pelo vendedor, não é truncamento
    # nosso).
    if len(versao_limpa) == 1 and re.fullmatch(r"\d", versao_limpa[0]):
        versao_limpa = []

    versao = " ".join(versao_limpa)
    obs = " ".join(_limpar_tokens(obs_tokens))
    return (modelo_final, versao or None, obs or None)
