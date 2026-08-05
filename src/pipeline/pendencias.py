"""
Pendências de verificação — a fila única de decisões manuais do painel.

Junta num lugar só o que antes estava espalhado: a quarentena de pares
marca/modelo fora do catálogo (que morava numa seção escondida da página de
anúncios) e as decisões sobre as informações de modelo vindas das fontes
externas (ver src/catalog/externo.py e docs/fontes_externas.md).

A ideia central é que a evidência externa CLASSIFICA a pendência. Antes, a
quarentena era uma lista chapada de pares órfãos e a usuária tinha que
pesquisar cada um pra saber se era carro de verdade, nome truncado ou lixo de
parsing. Agora cada linha já chega com o que as fontes sabem, e daí sai uma
ação sugerida:

    corrigir_nome  — a fonte tem o nome MAIS LONGO ('RANGE' -> 'RANGE ROVER'):
                     o banco truncou numa extração ruim. Corrigir no banco, e
                     NÃO cadastrar o nome truncado no catálogo.
    confirmado     — a fonte confirma o par, muitas vezes com faixa de ano.
                     É carro de verdade que só falta cadastrar.
    sem_evidencia  — nenhuma fonte conhece. Para carro NACIONAL isso é o
                     esperado (as fontes são europeias/americanas), então não
                     quer dizer que está errado — quer dizer que só a usuária
                     pode decidir.

Nada aqui altera o catálogo canônico sozinho. As ações continuam sendo as que
já existiam (`corrigir_marca_modelo`, `adicionar_ao_catalogo`,
`excluir_marca_modelo`), mais o "dispensar", que é novo.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.catalog.externo import evidencia_externa

_DATA = Path(__file__).parent.parent.parent / "data"

# Pares que a usuária olhou e decidiu deixar como estão. Sem isso, um par que
# ela já analisou e considerou correto reapareceria na fila para sempre.
DISPENSADAS_CSV = _DATA / "pendencias_dispensadas.csv"

TIPO_CORRIGIR = "corrigir_nome"
TIPO_CONFIRMADO = "confirmado"
TIPO_SEM_EVIDENCIA = "sem_evidencia"

# Ordem de exibição: primeiro o que tem ação clara e barata, por último o que
# exige pesquisa da usuária.
_ORDEM_TIPO = {TIPO_CORRIGIR: 0, TIPO_CONFIRMADO: 1, TIPO_SEM_EVIDENCIA: 2}


def carregar_dispensadas(caminho: Optional[Path] = None) -> set[tuple[str, str]]:
    """
    Pares dispensados, como {(marca, modelo)}.

    A chave NÃO inclui o tipo de pendência de propósito: se amanhã uma fonte
    nova reclassificar o par de `sem_evidencia` pra `confirmado`, a decisão da
    usuária ("já olhei, deixa como está") continua valendo. O tipo é uma
    leitura nossa; a dispensa é sobre o par.
    """
    dispensadas: set[tuple[str, str]] = set()
    try:
        with open(caminho or DISPENSADAS_CSV, encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f):
                marca = (linha.get("marca") or "").strip()
                modelo = (linha.get("modelo") or "").strip()
                if not marca:
                    continue
                if (linha.get("acao") or "dispensar").strip() == "restaurar":
                    dispensadas.discard((marca, modelo))
                else:
                    dispensadas.add((marca, modelo))
    except FileNotFoundError:
        pass
    return dispensadas


def _registrar(marca: str, modelo: str, acao: str, motivo: str = "") -> None:
    """Anexa uma linha ao log de dispensas (append-only, última linha vence)."""
    novo = not DISPENSADAS_CSV.exists()
    DISPENSADAS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(DISPENSADAS_CSV, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if novo:
            w.writerow(["marca", "modelo", "acao", "motivo", "quando"])
        w.writerow([marca, modelo, acao, motivo,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")])


def dispensar(marca: str, modelo: str, motivo: str = "") -> dict[str, Any]:
    """Tira um par da fila sem alterar anúncio nem catálogo."""
    marca = (marca or "").strip()
    modelo = (modelo or "").strip()
    if not marca:
        raise ValueError("Marca é obrigatória pra dispensar uma pendência.")
    _registrar(marca, modelo, "dispensar", motivo)
    return {"marca": marca, "modelo": modelo, "dispensada": True}


def restaurar(marca: str, modelo: str) -> dict[str, Any]:
    """Devolve um par dispensado para a fila."""
    marca = (marca or "").strip()
    modelo = (modelo or "").strip()
    if not marca:
        raise ValueError("Marca é obrigatória pra restaurar uma pendência.")
    _registrar(marca, modelo, "restaurar")
    return {"marca": marca, "modelo": modelo, "dispensada": False}


def _classificar(evidencia: Optional[dict]) -> str:
    if not evidencia:
        return TIPO_SEM_EVIDENCIA
    if evidencia["suspeita"] == "modelo_truncado":
        return TIPO_CORRIGIR
    return TIPO_CONFIRMADO


def listar_pendencias(incluir_dispensadas: bool = False) -> dict[str, Any]:
    """
    A fila completa: cada par fora do catálogo, com a evidência externa e a
    ação sugerida.

    Reaproveita `listar_anuncios_a_verificar` como base — é ela que já sabe
    quais pares estão fora do catálogo consagrado e que exclui buggy por
    decisão da usuária — e acrescenta a camada de evidência.

    Retorna, além dos `pares`, os `totais` por tipo (pros contadores das abas)
    e as listas de marcas/modelos do catálogo que os campos de correção usam.
    """
    from src.pipeline.persistence import listar_anuncios_a_verificar

    base = listar_anuncios_a_verificar()
    dispensadas = carregar_dispensadas()

    pares: list[dict] = []
    for p in base["pares"]:
        marca = (p["marca"] or "").strip()
        modelo = (p["modelo"] or "").strip()
        chave = (marca, modelo)
        esta_dispensada = chave in dispensadas
        if esta_dispensada and not incluir_dispensadas:
            continue

        ev = evidencia_externa(marca, modelo)
        tipo = _classificar(ev)
        pares.append(
            {
                "marca": marca,
                "modelo": modelo,
                "qtd": p["qtd"],
                "tipo": tipo,
                "dispensada": esta_dispensada,
                # `sugestao` é o que vai pré-preenchido no campo de correção:
                # só faz sentido quando a fonte tem o nome completo que falta.
                "sugestao": ev["modelo_fonte"] if tipo == TIPO_CORRIGIR else "",
                "evidencia": ev,
            }
        )

    pares.sort(key=lambda x: (_ORDEM_TIPO[x["tipo"]], -x["qtd"], x["marca"], x["modelo"]))

    totais = {t: 0 for t in _ORDEM_TIPO}
    for p in pares:
        totais[p["tipo"]] += 1

    return {
        "pares": pares,
        "totais": totais,
        "total_pares": len(pares),
        "total_anuncios": sum(p["qtd"] for p in pares),
        "total_dispensadas": len(dispensadas),
        "marcas_catalogo": base["marcas_catalogo"],
        "modelos_catalogo": base["modelos_catalogo"],
    }


def listar_versoes_pendentes(limite: int = 400) -> dict[str, Any]:
    """
    Versões do banco que o vocabulário de trim não reconhece.

    Sai da auditoria de 2026-08-05: só 70,8% dos anúncios com versão batiam
    com o catálogo, e o grosso do resto NÃO é erro do banco — é o catálogo da
    Webmotors que não lista trim nacional real (Corcel II "L", Belina "L",
    S10 "Luxe"). Sem uma fila de curadoria esses ficam órfãos pra sempre.

    Cada linha traz uma `sugestao` pra orientar a decisão:

      trim_provavel  — o par tem vocabulário no catálogo e este token não
                       está lá; é candidato a trim faltando
      geracao        — as fontes externas conhecem o token como GERAÇÃO
                       daquele carro ('C1' da Corvette, 'E34' do M5, 'MK1'
                       do Golf). Valor certo, campo errado.
      sem_referencia — o par nem tem vocabulário; nada a comparar

    A pista de geração vem de `vocabulario_geracao_trim.csv` e é usada só
    como SUGESTÃO na tela, nunca como regra automática do pipeline — a fonte
    externa segue isolada, como combinado (ver docs/fontes_externas.md).
    """
    from src.catalog.externo import carregar_vocabulario, evidencia_externa
    from src.catalog.loader import _indice_trim, carregar_catalogo
    from src.pipeline.normalizer import VERSAO_AGREGADA, normalizar_texto
    from src.pipeline.persistence import _connect

    carregar_catalogo()
    trim_idx = _indice_trim()
    vocab_externo = carregar_vocabulario()

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT marca, modelo, versao, COUNT(*) AS n
                FROM anuncios
                WHERE versao IS NOT NULL AND versao <> '' AND versao <> %s
                GROUP BY marca, modelo, versao
                ORDER BY COUNT(*) DESC
                """,
                (VERSAO_AGREGADA,),
            )
            rows = cur.fetchall()

    pendentes: list[dict] = []
    for r in rows:
        mk = normalizar_texto(r["marca"] or "")
        md = normalizar_texto(r["modelo"] or "")
        vs = r["versao"]
        vocab = trim_idx.get((mk, md), set())
        if vocab and any(t in vocab for t in vs.split()):
            continue  # já reconhecida

        geracoes: set[str] = set(vocab_externo.get((mk, md), {}).get("geracoes", []))
        ev = evidencia_externa(mk, md)
        if ev:
            geracoes |= set(
                vocab_externo.get((mk, ev["modelo_fonte"]), {}).get("geracoes", [])
            )

        if vs in geracoes:
            sugestao = "geracao"
        elif vocab:
            sugestao = "trim_provavel"
        else:
            sugestao = "sem_referencia"

        pendentes.append(
            {
                "marca": mk,
                "modelo": md,
                "versao": vs,
                "qtd": r["n"],
                "sugestao": sugestao,
                # Amostra do vocabulário conhecido, pra usuária comparar sem
                # sair da tela.
                "vocabulario": sorted(vocab)[:10],
            }
        )

    totais: dict[str, int] = defaultdict(int)
    for p in pendentes:
        totais[p["sugestao"]] += 1

    return {
        "versoes": pendentes[:limite],
        "total": len(pendentes),
        "total_anuncios": sum(p["qtd"] for p in pendentes),
        "totais": dict(totais),
        "truncado": len(pendentes) > limite,
    }


def listar_sem_versao(limite: int = 300) -> dict[str, Any]:
    """
    Anúncios SEM versão nenhuma, agrupados por (marca, modelo).

    Diferente das outras abas, esta é DIAGNÓSTICA e não uma fila de cliques:
    são 14.213 anúncios (42% da base), volume que ninguém tria à mão. O que
    ela responde é "onde há versão sendo perdida, e onde a fonte simplesmente
    não tem o dado" — a diferença entre um bug de extração e um limite da
    fonte, que olhando anúncio a anúncio não dá pra ver.

    Cada anúncio cai em uma de quatro classes (auditoria 2026-08-05):

      recuperavel     o TÍTULO traz um trim conhecido daquele carro que não
                      foi capturado. "Volkswagen Gol 1.8 Mi Gl 8v" com versão
                      vazia — o GL está ali. É bug de extração, não curadoria.
      enumeracao      o título lista a linha inteira ("Kadett Gl/sl/lite/
                      turim"); o certo é a sentinela VERSAO_AGREGADA.
      fonte_nao_diz   o título só tem spec ("Fusca 1.3 8V Gasolina 2P"). Não
                      há versão a extrair; é limite da fonte.
      sem_vocabulario o par não tem vocabulário de trim no catálogo, então não
                      dá pra afirmar nada.

    Carroceria/tração (PICK-UP, FURGÃO, 4X4, COUPÉ) NÃO conta como trim
    perdido: o pipeline manda esses pra `obs` de propósito. Sem essa exclusão
    a conta de "recuperável" inflava de 3.284 pra 5.122 — quase o dobro.
    """
    from src.catalog.loader import _indice_trim, carregar_catalogo
    from src.pipeline.normalizer import (
        _CARROCERIA_TRACAO,
        _e_enumeracao_versoes,
        normalizar_texto,
    )
    from src.pipeline.persistence import _connect

    carregar_catalogo()
    trim_idx = _indice_trim()
    dispensadas = carregar_dispensadas()

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT marca, modelo, titulo, fonte
                FROM anuncios
                WHERE versao IS NULL OR versao = ''
                """
            )
            rows = cur.fetchall()

    grupos: dict[tuple[str, str], dict] = {}
    totais: dict[str, int] = defaultdict(int)

    for r in rows:
        mk = normalizar_texto(r["marca"] or "")
        md = normalizar_texto(r["modelo"] or "")
        titulo = r["titulo"] or ""
        vocab = trim_idx.get((mk, md))

        if not vocab:
            classe, achados = "sem_vocabulario", []
        else:
            nome = set(mk.replace("-", " ").split()) | set(md.replace("-", " ").split())
            achados = [
                t for t in normalizar_texto(titulo).split()
                if t in vocab and t not in nome and t not in _CARROCERIA_TRACAO
            ]
            if len(achados) >= 2 and _e_enumeracao_versoes(titulo, mk, md, achados):
                classe = "enumeracao"
            elif achados:
                classe = "recuperavel"
            else:
                classe = "fonte_nao_diz"

        totais[classe] += 1
        g = grupos.setdefault(
            (mk, md),
            {
                "marca": mk, "modelo": md, "qtd": 0,
                "recuperavel": 0, "enumeracao": 0,
                "fonte_nao_diz": 0, "sem_vocabulario": 0,
                "fontes": set(), "amostras": [],
            },
        )
        g["qtd"] += 1
        g[classe] += 1
        g["fontes"].add(r["fonte"])
        # Amostra só do que é recuperável: é o que a usuária precisa ver pra
        # confirmar que o trim está mesmo no título.
        if classe == "recuperavel" and len(g["amostras"]) < 3:
            g["amostras"].append({"titulo": titulo, "trim": achados[0], "fonte": r["fonte"]})

    lista = [
        {**g, "fontes": sorted(g["fontes"]),
         "dispensada": (g["marca"], g["modelo"]) in dispensadas}
        for g in grupos.values()
    ]
    # Mais recuperável primeiro: é onde um ajuste rende mais anúncios.
    lista.sort(key=lambda g: (-g["recuperavel"], -g["qtd"]))

    return {
        "grupos": lista[:limite],
        "total_grupos": len(lista),
        "total_anuncios": len(rows),
        "totais": dict(totais),
        "truncado": len(lista) > limite,
    }


def listar_aliases_pendentes(incluir_decididos: bool = False) -> dict[str, Any]:
    """
    Aliases PT-BR <-> EN que ainda precisam de conferência.

    Só as linhas de regra `fuzzy` entram na fila: as demais (`serie_n`,
    `classe_x`, `espacamento`) vêm de transformação determinística e não são
    palpite. As fuzzy são ordenadas por similaridade decrescente, que é a
    ordem em que vale a pena revisar.
    """
    from src.catalog.externo import listar_aliases

    todos = listar_aliases()
    fuzzy = [a for a in todos if a["regra"] == "fuzzy"]
    pendentes = [a for a in fuzzy if incluir_decididos or not a["decisao"]]
    pendentes.sort(key=lambda a: (-a["similaridade"], -a["n_anuncios"]))

    return {
        "aliases": pendentes,
        "total_pendentes": len([a for a in fuzzy if not a["decisao"]]),
        "total_deterministicos": len(todos) - len(fuzzy),
    }
