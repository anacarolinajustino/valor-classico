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
    - Colapsa espaços duplicados
    - Remove pontuação irrelevante (mantém hífen e ponto)
    """
    sem_acento = remover_acentos(texto)
    maiusculo = sem_acento.upper()
    # Colapsar espaços
    sem_espacos_dup = re.sub(r"\s+", " ", maiusculo).strip()
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
}

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

    # Detectar ano: último token de 4 dígitos no intervalo 1900-2099
    ano: Optional[int] = None
    tokens_sem_ano = tokens[:]
    for i in range(len(tokens) - 1, -1, -1):
        match = re.fullmatch(r"(19|20)\d{2}", tokens[i])
        if match:
            ano = int(tokens[i])
            tokens_sem_ano = tokens[:i] + tokens[i + 1 :]
            break

    if not tokens_sem_ano:
        return ("", "", ano)

    marcas_catalogo, modelo_marca = _catalogo_vocab()

    # 1) Prefixo mais longo que seja marca conhecida do catálogo
    for n in (3, 2, 1):
        if len(tokens_sem_ano) >= n:
            prefixo = " ".join(tokens_sem_ano[:n])
            if prefixo in marcas_catalogo:
                return (prefixo, " ".join(tokens_sem_ano[n:]), ano)

    # 2) Alias de marca (2 tokens antes de 1: "MERCEDES BENZ" > "MERCEDES")
    if len(tokens_sem_ano) >= 2:
        duo = f"{tokens_sem_ano[0]} {tokens_sem_ano[1]}"
        if duo in _ALIASES_MARCA:
            return (_ALIASES_MARCA[duo], " ".join(tokens_sem_ano[2:]), ano)
    if tokens_sem_ano[0] in _ALIASES_MARCA:
        return (_ALIASES_MARCA[tokens_sem_ano[0]], " ".join(tokens_sem_ano[1:]), ano)

    # 3) Título começa pelo modelo ("Fusca 1600") e o modelo identifica
    #    uma única marca no catálogo — o modelo mantém todos os tokens
    if tokens_sem_ano[0] in modelo_marca:
        return (modelo_marca[tokens_sem_ano[0]], " ".join(tokens_sem_ano), ano)

    # 4) Fallback original: primeiro token é a marca
    marca = tokens_sem_ano[0]
    modelo = " ".join(tokens_sem_ano[1:]) if len(tokens_sem_ano) > 1 else ""

    return (marca, modelo, ano)
