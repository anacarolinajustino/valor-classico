"""
Carregamento do catálogo canônico de veículos a partir do CSV.

Estratégia de matching:
1. Exact match por (marca_normalized, modelo_normalized) → confidence=high, strategy=normalized_exact
2. Fuzzy match com difflib.SequenceMatcher threshold >= 0.80 → confidence=medium, strategy=fuzzy
3. Sem match → confidence=unmatched, strategy=none

Quando há match de marca+modelo e o anúncio tem versão, tenta também normalizar
a versão contra as versões canônicas do catálogo para esse (marca, modelo, ano).
"""
from __future__ import annotations

import csv
import difflib
import logging
from pathlib import Path
from typing import Optional

from src.pipeline.normalizer import normalizar_texto
from src.pipeline.schema import Anuncio

logger = logging.getLogger(__name__)

CSV_PADRAO = Path(__file__).parent.parent.parent / "data" / "base_marcamodelo.csv"

# Suplemento manual: modelos ausentes do CSV principal.
# Chaves já normalizadas (uppercase, sem acento). Ranges = anos de produção no Brasil.
_SUPLEMENTO: dict[tuple[str, str], set[int]] = {
    ("FIAT",    "IDEA"):  set(range(2005, 2017)),
    ("RENAULT", "LOGAN"): set(range(2006, 2016)),
    ("PEUGEOT", "207"):   set(range(2007, 2014)),
    ("HONDA",   "CR-V"):  set(range(1997, 2024)),
    ("TOYOTA",  "SW4"):   set(range(1992, 2024)),
    # Marcas clássicas ausentes do CSV, vistas em anúncios reais coletados
    # (auditoria 2026-07-14). Anos aproximados de produção.
    ("DKW",     "BELCAR"):        set(range(1958, 1968)),
    ("DKW",     "VEMAGUET"):      set(range(1958, 1968)),
    ("DKW",     "CAICARA"):       set(range(1962, 1965)),
    ("DKW",     "MUNGA"):         set(range(1958, 1969)),
    ("AUSTIN",  "A40"):           set(range(1947, 1957)),
    ("AUSTIN",  "HEALEY SPRITE"): set(range(1958, 1972)),
    ("AUSTIN",  "HEALEY 3000"):   set(range(1959, 1968)),
    ("REO",     "SPEED WAGON"):   set(range(1915, 1954)),
    ("REO",     "FLYING CLOUD"):  set(range(1927, 1937)),
    ("SCANIA",  "LK 111"):        set(range(1976, 1982)),
    ("SCANIA",  "L 111"):         set(range(1975, 1982)),
    ("SCANIA",  "113"):           set(range(1991, 1999)),
    # Motos/afins clássicos: usuário decidiu (2026-07-14) que ficam no banco
    ("YAMAHA",  "DT"):            set(range(1974, 2001)),
    ("YAMAHA",  "RD 350"):        set(range(1973, 1996)),
    ("YAMAHA",  "DRAG STAR"):     set(range(1997, 2001)),
    ("LAMBRETTA", "LI 150"):      set(range(1958, 1971)),
    ("LAMBRETTA", "STANDARD"):    set(range(1955, 1966)),
    ("PIAGGIO", "VESPA"):         set(range(1946, 2001)),
    ("HARLEY-DAVIDSON", "SPRINGER"):      set(range(1988, 2001)),
    ("HARLEY-DAVIDSON", "SPORTSTER"):     set(range(1957, 2001)),
    ("HARLEY-DAVIDSON", "ELECTRA GLIDE"): set(range(1965, 2001)),
    ("CALOI",   "MOBILETE"):      set(range(1970, 1996)),
    # Grafia com espaço: o CSV só tem "KARMANN-GHIA" (hifenizado), mas os
    # anúncios escrevem "Karmann Ghia" — sem esta entrada o primeiro token
    # não casa e a marca não é inferida.
    ("VOLKSWAGEN", "KARMANN GHIA"): set(range(1962, 1976)),
    # Modelos clássicos brasileiros ausentes do CSV (auditoria 2026-07-15):
    # apareciam sozinhos no título, sem a marca na frente, e o token não é
    # ambíguo entre marcas no mercado brasileiro (diferente de CARAVAN,
    # KADETT, BLAZER, SILVERADO e RANGER, que o catálogo geral compartilha
    # entre mais de uma marca e por isso ficam de fora de propósito).
    ("CHEVROLET", "DIPLOMATA"): set(range(1980, 1993)),
    ("CHEVROLET", "COMODORO"):  set(range(1977, 1987)),
    ("CHEVROLET", "CHEYENNE"):  set(range(1975, 1997)),
    ("FORD",      "F100"):      set(range(1957, 1993)),
    ("FORD",      "F150"):      set(range(1975, 1997)),
    ("FORD",      "F1000"):     set(range(1980, 1998)),
    ("FORD",      "F75"):       set(range(1973, 1980)),
    ("FORD",      "XR3"):       set(range(1984, 1993)),
    ("MERCEDES-BENZ", "C280"):  set(range(1993, 2001)),
    # Modelos cujo número É o nome da linha, não um trim (auditoria
    # 2026-07-20: sem a forma composta cadastrada, a nova separação de
    # versão — ver `separar_modelo_versao_obs` — arrancava o número do nome
    # e o modelo virava só "DEFENDER"/"SERIE"/"LS", perdendo qual carro é.
    # Diferente de "Galaxie 500"/"Charger 500" (esses SÃO trim de época,
    # ficam certos como versão) — aqui o número distingue carros diferentes
    # (chassi/geração/linha), não uma edição do mesmo carro.
    ("LAND ROVER", "DEFENDER 90"):   set(range(1983, 2017)),
    ("LAND ROVER", "DEFENDER 110"):  set(range(1983, 2017)),
    ("LAND ROVER", "DISCOVERY 1"):   set(range(1989, 1999)),
    ("LAND ROVER", "SERIE 1"):       set(range(1948, 1959)),  # "Land Rover Series I"
    ("MERCEDES-BENZ", "SPRINTER 310"): set(range(1995, 2007)),
    ("MERCEDES-BENZ", "SPRINTER 312"): set(range(1995, 2007)),
    ("LEXUS", "LS 400"):    set(range(1989, 2001)),
    ("BMW", "SERIE 3"):     set(range(1975, 2025)),
    ("BMW", "SERIE 5"):     set(range(1972, 2025)),
    # "Classe X" da Mercedes: só "CLASSE A" estava no CSV base — as demais
    # letras caíam no fallback "CLASSE" sozinho (usuária pediu 2026-07-20).
    # Bônus: protege "Classe E" de perder o E pro corte de spec (ver "E" em
    # _SPEC_OBSERVACAO — cauda começa a ser varrida só depois do que a
    # âncora consome, então uma âncora de 2 tokens tira "E" do alcance do
    # corte em vez de precisar mexer no set global de spec).
    ("MERCEDES-BENZ", "CLASSE C"):   set(range(1993, 2001)),
    ("MERCEDES-BENZ", "CLASSE E"):   set(range(1993, 2001)),
    ("MERCEDES-BENZ", "CLASSE S"):   set(range(1991, 2001)),
    ("MERCEDES-BENZ", "CLASSE CLK"): set(range(1997, 2001)),
    ("MERCEDES-BENZ", "CLASSE SLK"): set(range(1996, 2001)),
    # Picapes GM linha C/D com grafia espaçada ("C 10", diferente de "C10"/
    # "C1500" já cobertos por _MODELO_AMBIGUO_MARCA) — o número é a
    # capacidade de carga (meia/3-quartos de tonelada), não um trim.
    ("CHEVROLET", "C 10"):  set(range(1960, 1988)),
    ("CHEVROLET", "C 20"):  set(range(1960, 1988)),
    ("CHEVROLET", "D 20"):  set(range(1975, 1998)),
    # "Galaxie 500"/"Charger 500" nasceram como trim, mas nos 21+1 anúncios
    # do banco NUNCA aparecem sem o "500" nem com outro trim alternativo —
    # na prática funcionam como o nome pelo qual o carro é conhecido, igual
    # "Fusca" (auditoria 2026-07-20, amostra completa revisada).
    ("FORD",  "GALAXIE 500"): set(range(1959, 1975)),
    ("DODGE", "CHARGER 500"): set(range(1969, 1971)),
    ("AUSTIN", "A 40"):       set(range(1947, 1958)),
    # Motos: cilindrada faz parte do nome comercial (CB400, CG125...), não é
    # trim — mesmo raciocínio dos carros acima.
    ("HONDA", "CB 400"):    set(range(1978, 1985)),
    ("HONDA", "CG 125"):    set(range(1976, 2005)),
    ("HONDA", "ML 125"):    set(range(1982, 1988)),
    ("HONDA", "SHADOW 750"): set(range(1997, 2010)),
    # Nome de modelo que É um número/cilindrada por convenção histórica da
    # marca — sem isso, o saneamento de spec (que trata "3.4"/"2CV" como
    # cilindrada/potência) apagava o carro inteiro (auditoria 2026-07-20,
    # revisão de "modelo em branco ou com motorização").
    ("CITROEN", "2CV"):  set(range(1948, 1991)),
    ("RENAULT", "4CV"):  set(range(1947, 1962)),
    ("JAGUAR",  "3.4"):  set(range(1957, 1968)),
    ("JAGUAR",  "3.8"):  set(range(1959, 1968)),
    ("SANTA MATILDE", "4.1"): set(range(1975, 1985)),
    # Auditoria de EXISTÊNCIA 2026-07-21: pares que já apareciam corretos
    # (marca/modelo batem com o título original) mas o CSV base não tem —
    # ou porque o carro é raro/regional demais pro scrape, ou porque a
    # marca no banco é uma variante deliberada (ver _ALIAS_MARCA em
    # normalizer.py: "ASIA" -> "ASIA MOTORS", por pedido da usuária
    # 2026-07-15) que não bate com a grafia curta do CSV. Confirmados por
    # título + conhecimento histórico; Simca Tufão, CBT Javali e Mercury
    # Eight confirmados via pesquisa (fontes: autoentusiastas.com.br,
    # pt.wikipedia.org/wiki/CBT_Javali, classiccars.fandom.com).
    ("FIAT", "PREMIO"): set(range(1985, 1997)),  # CSV tem só "PREMIOTempra" (scrape colado)
    ("CHEVROLET", "CORVAIR"): set(range(1960, 1970)),
    ("JEEP", "RENEGADE"): set(range(2015, 2026)),
    ("SIMCA", "TUFAO"): set(range(1964, 1968)),
    ("MERCURY", "EIGHT"): set(range(1939, 1952)),
    ("MERCURY", "MARQUIS"): set(range(1967, 1975)),
    ("DODGE", "MONACO"): set(range(1965, 1979)),
    ("FORD", "DELUXE"): set(range(1935, 1941)),
    ("LEXUS", "ES300"): set(range(1991, 2002)),
    ("PUMA", "GTE"): set(range(1973, 1981)),
    ("PUMA", "GTC"): set(range(1980, 1986)),
    # Motos Honda CB: cilindrada é parte do nome comercial (mesmo raciocínio
    # do CB 400 acima).
    ("HONDA", "CB 500"): set(range(1971, 1979)),
    ("HONDA", "CB 450"): set(range(1965, 1975)),
    ("HONDA", "CB 360"): set(range(1974, 1977)),
    # Fabricantes brasileiros de buggy/jipe: catálogo tem a marca mas não
    # o modelo genérico "Buggy"/nome comercial específico usado nos anúncios.
    ("BUGRE", "BUGGY"): set(range(1968, 2001)),
    ("BRM", "BUGGY"): set(range(1971, 2001)),
    ("FYBER", "BUGGY"): set(range(1980, 1999)),
    ("FYBER", "STAR"): set(range(1985, 1999)),
    ("ENGESA", "4X4"): set(range(1974, 1995)),
    ("CBT", "JAVALI"): set(range(1988, 1996)),
    # "ASIA MOTORS" é a marca completa (usuária pediu 2026-07-15, ver
    # _MARCA_SUFIXO_ABSORVE em normalizer.py); CSV grafa só "ASIA".
    ("ASIA MOTORS", "TOWNER"): set(range(1990, 1999)),
    ("ASIA MOTORS", "TOPIC"): set(range(1990, 1999)),
    ("ASIA MOTORS", "HI-TOPIC"): set(range(1990, 1999)),
    ("ASIA MOTORS", "ROCSTA"): set(range(1993, 1999)),
    ("FORD", "VICTORIA"): set(range(1928, 1935)),
    ("STUDEBAKER", "CHAMPION"): set(range(1939, 1959)),
}

# (marca_norm, modelo_norm) -> set de anos disponíveis
_catalogo: dict[tuple[str, str], set[int]] = {}
# (marca_norm, modelo_norm, ano) -> lista de versões normalizadas do catálogo
_versoes: dict[tuple[str, str, int], list[str]] = {}
_carregado = False


def carregar_catalogo(caminho: Optional[Path] = None) -> dict[tuple[str, str], set[int]]:
    """
    Carrega o CSV do catálogo em memória como dict indexado por
    (marca_normalizada, modelo_normalizado) -> set de anos.

    Idempotente: se já carregado, retorna o cache existente.
    """
    global _catalogo, _versoes, _carregado

    if _carregado:
        return _catalogo

    caminho_csv = caminho or CSV_PADRAO
    catalogo: dict[tuple[str, str], set[int]] = {}
    versoes: dict[tuple[str, str, int], list[str]] = {}

    try:
        with open(caminho_csv, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for linha in reader:
                marca_raw = linha.get("nome_marca", "").strip()
                modelo_raw = linha.get("nome_modelo", "").strip()
                ano_raw = linha.get("ano_modelo", "").strip()
                versao_raw = linha.get("nome_versao", "").strip()

                if not marca_raw or not modelo_raw:
                    continue

                marca_norm = normalizar_texto(marca_raw)
                modelo_norm = normalizar_texto(modelo_raw)
                chave = (marca_norm, modelo_norm)

                try:
                    ano = int(ano_raw) if ano_raw else 0
                except ValueError:
                    ano = 0

                catalogo.setdefault(chave, set())
                if ano > 0:
                    catalogo[chave].add(ano)
                    if versao_raw:
                        chave_v = (marca_norm, modelo_norm, ano)
                        versoes.setdefault(chave_v, []).append(normalizar_texto(versao_raw))

        _catalogo = catalogo
        _versoes = versoes
        _carregado = True
        logger.info("Catálogo carregado: %d entradas de marca+modelo", len(catalogo))

    except FileNotFoundError:
        logger.warning("CSV do catálogo não encontrado: %s", caminho_csv)
        _catalogo = {}
        _versoes = {}

    for chave, anos_sup in _SUPLEMENTO.items():
        _catalogo.setdefault(chave, set()).update(anos_sup)
    logger.info("Suplemento aplicado: %d entradas adicionadas/estendidas", len(_SUPLEMENTO))
    _carregado = True

    return _catalogo


def resetar_cache() -> None:
    """Reseta o cache do catálogo (útil para testes)."""
    global _catalogo, _versoes, _carregado
    _catalogo = {}
    _versoes = {}
    _carregado = False


def match_anuncio(anuncio: Anuncio, caminho: Optional[Path] = None) -> Anuncio:
    """
    Tenta fazer matching do anúncio com o catálogo canônico.

    Estratégia:
    1. Exact match por (marca_norm, modelo_norm) → confidence=high, strategy=normalized_exact
    2. Fuzzy match com SequenceMatcher >= 0.80 → confidence=medium, strategy=fuzzy
    3. Sem match → confidence=unmatched, strategy=none

    Quando há match, tenta também normalizar a versão do anúncio contra as versões
    canônicas do catálogo para aquele (marca, modelo, ano).

    Retorna novo Anuncio com match_confidence, match_strategy e versao atualizados.
    """
    catalogo = carregar_catalogo(caminho)

    if not catalogo:
        return anuncio

    marca_norm = normalizar_texto(anuncio.marca)
    modelo_norm = normalizar_texto(anuncio.modelo)

    # 1. Exact match
    if (marca_norm, modelo_norm) in catalogo:
        versao_canonical = _normalizar_versao(marca_norm, modelo_norm, anuncio.ano, anuncio.versao)
        return _com_match(anuncio, "high", "normalized_exact", versao_canonical)

    # 2. Fuzzy match — busca apenas dentro dos modelos da mesma marca
    marcas_catalogo = {chave[0] for chave in catalogo}
    melhor_marca = _melhor_fuzzy(marca_norm, list(marcas_catalogo), threshold=0.80)

    if melhor_marca:
        modelos_da_marca = [chave[1] for chave in catalogo if chave[0] == melhor_marca]
        melhor_modelo = _melhor_fuzzy(modelo_norm, modelos_da_marca, threshold=0.80)
        if melhor_modelo:
            return _com_match(anuncio, "medium", "fuzzy", None)

    return _com_match(anuncio, "unmatched", "none", None)


def _normalizar_versao(
    marca_norm: str,
    modelo_norm: str,
    ano: Optional[int],
    versao: Optional[str],
) -> Optional[str]:
    """
    Tenta casar a versão do anúncio com as versões canônicas do catálogo
    para aquele (marca, modelo, ano). Retorna a versão canônica se encontrada,
    ou None se não houver dados suficientes para normalizar.
    """
    if not versao or not ano:
        return None
    candidatos = _versoes.get((marca_norm, modelo_norm, ano), [])
    if not candidatos:
        return None
    versao_norm = normalizar_texto(versao)
    if not versao_norm:
        return None
    if versao_norm in candidatos:
        return versao_norm
    return _melhor_fuzzy(versao_norm, candidatos, threshold=0.75)


def _melhor_fuzzy(alvo: str, candidatos: list[str], threshold: float) -> Optional[str]:
    """Retorna o melhor candidato fuzzy acima do threshold, ou None."""
    if not alvo or not candidatos:
        return None
    matches = difflib.get_close_matches(alvo, candidatos, n=1, cutoff=threshold)
    return matches[0] if matches else None


def _com_match(
    anuncio: Anuncio,
    confidence: str,
    strategy: str,
    versao_canonical: Optional[str],
) -> Anuncio:
    """Cria cópia do anúncio com os campos de matching (e versão canônica) atualizados."""
    from dataclasses import replace
    updates: dict = {"match_confidence": confidence, "match_strategy": strategy}
    if versao_canonical is not None:
        updates["versao"] = versao_canonical
    return replace(anuncio, **updates)
