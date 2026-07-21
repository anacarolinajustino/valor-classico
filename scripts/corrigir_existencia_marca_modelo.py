"""
Correção retroativa dos pares marca/modelo SEM referência no catálogo
(auditoria de existência, 2026-07-21).

Cobre os ~40 grupos com 3+ anúncios da lista de 416 pares "sem match" contra
data/base_marcamodelo.csv (ver scripts/auditar_existencia_marca_modelo.py).
Cada grupo foi decidido lendo os títulos originais dos anúncios (ground
truth) e cruzando com o catálogo + conhecimento histórico automotivo (alguns
casos raros confirmados por pesquisa: Simca Tufão, CBT Javali, Mercury Eight).

Os pares que SÃO carros reais mas simplesmente ausentes do catálogo (ex.:
Fiat Prêmio, Chevrolet Corvair, CBT Javali) não são alterados aqui — entram
no suplemento manual em src/catalog/loader.py (feito à parte).

Os ~250+ pares com apenas 1 anúncio (muitos com título "sujo" de revenda,
citando vários carros) ficam para uma rodada seguinte.

Uso:
    python scripts/corrigir_existencia_marca_modelo.py            # dry-run
    python scripts/corrigir_existencia_marca_modelo.py --apply    # backup + aplica
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.persistence import _connect

# --------------------------------------------------------------------------
# A) Correções em bloco: todo anúncio com (marca, modelo) velho vira o novo,
#    sem precisar olhar o título linha a linha (o grupo inteiro tem a mesma
#    causa/solução).
# --------------------------------------------------------------------------
BULK_FIXES: dict[tuple[str, str], tuple[str, str]] = {
    # "Willys Overland" virou marca=WILLYS + modelo=OVERLAND (2ª metade do
    # nome da marca vazou pro modelo). Título quase sempre diz
    # "Willys Overland Jeep ..." — o carro real é o Jeep Willys.
    ("WILLYS", "OVERLAND"): ("WILLYS", "JEEP"),
    # Buggy genérico (marca desconhecida, decisão deliberada 2026-07-15) com
    # "1.6" (cilindrada) vazada pro modelo em vez do nome do carro.
    ("BUGGY", "1.6"): ("BUGGY", "BUGGY"),
    # "Bugre Bugre" redundante -> mesmo padrão dos outros fabricantes de
    # buggy (marca conhecida, modelo genérico "Buggy").
    ("BUGRE", "BUGRE"): ("BUGRE", "BUGGY"),
    # Apelido "Boca de Sapo" (grade arredondada) não é nome de modelo —
    # título sempre cita a picape 3100, que o catálogo já tem.
    ("CHEVROLET", "BOCA"): ("CHEVROLET", "3100"),
    # GMC Sonoma é badge exclusivo da GMC (não existe Chevrolet Sonoma no
    # catálogo) — catálogo confirma "SONOMA" só embaixo de GMC.
    ("CHEVROLET", "SONOMA"): ("GMC", "SONOMA"),
    # "Chevrolet D 10/D 100" -> D10 (grafia do catálogo).
    ("CHEVROLET", "D"): ("CHEVROLET", "D10"),
    # "Aero Willys" -> grafia do catálogo com hífen.
    ("WILLYS", "AERO"): ("WILLYS", "AERO-WILLYS"),
    # "Austin Imp A40" -> A40 é o modelo real (catálogo/suplemento já tem).
    ("AUSTIN", "IMP"): ("AUSTIN", "A40"),
    # Ford 1929/29 sem outro dado = Ford Model A (catálogo tem "A").
    ("FORD", "1929"): ("FORD", "A"),
    ("FORD", "29"): ("FORD", "A"),
    # CBT Jipe -> nome comercial real é "Javali" (confirmado: fabricante
    # Companhia Brasileira de Tratores, 1988-1995).
    ("CBT", "JIPE"): ("CBT", "JAVALI"),
    # "Asia Motors Jipe Rocsta" -> Rocsta é o modelo (catálogo confirma).
    ("ASIA MOTORS", "JIPE"): ("ASIA MOTORS", "ROCSTA"),
    # Lexus ES-300/ES300 3 -> grafia única sem hífen nem número de motor solto.
    ("LEXUS", "ES-300"): ("LEXUS", "ES300"),
    # "2 portas" (contagem de portas) vazou pro modelo — sem outro dado no
    # título pra saber qual carro é.
    ("FORD", "2"): ("FORD", ""),
    # MP Lafer só tem uma linha de carro — todas essas variações (blank,
    # cilindrada, "conversível"/"cupê" como carroceria, ano de 2 dígitos)
    # são o mesmo carro que já aparece corretamente como CLASSICO em 13
    # anúncios (grafia do catálogo).
    ("MP LAFER", "1.6"): ("MP LAFER", "CLASSICO"),
    ("MP LAFER", "1600"): ("MP LAFER", "CLASSICO"),
    ("MP LAFER", "75"): ("MP LAFER", "CLASSICO"),
    ("MP LAFER", "78"): ("MP LAFER", "CLASSICO"),
    ("MP LAFER", "CABRIOLET"): ("MP LAFER", "CLASSICO"),
    ("MP LAFER", "CONVERSIVEL"): ("MP LAFER", "CLASSICO"),
    ("MP LAFER", "COUPE"): ("MP LAFER", "CLASSICO"),
    ("MP LAFER", "MINIATURA"): ("MP LAFER", "CLASSICO"),
}

# Mesma lista, mas pra pares com modelo NULL (não dá pra usar como chave de
# dict com '' — tratado à parte no fetch).
BULK_FIXES_MODELO_NULO: dict[str, tuple[str, str]] = {
    "MP LAFER": ("MP LAFER", "CLASSICO"),
}

# --------------------------------------------------------------------------
# B) Correções por linha: dentro do mesmo par (marca, modelo) errado, cada
#    anúncio pede um destino diferente — decidido lendo o título (e às vezes
#    o ano) de cada um.
# --------------------------------------------------------------------------
ROW_FIXES: dict[int, tuple[str, str]] = {
    # --- CHEVROLET/GM: "Chevrolet - GM <modelo real>" ou "GM/Chevrolet <modelo>" ---
    1511: ("CHEVROLET", "C14"),
    2618: ("CHEVROLET", "VECTRA"),
    2619: ("CHEVROLET", "BLAZER"),
    2624: ("CHEVROLET", "BLAZER"),
    2628: ("CHEVROLET", "CARAVAN"),
    2629: ("CHEVROLET", "OPALA"),
    2637: ("CHEVROLET", "VECTRA"),
    2639: ("CHEVROLET", "VECTRA"),
    2641: ("CHEVROLET", "OPALA"),
    2643: ("CHEVROLET", "C14"),
    34754: ("CHEVROLET", "BEL AIR"),
    36540: ("CHEVROLET", "OMEGA"),

    # --- DKW/VEMAG: "Vemag" é a fabricante (joint-venture), modelo real é
    # Vemaguet ou Belcar (ambos já no suplemento de loader.py) ---
    4474: ("DKW", "BELCAR"),
    13307: ("DKW", "VEMAGUET"),
    13373: ("DKW", "VEMAGUET"),
    13397: ("DKW", "VEMAGUET"),
    13421: ("DKW", "VEMAGUET"),
    13504: ("DKW", "VEMAGUET"),
    13513: ("DKW", "BELCAR"),
    13607: ("DKW", "VEMAGUET"),
    13748: ("DKW", "BELCAR"),
    35972: ("DKW", "BELCAR"),

    # --- MERCEDES-BENZ: "Bens"/"Mercedes"/"Benz" repete a marca; modelo
    # real está logo depois no título ---
    34911: ("MERCEDES-BENZ", "C 280"),
    34980: ("MERCEDES-BENZ", "S 500"),
    34991: ("MERCEDES-BENZ", "C 180"),
    1489: ("MERCEDES-BENZ", "E 430"),
    4752: ("MERCEDES-BENZ", "SL 500"),
    4755: ("MERCEDES-BENZ", "C 280"),
    31: ("MERCEDES-BENZ", "230 S"),
    1401: ("MERCEDES-BENZ", "E 320"),

    # --- CHEVROLET/GMC: só o caso claro (GMC Jimmy = irmão do Blazer);
    # os outros 2 (título ambíguo citando 2 carros) ficam pra próxima rodada ---
    25283: ("CHEVROLET", "BLAZER"),

    # --- CHEVROLET/OUTROS ---
    36654: ("CHEVROLET", ""),  # "6 cilindros" só, sem modelo identificável
    36684: ("CHEVROLET", "BEL AIR"),  # "Bel Air Nomad"
    37491: ("CHEVROLET", "COMODORO"),  # "Opala Sedan Comodoro" — Comodoro é o nome comercial
    39054: ("CHEVROLET", "S10"),  # "Ss10" = trim SS do S10

    # --- FORD/OUTROS ---
    36665: ("FORD", "A"),  # "1929 29" = Ford Model A
    37144: ("FORD", "JEEP"),  # 1972 (pós-aquisição da Willys pela Ford em 1967) — catálogo tem FORD+JEEP

    # --- DODGE/OUTROS ---
    37088: ("DODGE", "MONACO"),
    37122: ("DODGE", "CHALLENGER"),

    # --- HONDA/CB: cilindrada faz parte do nome comercial da linha CB ---
    851: ("HONDA", "CB 500"),
    854: ("HONDA", "CB 500"),
    2265: ("HONDA", "CB 450"),
    6169: ("HONDA", "CB 360"),
    # id 38 "CB 700km" — sigla ambígua (pode ser km rodado colado), sem
    # modelo confiável -> deixa em branco
    38: ("HONDA", ""),

    # --- CHRYSLER/SIMCA: marca real é Simca (Chrysler só controlava a
    # fábrica), modelo é o que vem depois ---
    13689: ("SIMCA", "TUFAO"),
    32889: ("SIMCA", "TUFAO"),
    35141: ("SIMCA", "CHAMBORD"),

    # --- FORD/MERCURY: Mercury é marca irmã da Ford, não modelo ---
    35218: ("MERCURY", "MARQUIS"),
    36151: ("MERCURY", "EIGHT"),
    36425: ("MERCURY", "EIGHT"),  # "Mercury Cup" = Coupe (Mercury Eight Coupe 1949)

    # --- CHEVROLET/SEDAN ---
    34972: ("CHEVROLET", "BEL AIR"),
    36021: ("CHEVROLET", ""),  # 1936, sem linha identificável
    36376: ("CHEVROLET", ""),  # 1933, sem linha identificável

    # --- FORD/FURGAO ---
    6207: ("FORD", "F-1"),  # 1951, geração F-1 (1948-52)
    34807: ("FORD", "F-100"),  # título cita F100 explicitamente
    35684: ("FORD", "F-1"),  # 1951/51

    # --- FORD/HOT: "Hot Rod" é customização, não modelo de fábrica ---
    4532: ("FORD", ""),
    35054: ("FORD", "T"),  # "T. Buket" = T-bucket, baseado no Ford Model T
    35161: ("FORD", "TUDOR"),  # carroceria Tudor citada explicitamente
    35418: ("FORD", ""),

    # --- FORD/SEDAN ---
    32818: ("FORD", "DELUXE"),
    34875: ("FORD", "DELUXE"),
    7523: ("FORD", ""),  # 1939, sem trim identificável
    35526: ("FORD", ""),

    # --- VOLKSWAGEN/PUMA: Puma é marca própria (carroceria esportiva
    # brasileira sobre mecânica VW), não modelo da Volkswagen ---
    421: ("PUMA", "GT"),
    429: ("PUMA", "GT"),
    35150: ("PUMA", "GTC"),
    35610: ("PUMA", "GTC"),
    35968: ("PUMA", "GT"),
    35971: ("PUMA", "GTE"),
    36000: ("PUMA", "GTE"),
    36316: ("PUMA", "GTE"),
    36321: ("PUMA", "GT"),
    36475: ("PUMA", "GT"),

    # --- JEEP/WILLYS: separa CJ5/CJ6 (linha Jeep) de Willys Overland genérico ---
    1442: ("JEEP", "CJ 5"),
    6602: ("JEEP", "CJ 5"),
    35194: ("JEEP", "CJ 6"),
    2244: ("WILLYS", "JEEP"),
    13315: ("WILLYS", "JEEP"),
    32795: ("WILLYS", "JEEP"),
    35238: ("WILLYS", "JEEP"),
    36311: ("WILLYS", "JEEP"),
    36592: ("WILLYS", "JEEP"),  # "Willys Ford Barn Find" — pouca informação, default

    # "Chevy" é apelido informal de Chevrolet — só este anúncio nomeia o
    # modelo real explicitamente ("BelAir"); os outros 2 (Coupe 1934 título
    # de revenda citando 4 carros, "Brasil 6500" sem linha clara) ficam
    # pra próxima rodada.
    6603: ("CHEVROLET", "BEL AIR"),
}

# --------------------------------------------------------------------------
# C) FORD/WILLYS: 83 anúncios, dois carros reais diferentes no mesmo par
#    errado. "Aero Willys" só existe no catálogo como WILLYS (não FORD).
#    "Rural" existe nas duas marcas do catálogo — usa o ano pra decidir:
#    Ford comprou a Willys-Overland do Brasil em jan/1967.
# --------------------------------------------------------------------------
def gerar_fixes_ford_willys(cur) -> dict[int, tuple[str, str]]:
    cur.execute(
        "SELECT id, ano, titulo FROM anuncios WHERE marca = 'FORD' AND modelo = 'WILLYS'"
    )
    fixes: dict[int, tuple[str, str]] = {}
    for r in cur.fetchall():
        titulo_up = (r["titulo"] or "").upper()
        ano = r["ano"] or 0
        if "AERO" in titulo_up:
            fixes[r["id"]] = ("WILLYS", "AERO-WILLYS")
        elif "RURAL" in titulo_up:
            if ano >= 1967:
                fixes[r["id"]] = ("FORD", "RURAL")
            else:
                fixes[r["id"]] = ("WILLYS", "RURAL")
        else:
            # único caso residual: "Ford Coupe Willys V8 Hot Rood Spyder
            # Tudor Mustang Maverick" — título de revenda citando vários
            # carros, sem modelo confiável.
            fixes[r["id"]] = ("FORD", "")
    return fixes


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            row_fixes = dict(ROW_FIXES)
            row_fixes.update(gerar_fixes_ford_willys(cur))

            # Busca estado atual de todas as linhas envolvidas (bulk + row)
            cur.execute("SELECT id, marca, modelo FROM anuncios ORDER BY id")
            todas = {r["id"]: (r["marca"], r["modelo"]) for r in cur.fetchall()}

        mudancas: list[tuple[int, str, str, str, str]] = []

        for id_, (marca_velha, modelo_velho) in todas.items():
            novo = None
            if id_ in row_fixes:
                novo = row_fixes[id_]
            elif modelo_velho is None and marca_velha in BULK_FIXES_MODELO_NULO:
                novo = BULK_FIXES_MODELO_NULO[marca_velha]
            elif (marca_velha, modelo_velho or "") in BULK_FIXES:
                novo = BULK_FIXES[(marca_velha, modelo_velho or "")]

            if novo is None:
                continue
            marca_nova, modelo_novo = novo
            if marca_nova != marca_velha or modelo_novo != (modelo_velho or ""):
                mudancas.append((id_, marca_velha, marca_nova, modelo_velho or "", modelo_novo))

        print(f"Total de anúncios no banco: {len(todas)}")
        print(f"Linhas que serão corrigidas: {len(mudancas)}")

        resumo: dict[tuple[str, str, str, str], int] = {}
        for _id, mv, mn, modv, modn in mudancas:
            resumo[(mv, modv, mn, modn)] = resumo.get((mv, modv, mn, modn), 0) + 1

        print("\n--- Resumo (marca/modelo antigo -> novo) ---")
        for (mv, modv, mn, modn), n in sorted(resumo.items(), key=lambda x: -x[1]):
            print(f"  {n:4d}  {mv!r:15}/{modv!r:15} -> {mn!r:15}/{modn!r}")

        if not aplicar:
            print("\nDry-run — nada foi alterado. Rode com --apply pra gravar as mudanças.")
            return

        print("\nGerando backup antes de aplicar...")
        caminho = fazer_backup()
        if caminho is None:
            print("ERRO: backup falhou — abortando pra não gravar sem rede de segurança.")
            sys.exit(1)
        print(f"Backup criado: {caminho}")

        print(f"\nAplicando {len(mudancas)} atualizações...")
        with conn.cursor() as cur:
            for id_, _mv, marca_nova, _modv, modelo_novo in mudancas:
                cur.execute(
                    "UPDATE anuncios SET marca = %s, modelo = %s WHERE id = %s",
                    (marca_nova, modelo_novo, id_),
                )
        print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
