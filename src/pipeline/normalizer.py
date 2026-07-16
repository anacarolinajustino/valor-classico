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
    "VOIAGE": "VOLKSWAGEN",  # grafia errada de "Voyage" (o modelo, não a marca)
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
    # MP Lafer é o mesmo fabricante brasileiro de kit car que "Lafer"
    # sozinho (ver LAFER no fallback) — "MP" é a sigla da fábrica.
    "MP LAFFER": "LAFER",
    "MP LAFER-": "LAFER",  # hífen do título original ("Lafer- 1978/78...")
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
}

# O catálogo geral grafa a mesma marca de mais de um jeito ("WILLYS" e
# "WILLYS OVERLAND" são o mesmo fabricante) — a regra "prefixo mais longo
# primeiro" do passo 1 preferiria a forma composta, fragmentando o grupo já
# estabelecido (usuária pediu 2026-07-15 pra manter só "WILLYS").
_MARCA_CANONICA: dict[str, str] = {
    "WILLYS OVERLAND": "WILLYS",
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

# Cache do vocabulário derivado do catálogo canônico:
# (marcas conhecidas, primeiro-token-de-modelo -> marca exclusiva)
_vocab_catalogo: Optional[tuple[set, dict]] = None


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

    # 1) Prefixo mais longo que seja marca conhecida do catálogo. Prefixos
    # rebaixados por _MARCA_CANONICA são pulados aqui (não só renomeados no
    # retorno) pra não engolir de "modelo" um token que já vira a forma
    # canônica mais curta ("Willys Overland" não pode consumir "Overland"
    # inteiro só pra depois virar marca="WILLYS" e modelo="").
    for n in (3, 2, 1):
        if len(tokens_sem_ano) >= n:
            prefixo = " ".join(tokens_sem_ano[:n])
            if prefixo in marcas_catalogo and prefixo not in _MARCA_CANONICA:
                return (prefixo, " ".join(tokens_sem_ano[n:]), ano)

    # 2) Alias de marca (2 tokens antes de 1: "MERCEDES BENZ" > "MERCEDES")
    alias_alvo: Optional[str] = None
    consumidos = 0
    if len(tokens_sem_ano) >= 2:
        duo = f"{tokens_sem_ano[0]} {tokens_sem_ano[1]}"
        if duo in _ALIASES_MARCA:
            alias_alvo, consumidos = _ALIASES_MARCA[duo], 2
    if alias_alvo is None and tokens_sem_ano[0] in _ALIASES_MARCA:
        alias_alvo, consumidos = _ALIASES_MARCA[tokens_sem_ano[0]], 1
    if alias_alvo is not None:
        resto = tokens_sem_ano[consumidos:]
        # O alias pode ser só um selo na frente da marca real ("GM
        # Oldsmobile Tornado") — se o que vem depois já é marca do
        # catálogo, ela prevalece sobre o alias.
        for n in (2, 1):
            if len(resto) >= n and " ".join(resto[:n]) in marcas_catalogo:
                return (" ".join(resto[:n]), " ".join(resto[n:]), ano)
        return (alias_alvo, " ".join(resto), ano)

    # 3) Título começa pelo modelo ("Fusca 1600") e o modelo identifica
    #    uma única marca no catálogo — o modelo mantém todos os tokens
    if tokens_sem_ano[0] in modelo_marca:
        return (modelo_marca[tokens_sem_ano[0]], " ".join(tokens_sem_ano), ano)

    # 3.5) Modelo ambíguo no catálogo geral mas com marca dominante neste
    # recorte de clássico brasileiro ("147 1.3L", "Caravan Comodoro") — ver
    # dict acima.
    if tokens_sem_ano[0] in _MODELO_AMBIGUO_MARCA:
        return (_MODELO_AMBIGUO_MARCA[tokens_sem_ano[0]], " ".join(tokens_sem_ano), ano)

    # 4) Fallback: primeiro token é a marca — mas só quando ele não é uma
    # palavra comum de português (adjetivo/conectivo/substantivo de venda)
    # que nunca é nome de marca. Sem essa guarda, "Veículo Ótimo Estado De
    # Conservação" virava marca="OTIMO" (usuária pediu 2026-07-15, 3ª
    # rodada: todo anúncio sem marca explícita no título deve cair em
    # MARCA_NAO_IDENTIFICADA — sinalizado pra revisão manual — em vez de
    # aceitar qualquer primeiro token como se fosse marca real).
    if tokens_sem_ano[0] in _PALAVRAS_NAO_MARCA:
        return (MARCA_NAO_IDENTIFICADA, " ".join(tokens_sem_ano), ano)

    marca = tokens_sem_ano[0]
    modelo = " ".join(tokens_sem_ano[1:]) if len(tokens_sem_ano) > 1 else ""

    return (marca, modelo, ano)
