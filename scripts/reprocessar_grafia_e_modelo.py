"""
Reprocessamento retroativo de grafia + modelo-lixo (auditoria 2026-07-21, 2ª
passada — a usuária apontou que a 1ª passada deixou modelos errados: '0',
'VW-FUSCA-1300', várias grafias de Willys).

Duas fases por anúncio:

  Fase A (todos): re-sanea o CAMPO modelo com separar_modelo_versao_obs, que
    agora canoniza a grafia contra o catálogo ('D-20'→'D20', 'C-180'→'C 180')
    e descola modelo grudado ('Fusca1300'→'Fusca'). Idempotente pra quem já
    está certo. NÃO altera a marca.

  Fase B (só modelo-lixo depois da fase A): quando o modelo continua lixo
    (vazio, '0', um ano solto, ou um typo de Willys), o nome real costuma
    estar no TÍTULO, não no campo — então re-infere do título com
    inferir_marca_modelo_versao_obs_ano. Aceita o resultado só quando ele dá
    um modelo melhor (não-lixo). Pode corrigir a marca junto (ex.: campo
    'GM'→título 'Chevrolet Opala').

OVERRIDES: correções manuais por id pros casos que nenhuma das fases resolve
sozinha (revenda citando vários carros, marca trocada pelo vendedor). Curados
lendo o título original de cada um.

Uso:
    python scripts/reprocessar_grafia_e_modelo.py            # dry-run
    python scripts/reprocessar_grafia_e_modelo.py --apply    # backup + aplica
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.catalog.loader import carregar_catalogo
from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import (
    separar_modelo_versao_obs,
    inferir_marca_modelo_versao_obs_ano,
    normalizar_texto,
    _GRAFIAS_WILLYS,
)
from src.pipeline.persistence import _connect

_CATALOGO = carregar_catalogo()

# --- Overrides manuais por id (marca, modelo, versao|None, obs|None) --------
# Curados lendo o título original. Vencem as duas fases automáticas.
_VAZIO = ("", "")  # sentinela interna: mantém marca, zera modelo


def _ov(marca, modelo, versao=None, obs=None):
    return (marca, modelo, versao, obs)


OVERRIDES: dict[int, tuple[str, str, str | None, str | None]] = {
    # modelo='0' com o modelo real no título ("Chevrolet 0 1994 Custom/ C-20")
    37770: _ov("CHEVROLET", "C20", None, None),
    38044: _ov("CHEVROLET", "C20", None, None),
    # "Nissan 0 1993 Se 4x4 3.0 V6" = Pathfinder (SUV Nissan 3.0 V6 4x4 da época)
    38161: _ov("NISSAN", "PATHFINDER", None, "4X4"),
    # marca trocada pelo vendedor: título diz outro carro
    34748: _ov("RENAULT", "DAUPHINE", None, None),   # "Dauphine 1961..."
    36530: _ov("RENAULT", "DAUPHINE", None, None),
    35141: _ov("SIMCA", "CHAMBORD", None, None),     # "Simca Cord 1964 Chambord"
    36540: _ov("CHEVROLET", "OMEGA", None, None),    # "Omega 3.0 1994"
    35967: _ov("RENAULT", "GORDINI", None, None),    # "Renault Gordini 1966" (salvo FORD)
    35969: _ov("RENAULT", "GORDINI", None, None),
    35878: _ov("CHEVROLET", "MONZA", None, None),    # "Chevrolet Monza" (salvo modelo GLS)
    36518: _ov("CADILLAC", "FLEETWOOD", None, None), # "Limousine Fleetwood" (salvo modelo GM)
    36102: _ov("TOYOTA", "BANDEIRANTE", None, None), # "Toyota Bandeirante Carroceria"
    # sem modelo real recuperável no título -> zera modelo (honesto)
    36453: _ov("CHEVROLET", "", None, None),         # "Gm Chevrolet 51"
    34835: _ov("CHEVROLET", "", None, None),         # "Chevrolet Tigre" (apelido, não modelo)
    # "Motor Chevette" é o motor do hot rod, não o carro (Fordinho 29)
    34758: _ov("FORD", "", None, None),
    # "Mobylette Caloi" — a inferência inverte marca/modelo; é Caloi Mobylette
    1734: _ov("CALOI", "MOBYLETTE", None, None),
    # "VW-FUSCA-1300" — marca(alias)+modelo+cilindrada grudados por hífen; os
    # hífens impedem a separação normal (não dá pra splitar hífen global sem
    # quebrar AERO-WILLYS/KARMANN-GHIA). Título é só "Placa Preta".
    36353: _ov("VOLKSWAGEN", "FUSCA", None, None),
    # marca errada com o modelo real explícito no título
    36251: _ov("ALFA ROMEO", "2300", None, None),        # "Alfa Romeo 2300 1976"
    14162: _ov("LINCOLN", "CONTINENTAL", "MARK V", None),  # "Ford Lincoln Continental Mark V"
    36695: _ov("SIMCA", "CHAMBORD", None, None),          # "Simca Cord 1964 Chambord"
    419: _ov("VOLKSWAGEN", "1600", None, None),           # "VOLKSWAGEN VW 1600" (VW é eco)
    # "Pick-up Willys 4x4 1963" — o "44" é o "4x4" mal parseado; sem modelo
    # de linha específico recuperável -> zera (melhor vazio que lixo).
    1471: _ov("WILLYS", "", None, None),
}


def _reinferir(marca_v, modelo_v, ano, titulo):
    """
    Fase B: re-infere marca/modelo do título pra recuperar um modelo-lixo.
    Guarda contra falso positivo (título de hot rod/revenda citando vários
    carros, motor de outra marca): só aceita o resultado se o par (marca,
    modelo) inferido EXISTE no catálogo. Se não recupera nada confiável,
    ZERA o modelo (vazio honesto é melhor que '0'/ano/typo).
    """
    mk2, md2, vs2, ob2, _an2 = inferir_marca_modelo_versao_obs_ano(titulo or "")
    if md2 and not _e_lixo(md2, ano) and (mk2, normalizar_texto(md2)) in _CATALOGO:
        return (mk2, md2, vs2, ob2, "faseB")
    # "Jeep Wilys/Wyllis..." (marca JEEP + typo de Willys) sem outro modelo no
    # título é o Willys Jeep — não zerar (título bagunçado às vezes engole o
    # modelo na inferência).
    if marca_v == "JEEP" and normalizar_texto(modelo_v) in _GRAFIAS_WILLYS:
        return ("WILLYS", "JEEP", None, None, "willys")
    return (marca_v, "", None, None, "zerado")


def _e_lixo(modelo: str, ano) -> bool:
    m = (modelo or "").strip()
    if not m or m == "0":
        return True
    if re.fullmatch(r"\d{1,4}", m):
        val = int(m)
        if ano and (val == ano or (val < 100 and 1900 + val == ano)):
            return True
    if normalizar_texto(m) in _GRAFIAS_WILLYS and normalizar_texto(m) != "WILLYS":
        return True
    return False


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, marca, modelo, versao, obs, ano, titulo FROM anuncios ORDER BY id")
            rows = cur.fetchall()

        print(f"Total de anúncios: {len(rows)}")

        mudancas = []  # (id, marca_v, modelo_v, marca_n, modelo_n, versao_n, obs_n, origem)
        for r in rows:
            id_ = r["id"]
            marca_v = r["marca"] or ""
            modelo_v = r["modelo"] or ""
            ano = r["ano"]

            # OVERRIDE tem prioridade
            if id_ in OVERRIDES:
                mk, md, vs, ob = OVERRIDES[id_]
                origem = "override"
            elif not (modelo_v or "").strip():
                # Modelo já vazio: não reconstruir da versão (viraria lixo);
                # tenta o título, mas só aceita par que exista no catálogo.
                mk, md, vs, ob, origem = _reinferir(marca_v, modelo_v, ano, r["titulo"])
            else:
                # Fase A (cirúrgica): atualiza SÓ o nome do modelo — canoniza
                # grafia ('D-20'→'D20') e descola grudado ('Fusca1300'→'Fusca')
                # — preservando versao/obs originais (a rodada passada já os
                # separou; recalcular arriscaria reverter/sujar).
                md = separar_modelo_versao_obs(marca_v, modelo_v)[0]
                mk, vs, ob = marca_v, r["versao"], r["obs"]
                origem = "faseA"
                # Fase B: se o modelo ficou lixo, re-infere do título (com guarda)
                if _e_lixo(md, ano):
                    mk, md, vs, ob, origem = _reinferir(marca_v, modelo_v, ano, r["titulo"])

            # Escopo desta rodada é MODELO (e marca): só registra quando um
            # dos dois muda — não mexe em versao/obs de quem só teria a versão
            # recalculada (fora de escopo, arriscaria reverter separações boas).
            if (mk, md) != (marca_v, modelo_v):
                mudancas.append((id_, marca_v, modelo_v, mk, md, vs, ob, origem))

        por_origem = {}
        for m in mudancas:
            por_origem[m[7]] = por_origem.get(m[7], 0) + 1
        print(f"Linhas alteradas: {len(mudancas)}  (por origem: {por_origem})")

        # Mudanças de MARCA (mais sensíveis) — listar todas
        muda_marca = [m for m in mudancas if m[1] != m[3]]
        print(f"\n--- {len(muda_marca)} mudanças de MARCA (revisar) ---")
        for id_, mkv, mdv, mkn, mdn, vs, ob, org in muda_marca:
            print(f"  #{id_} [{org}] {mkv!r}/{mdv!r} -> {mkn!r}/{mdn!r}")

        # Modelos que ficaram VAZIOS (sem modelo recuperável) — revisar
        vazios = [m for m in mudancas if not m[4]]
        print(f"\n--- {len(vazios)} anúncios que ficaram SEM modelo (revisar) ---")
        for id_, mkv, mdv, mkn, mdn, vs, ob, org in vazios[:40]:
            print(f"  #{id_} [{org}] {mkv!r}/{mdv!r} -> {mkn!r}/'' ")

        print("\n--- Amostra de 30 mudanças de modelo (marca igual) ---")
        so_modelo = [m for m in mudancas if m[1] == m[3]]
        for id_, mkv, mdv, mkn, mdn, vs, ob, org in so_modelo[:30]:
            print(f"  #{id_} [{org}] {mdv!r} -> modelo={mdn!r} versao={vs!r} obs={ob!r}")

        if not aplicar:
            print("\nDry-run — nada foi alterado. Rode com --apply pra gravar.")
            return

        print("\nGerando backup antes de aplicar...")
        caminho = fazer_backup()
        if caminho is None:
            print("ERRO: backup falhou — abortando.")
            sys.exit(1)
        print(f"Backup criado: {caminho}")

        print(f"\nAplicando {len(mudancas)} atualizações...")
        with conn.cursor() as cur:
            for id_, _mkv, _mdv, mkn, mdn, vs, ob, _org in mudancas:
                cur.execute(
                    "UPDATE anuncios SET marca = %s, modelo = %s, versao = %s, obs = %s WHERE id = %s",
                    (mkn, mdn, vs, ob, id_),
                )
        print("Concluído (commit ao sair do bloco).")


if __name__ == "__main__":
    main()
