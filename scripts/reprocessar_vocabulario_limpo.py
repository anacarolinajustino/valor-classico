"""
Reprocessamento do LIXO QUE O VOCABULÁRIO DE TRIM AVALIZAVA (2026-08-07).

O vocabulário de trim é derivado da coluna `nome_versao` do catálogo da
Webmotors, tokenizada e filtrada por listas de spec. Três formas de lixo
escapavam dessas listas porque só se reconhecem pelo token VIZINHO:

    "2.8 6 CILINDROS"      -> indexava `6`  como trim (59 pares)
    "1.3 I SEDAN"          -> indexava `I`  como trim (34 pares)
    "TETO DE LONA"         -> indexava `DE` como trim (12 pares)

E aí `_trims_na_cauda`, que pesca na cauda do título exatamente o que o
catálogo avaliza, pescava isso: a Mercedes 280 SE ficou com versão "6", o Gol
com "I", o Escort com "I XR3". `_e_trim_de_verdade` (src/catalog/loader.py)
passou a barrar os três na origem.

Este script conserta o que já foi gravado. O ESCOPO é a diferença entre o
vocabulário antigo e o novo, calculada aqui mesmo: só entram os anúncios cuja
versão contém um token que o vocabulário DEIXOU de avalizar naquele par.

Por que não reprocessar toda versão a partir do título: em boa parte da base a
versão NÃO vem do título — vem do campo estruturado da ficha técnica do ML e
da Webmotors, que é melhor que o título. Re-derivar tudo trocaria dado bom por
dado pior. A diferença de vocabulário é o recorte exato do estrago.

Trava herdada de `reprocessar_trim_da_cauda.py`: só aplica quando marca/modelo
re-inferidos do título BATEM com os gravados. Par divergente é outra auditoria.

Uso:
    python scripts/reprocessar_vocabulario_limpo.py            # dry-run
    python scripts/reprocessar_vocabulario_limpo.py --apply    # backup + aplica
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.catalog.loader import (
    CSV_PADRAO,
    _SPEC_VERSAO_PALAVRA,
    _SPEC_VERSAO_RE,
    _indice_trim,
    carregar_catalogo,
)
from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import (
    _VERSAO_SINONIMO_FRASE,
    decompor_versao,
    inferir_marca_modelo_versao_obs_ano,
    normalizar_texto,
)
from src.pipeline.persistence import _connect


def _vocabulario_antigo() -> dict[tuple[str, str], set[str]]:
    """
    O índice como era antes de `_e_trim_de_verdade` — mesma leitura do CSV,
    só com os dois filtros antigos. Reconstruído aqui em vez de guardado em
    lugar nenhum: o alvo do script é a DIFERENÇA entre os dois, e derivá-la
    do próprio código evita uma lista de tokens escrita à mão que envelhece
    junto com o catálogo.
    """
    idx: dict[tuple[str, str], set[str]] = {}
    with open(CSV_PADRAO, encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            marca_raw = linha.get("nome_marca", "").strip()
            modelo_raw = linha.get("nome_modelo", "").strip()
            versao_raw = linha.get("nome_versao", "").strip()
            if not marca_raw or not modelo_raw or not versao_raw:
                continue
            versao_norm = normalizar_texto(versao_raw)
            for padrao, canonico in _VERSAO_SINONIMO_FRASE:
                versao_norm = padrao.sub(canonico, versao_norm)
            for t in versao_norm.split():
                if t in _SPEC_VERSAO_PALAVRA or _SPEC_VERSAO_RE.match(t):
                    continue
                idx.setdefault(
                    (normalizar_texto(marca_raw), normalizar_texto(modelo_raw)), set()
                ).add(t)
    return idx


def main() -> None:
    aplicar = "--apply" in sys.argv

    carregar_catalogo()
    novo = _indice_trim()
    antigo = _vocabulario_antigo()

    removidos: dict[tuple[str, str], set[str]] = {}
    for par, tokens in antigo.items():
        fora = tokens - novo.get(par, set())
        if fora:
            removidos[par] = fora

    total_tokens: Counter = Counter()
    for fora in removidos.values():
        total_tokens.update(fora)
    print(f"Pares com token removido do vocabulário: {len(removidos)}")
    print("Tokens que saíram (por nº de pares):")
    for tok, n in total_tokens.most_common(20):
        print(f"   {tok!r:<10} em {n:4d} pares")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, marca, modelo, versao, obs, geracao, motor, titulo "
                "FROM anuncios WHERE versao IS NOT NULL AND versao <> '' ORDER BY id"
            )
            rows = cur.fetchall()

        alvo = []
        for r in rows:
            mk = normalizar_texto(r["marca"] or "")
            md = normalizar_texto(r["modelo"] or "")
            fora = removidos.get((mk, md))
            if fora and (fora & set(r["versao"].split())):
                alvo.append(r)

        print(f"\nAnúncios com versão contaminada: {len(alvo)}")

        mudancas: list[tuple[int, tuple, tuple]] = []
        pulados_par: Counter = Counter()
        teimosos: Counter = Counter()

        for r in alvo:
            mk = normalizar_texto(r["marca"] or "")
            md = normalizar_texto(r["modelo"] or "")
            mk_novo, md_novo, versao_nova, obs_nova, _ano = (
                inferir_marca_modelo_versao_obs_ano(r["titulo"] or "")
            )
            if (mk_novo, md_novo) != (mk, md):
                pulados_par[(mk, md, mk_novo, md_novo)] += 1
                continue

            n = decompor_versao(
                mk, md, versao_nova, obs_nova or r["obs"],
                r["titulo"], r["geracao"], r["motor"],
            )
            v = (r["versao"], r["geracao"], r["motor"], r["obs"])
            if n == v:
                # O pipeline de hoje produz exatamente o que já está gravado.
                # Duas naturezas bem diferentes caem aqui, e vale distinguir:
                #
                #   "CUSTOM DE LUXE" — CERTO. O DE saiu do vocabulário, mas
                #   `_trims_na_cauda` o preserva entre dois trims aceitos; é a
                #   ponte de conectivo funcionando, não um caso pendente.
                #
                #   "WOLFSBURG EDITION I" (de "2000i"), "SO 6" (de "SÓ 65.000
                #   KM") — ERRADO, mas o token está no MIOLO do título, antes
                #   do corte de spec, onde o vocabulário nunca mandou. Outro
                #   bug, fora do alcance deste script; vai pra fila "Versões a
                #   conferir" do painel, que é onde a curadoria manual decide.
                teimosos[(mk, md, r["versao"])] += 1
                continue
            mudancas.append((r["id"], v, n))

        print(f"Linhas que mudam: {len(mudancas)}")
        perdem = sum(1 for _i, v, n in mudancas if v[0] and not n[0])
        print(f"   ficam SEM versão (a versão era só o lixo): {perdem}")
        print(f"   pulados por par divergente: {sum(pulados_par.values())}")
        print(f"   inalterados (pipeline de hoje dá o mesmo valor): {sum(teimosos.values())}")

        if teimosos:
            print("\n--- inalterados: 'CUSTOM DE LUXE' é a ponte de conectivo "
                  "funcionando; o resto é token do miolo do título ---")
            for (mk, md, vs), n in teimosos.most_common(12):
                print(f"   {n:4d}x  {mk} {md} versao={vs!r}")

        if pulados_par:
            print("\n--- pulados por par divergente ---")
            for (mkb, mdb, mkn, mdn), n in pulados_par.most_common(8):
                print(f"   {n:4d}x  banco={mkb} {mdb!r} -> título dá {mkn} {mdn!r}")

        print("\n--- amostra de 30 mudanças ---")
        for id_, v, n in mudancas[:30]:
            print(f"   #{id_}: versao {v[0]!r} -> {n[0]!r}"
                  + (f" | obs {v[3]!r} -> {n[3]!r}" if v[3] != n[3] else ""))

        if not aplicar:
            print("\nDry-run — nada foi alterado. Rode com --apply pra gravar.")
            return

        print("\nGerando backup antes de aplicar...")
        caminho = fazer_backup()
        if caminho is None:
            print("ERRO: backup falhou — nada foi alterado.")
            sys.exit(1)
        print(f"Backup criado: {caminho}")

        print(f"\nAplicando {len(mudancas)} atualizações...")
        with conn.cursor() as cur:
            for id_, _v, n in mudancas:
                cur.execute(
                    "UPDATE anuncios SET versao = %s, geracao = %s, motor = %s, obs = %s "
                    "WHERE id = %s",
                    (n[0], n[1], n[2], n[3], id_),
                )
        print("Concluído (commit ao sair do bloco de conexão).")


if __name__ == "__main__":
    main()
