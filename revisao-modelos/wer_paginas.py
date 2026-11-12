#!/usr/bin/env python3
"""WER página a página de um .tex revisado contra a entrada (ambos contra o padrão-ouro).

    python3 revisao-modelos/wer_paginas.py revisao-modelos/por-pagina/haiku/vol2 [--vol vol2]
Notas que atravessam páginas inflam o número de cada página isolada; vale a diferença entre colunas.
"""
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FAIXA = {"vol2": (421, 442), "vol1": (331, 334)}


def wer(vol, tex, p):
    r = subprocess.run([sys.executable, "tools/mede_wer.py", "--vol", vol, "--tex", str(tex), "-f", str(p), "-l", str(p)],
                       cwd=RAIZ, capture_output=True, text=True).stdout
    return {m[1]: int(m[2]) for m in re.finditer(r"^(corpo|notas)\s+ouro\s+(\d+).*", r, re.M)} | \
        {m[1] + "_err": round(float(m[2]) * 0 + sum(int(x) for x in re.findall(r"\d+", m[3])))
         for m in re.finditer(r"^(corpo|notas)\s.*WER\s+([\d.]+)%\s+(\{.*\})", r, re.M)}


def main():
    d = Path(sys.argv[1]).resolve()
    vol = sys.argv[3] if len(sys.argv) > 3 else d.name
    de, ate = FAIXA[vol]
    print(f"{'p.':>4} | erros corpo ent→rev | erros notas ent→rev")
    for p in range(de, ate + 1):
        a, b = wer(vol, d / "entrada.tex", p), wer(vol, d / "revisado.tex", p)
        print(f"{p:>4} | {a.get('corpo_err', 0):>5} → {b.get('corpo_err', 0):<5} | "
              f"{a.get('notas_err', 0):>5} → {b.get('notas_err', 0):<5}")


if __name__ == "__main__":
    main()
