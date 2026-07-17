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

    # Passos 1-3.5: identificar a marca no prefixo dos tokens (catálogo,
    # alias, modelo-exclusivo, modelo-ambíguo). Extraído pra _separar_marca
    # porque a mesma lógica sanea marca/modelo vindos crus de ficha técnica.
    marca, resto = _separar_marca(tokens_sem_ano)
    if marca is not None:
        return (marca, " ".join(resto), ano)

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


def _separar_marca(tokens: list[str]) -> tuple[Optional[str], list[str]]:
    """
    Identifica a marca canônica no prefixo de `tokens` (já normalizados, sem
    ano) e retorna (marca, tokens_restantes). Retorna (None, tokens) quando
    nenhuma marca é reconhecida — o chamador decide o fallback.

    Ordem de precedência (a mesma que `inferir_marca_modelo_ano` sempre usou):
      1. Prefixo mais longo que seja marca do catálogo (cobre compostas como
         "LAND ROVER", "MP LAFER"; prefixos rebaixados por _MARCA_CANONICA são
         pulados aqui pra não engolir tokens de modelo).
      2. Alias de marca (2 tokens antes de 1: "MERCEDES BENZ" > "MERCEDES");
         o alias pode ser só um selo na frente da marca real ("GM Oldsmobile"),
         nesse caso a marca de catálogo que vem depois prevalece.
      3. Primeiro token é um modelo que identifica uma única marca ("FUSCA").
      3.5. Modelo ambíguo com marca dominante no clássico BR ("147", "CARAVAN").

    Nos casos 3/3.5 o token que identificou a marca É parte do modelo, então
    ele permanece em tokens_restantes (a marca é implícita, não estava escrita).
    """
    if not tokens:
        return (None, [])
    marcas_catalogo, modelo_marca = _catalogo_vocab()

    # 1) Prefixo de catálogo (3, 2, 1 tokens)
    for n in (3, 2, 1):
        if len(tokens) >= n:
            prefixo = " ".join(tokens[:n])
            if prefixo in marcas_catalogo and prefixo not in _MARCA_CANONICA:
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

    Exemplos:
        ('Chevrolet Opala', 'De Luxe 4 Portas') -> ('CHEVROLET', 'OPALA DE LUXE 4 PORTAS')
        ('Ford Mustang', 'GT500')               -> ('FORD', 'MUSTANG GT500')
        ('Alfa Romeu', 'Spider')                -> ('ALFA ROMEO', 'SPIDER')
        ('Volkswagem', 'Fusca')                 -> ('VOLKSWAGEN', 'FUSCA')
        ('.', 'Lincoln Zephyr')                 -> ('LINCOLN', 'ZEPHYR')
    """
    marca_norm = normalizar_texto(marca_bruta)
    modelo_toks = normalizar_texto(modelo_bruto).split()

    # Sentinela / decisão preservada: não reinterpretar.
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
            return (MARCA_NAO_IDENTIFICADA, " ".join(marca_toks + modelo_toks))
        return (marca_toks[0], " ".join(marca_toks[1:] + modelo_toks))

    # Marca reconhecida. Modelo = o que sobrou do campo "Marca" + campo
    # "Modelo", sem repetir a marca canônica nem duplicar a sobra (o campo
    # "Modelo" do ML costuma repetir a marca e/ou o modelo).
    marca_set = set(marca.split())
    modelo_limpo = [t for t in modelo_toks if t not in marca_set]
    modelo_limpo_set = set(modelo_limpo)
    sobra_filtrada = [t for t in sobra if t not in marca_set and t not in modelo_limpo_set]
    return (marca, " ".join(sobra_filtrada + modelo_limpo))
