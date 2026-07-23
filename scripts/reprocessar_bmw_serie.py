"""
Reprocessamento das BMW cujo modelo ficou como "Série N" (2026-07-23 — a usuária
apontou que, na BMW, "Série" não é o modelo: o modelo é o número, 325i/328i/750i…).

Origem: anúncios do Mercado Livre, onde o campo estruturado "Modelo" da ficha
técnica traz a FAMÍLIA ("Série 3") em vez do número. O número específico só está
no título — e nem sempre está.

Regra de resolução (só corrige o que é determinável com segurança):
  1. Número explícito no título (325, 750il, 318im…) -> esse número (forma 325I).
  2. Sem número, mas a CILINDRADA define o modelo na linha BMW da época:
       Série 3: 1.6->316i, 1.8/1.9->318i, 2.0->320i, 2.8->328i
       Série 5: 2.0->520i, 2.5->525i, 2.8->528i, 3.0->530i, 3.5->535i, 4.0/4.4->540i
       Série 7: 3.5->735i, 4.0->740i, 5.4->750i
  AMBÍGUOS ficam INTACTOS (decisão da usuária 2026-07-23, curadoria manual):
    - "2.5 Série 3" (pode ser 323i ou 325i — mesma cilindrada);
    - "Série N" sem cilindrada nem número (ex.: "Serie 5 Imp/bmw").

Para cada registro determinável, reconstrói um título sintético com o número no
lugar de "Série N" e re-infere (modelo forçado ao alvo; versão/obs saem do
pipeline normal), mantendo a grafia canônica do catálogo.

Uso:
    python scripts/reprocessar_bmw_serie.py            # dry-run
    python scripts/reprocessar_bmw_serie.py --apply    # backup + aplica
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from src.pipeline.backup import fazer_backup
from src.pipeline.normalizer import inferir_marca_modelo_versao_obs_ano
from src.pipeline.persistence import _connect

# Cilindrada -> modelo por Série (fato da linha BMW BR anos 90). Sem o "2.5" da
# Série 3, que é ambíguo (323i x 325i) e fica pra curadoria manual.
_MAPA_CILINDRADA: dict[str, dict[str, str]] = {
    "3": {"1.6": "316I", "1.8": "318I", "1.9": "318I", "2.0": "320I", "2.8": "328I"},
    "5": {"2.0": "520I", "2.5": "525I", "2.8": "528I", "3.0": "530I", "3.5": "535I", "4.0": "540I", "4.4": "540I"},
    "7": {"3.5": "735I", "4.0": "740I", "5.4": "750I"},
}

_NUM_RE = re.compile(r"\b([1-8]\d{2})(?:i|ia|il|im|is)?\b", re.IGNORECASE)
_SERIE_RE = re.compile(r"(?i)\bs[eé]rie\s*([1-8])\b")
_CILINDRADA_RE = re.compile(r"\b(\d\.\d)\b")


def _alvo(titulo: str) -> str | None:
    """Modelo-alvo (ex.: '328I') ou None se ambíguo/sem informação."""
    tu = titulo.upper()
    sem_ano = re.sub(r"\b(19|20)\d{2}\b", " ", tu)

    m_num = _NUM_RE.search(sem_ano)
    if m_num:
        return f"{m_num.group(1)}I"  # forma canônica do catálogo (325 -> 325I)

    m_ser = _SERIE_RE.search(tu)
    m_cil = _CILINDRADA_RE.search(tu)
    if m_ser and m_cil:
        alvo = _MAPA_CILINDRADA.get(m_ser.group(1), {}).get(m_cil.group(1))
        if alvo:
            return alvo
    # Série 5 "V8 4.0" sem "4.0" isolado às vezes vem como "V8 4.0" — coberto acima;
    # V8 sozinho na Série 5 é 540i.
    if m_ser and m_ser.group(1) == "5" and re.search(r"\bV8\b", tu):
        return "540I"
    return None  # ambíguo (2.5 Série 3) ou sem info -> deixa pra curadoria manual


def _sintetico(titulo: str, alvo: str) -> str:
    """Título com o número canônico no lugar de 'Série N'/ano/número original."""
    t = re.sub(r"\b(19|20)\d{2}\b", " ", titulo)          # ano
    t = re.sub(r"(?i)\bs[eé]rie\s*[1-8]?\b", " ", t)       # Série N
    t = _NUM_RE.sub(" ", t)                                 # número original (+sufixo)
    t = re.sub(r"(?i)\bbmw\b", " ", t)                     # marca (recolocada)
    t = re.sub(r"\s+", " ", t).strip()
    return f"BMW {alvo} {t}".strip()


def main() -> None:
    aplicar = "--apply" in sys.argv

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, modelo, versao, obs, titulo FROM anuncios "
                "WHERE UPPER(marca) = 'BMW' AND UPPER(modelo) LIKE 'SERIE%' ORDER BY id"
            )
            rows = cur.fetchall()

        mudancas = []
        intactos = 0
        for r in rows:
            alvo = _alvo(r["titulo"] or "")
            if not alvo:
                intactos += 1
                continue
            _mk, modelo_n, versao_n, obs_n, _ano = inferir_marca_modelo_versao_obs_ano(
                _sintetico(r["titulo"], alvo)
            )
            modelo_n = alvo  # força o alvo (a inferência confirma, mas garantimos)
            if (modelo_n, versao_n, obs_n) != (r["modelo"], r["versao"], r["obs"]):
                mudancas.append((r["id"], r["modelo"], r["versao"], modelo_n, versao_n, obs_n, r["titulo"]))

        print(f"BMW Série*: {len(rows)}  |  a corrigir: {len(mudancas)}  |  intactos (ambíguo/sem info): {intactos}")
        for id_, mdv, vsv, mdn, vsn, obn, tit in mudancas:
            print(f"  #{id_}  {mdv!r}/{vsv!r} -> {mdn!r}/{vsn!r} obs={obn!r}")
            print(f"        {tit!r}")

        if not aplicar:
            print("\nDry-run — nada foi alterado. Rode com --apply pra gravar.")
            return

        print("\nGerando backup antes de aplicar...")
        caminho = fazer_backup()
        if caminho is None:
            print("ERRO: backup falhou — abortando.")
            sys.exit(1)
        print(f"Backup criado: {caminho}")

        with conn.cursor() as cur:
            for id_, _mdv, _vsv, mdn, vsn, obn, _tit in mudancas:
                cur.execute(
                    "UPDATE anuncios SET modelo = %s, versao = %s, obs = %s WHERE id = %s",
                    (mdn, vsn, obn, id_),
                )
        print(f"\nAplicadas {len(mudancas)} atualizações (commit ao sair do bloco).")


if __name__ == "__main__":
    main()
