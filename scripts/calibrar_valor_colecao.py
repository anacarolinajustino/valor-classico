"""
Recalibra a curva de valor de coleção contra o estado atual do banco.

A curva converte a mediana do mercado aberto no preço que o mesmo modelo
alcança em estado de coleção. Ela é ajustada usando as lojas de carro antigo
como régua — ver o cabeçalho de src/pipeline/valor_colecao.py pro racional
completo, que não se repete aqui.

Este script NÃO escreve no banco nem no módulo: ele imprime o bloco
`Calibracao(...)` pronto pra colar em src/pipeline/valor_colecao.py. As
constantes ficam no código de propósito, sob revisão — um índice publicado
não pode ter o parâmetro mudando sozinho embaixo dele a cada coleta.

Rodar depois de cada coleta mensal. Se o expoente `b` pular muito de uma
rodada pra outra, isso é notícia sobre a base (fonte nova entrando, fonte
morrendo), não um detalhe de manutenção — conferir antes de colar.

Uso:
    python scripts/calibrar_valor_colecao.py
    python scripts/calibrar_valor_colecao.py --min-especializadas 10
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from datetime import date

from src.pipeline.persistence import _connect
from src.pipeline.valor_colecao import CALIBRACAO, FONTES_GENERALISTAS

# Amostra mínima de cada lado pra um modelo virar ponto do ajuste. A régua
# (lado especializado) é sempre curta — 8 anúncios já dão uma mediana que
# não é ruído puro, e exigir mais derruba metade dos modelos.
MIN_ESPECIALIZADAS = 8
MIN_GENERALISTAS = 40


def _pctl(v: list[float], q: float) -> float:
    """Percentil interpolado sobre lista JÁ ordenada."""
    if len(v) == 1:
        return v[0]
    i = q * (len(v) - 1)
    lo = math.floor(i)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def _ols(xs: list[float], ys: list[float]) -> tuple[float, float, float, float]:
    """Regressão simples. Devolve (a, b, r2, erro padrão de b)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    res = [y - (a + b * x) for x, y in zip(xs, ys)]
    sqe = sum(r * r for r in res)
    sqt = sum((y - my) ** 2 for y in ys)
    return a, b, (1 - sqe / sqt if sqt else 0.0), math.sqrt(sqe / (n - 2) / sxx)


def _pontos(min_esp: int, min_ger: int) -> list[tuple[str, str, float, float]]:
    """(marca, modelo, mediana generalista, mediana especializada)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT marca, modelo,
                       CASE WHEN fonte = ANY(%s) THEN 'g' ELSE 'e' END AS tipo,
                       preco
                FROM anuncios
                WHERE preco > 1000 AND marca IS NOT NULL AND modelo IS NOT NULL
                """,
                (list(FONTES_GENERALISTAS),),
            )
            grupos: dict[tuple[str, str], dict[str, list[float]]] = {}
            for r in cur.fetchall():
                d = grupos.setdefault((r["marca"], r["modelo"]), {"e": [], "g": []})
                d[r["tipo"]].append(float(r["preco"]))

    return [
        (marca, modelo, _pctl(sorted(d["g"]), 0.5), _pctl(sorted(d["e"]), 0.5))
        for (marca, modelo), d in grupos.items()
        if len(d["e"]) >= min_esp and len(d["g"]) >= min_ger
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-especializadas", type=int, default=MIN_ESPECIALIZADAS)
    ap.add_argument("--min-generalistas", type=int, default=MIN_GENERALISTAS)
    args = ap.parse_args()

    pontos = _pontos(args.min_especializadas, args.min_generalistas)
    if len(pontos) < 10:
        print(f"Só {len(pontos)} modelos com amostra dos dois lados — "
              "poucos pra ajustar. Afrouxe os mínimos ou colete mais.")
        return 1

    xs = [math.log(p[2]) for p in pontos]
    ys = [math.log(p[3]) for p in pontos]
    a, b, r2, ep_b = _ols(xs, ys)
    res = [y - (a + b * x) for x, y in zip(xs, ys)]
    sigma = math.sqrt(sum(r * r for r in res) / (len(res) - 2))
    t = (b - 1) / ep_b

    # Leave-one-out: cada modelo previsto por uma curva reajustada sem ele.
    # É o único número honesto aqui — o R² acima é sempre otimista porque o
    # modelo previsto ajudou a definir a curva que o prevê.
    erros = {"curva": [], "prêmio fixo": [], "sem correção": []}
    for i in range(len(pontos)):
        xi = [x for j, x in enumerate(xs) if j != i]
        yi = [y for j, y in enumerate(ys) if j != i]
        ai, bi, _, _ = _ols(xi, yi)
        premio = sum(yi) / len(yi) - sum(xi) / len(xi)   # o mesmo com b = 1
        erros["curva"].append(abs(ai + bi * xs[i] - ys[i]))
        erros["prêmio fixo"].append(abs(xs[i] + premio - ys[i]))
        erros["sem correção"].append(abs(xs[i] - ys[i]))
    loo = sorted(erros["curva"])[len(erros["curva"]) // 2]

    print(f"AJUSTE  ({len(pontos)} modelos com amostra dos dois lados)")
    print(f"  log(coleção) = {a:.3f} + {b:.3f} · log(mercado)")
    print(f"  R² {r2:.3f}   sigma residual {sigma:.3f}   erro padrão de b {ep_b:.3f}")
    # Se não rejeitar, a curva não está ganhando nada de um multiplicador
    # simples e o expoente vira só complexidade sem retorno.
    veredito = "REJEITA" if abs(t) > 2 else "NÃO rejeita (curva não se justifica)"
    print(f"  teste b = 1 (prêmio constante): t = {t:+.2f} -> {veredito}")

    print("\nVALIDAÇÃO leave-one-out (erro absoluto mediano em log)")
    for nome, e in erros.items():
        m = sorted(e)[len(e) // 2]
        print(f"  {nome:<14} {m:.3f}  -> tipicamente {(math.exp(m) - 1) * 100:>4.0f}% fora")

    ordem = sorted(range(len(pontos)), key=lambda i: res[i])
    print("\nMAIORES RESÍDUOS (modelo foge da curva — vale conferir a amostra)")
    for i in ordem[:3] + ordem[-3:]:
        marca, modelo, mg, me = pontos[i]
        print(f"  {marca[:9] + ' ' + modelo:<24} mercado {mg:>9,.0f}  "
              f"loja {me:>9,.0f}  curva {math.exp(a + b * xs[i]):>9,.0f}  "
              f"{math.exp(res[i]):>5.2f}x")

    print("\n" + "-" * 72)
    print("COLAR em src/pipeline/valor_colecao.py:\n")
    print("CALIBRACAO = Calibracao(")
    print(f"    a={a:.3f},")
    print(f"    b={b:.3f},")
    print(f"    sigma={sigma:.3f},")
    print(f"    r2={r2:.3f},")
    print(f"    n_modelos={len(pontos)},")
    print(f"    erro_loo={loo:.3f},")
    print(f'    data="{date.today().isoformat()}",')
    print(")")

    v = CALIBRACAO
    print(f"\nvigente: a={v.a} b={v.b} sigma={v.sigma} (de {v.data})")
    if abs(b - v.b) > 3 * ep_b:
        print(f"  ATENÇÃO: b mudou {abs(b - v.b):.3f}, mais de 3 erros padrão. "
              "Alguma fonte entrou ou morreu — investigar antes de colar.")
    for m in (20_000, 50_000, 150_000):
        antes = math.exp(v.a + v.b * math.log(m))
        agora = math.exp(a + b * math.log(m))
        print(f"  mercado {m:>7,} -> {antes:>9,.0f} vira {agora:>9,.0f}  "
              f"({agora / antes:.2f}x)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
