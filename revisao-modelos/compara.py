#!/usr/bin/env python3
"""Tabela da comparação de modelos (revisao-modelos/<modelo>/<vol>/, de roda.sh).

    python3 revisao-modelos/compara.py                         # revisao-modelos/<m>/<vol>/ (agente, roda.sh)
    python3 revisao-modelos/compara.py revisao-modelos/por-pagina       # por página sobre o .tex (antigo)
    python3 revisao-modelos/compara.py revisao-modelos/por-pagina-xml   # por página sobre o TEI (roda_por_pagina.sh)
Se houver revisado.xml/entrada/volN.xml ao lado do .tex, o WER é medido no TEI.
WER contra o padrão-ouro (docs/07): vol. 2 = capítulo inteiro (pp. 421-442); vol. 1 = só o bloco
331-334 que o ouro cobre (o capítulo vai até 359).  Custo/turnos/tempo do resultado.json do claude -p.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
AQUI = Path(__file__).resolve().parent
FAIXA = {"vol2": (421, 442), "vol1": (331, 334)}


def wer(vol, tex, tei=True):
    de, ate = FAIXA[vol]
    xml = Path(tex).with_suffix(".xml")      # revisão sobre TEI: mede o XML (sem os números de \\pgn)
    fonte = ["--xml", str(xml)] if tei and xml.exists() else ["--tex", str(tex)]
    r = subprocess.run([sys.executable, "tools/mede_wer.py", "--vol", vol, *fonte, "-f", str(de),
                        "-l", str(ate)], cwd=RAIZ, capture_output=True, text=True)
    out = {}
    for m in re.finditer(r"^(total|corpo|notas)\s.*WER\s+([\d.]+)%", r.stdout, re.M):
        out[m[1]] = float(m[2])
    return out


def integridade(tex):
    s = Path(tex).read_text(encoding="utf-8")
    pgs = re.findall(r"\\pg\{(\d+)\}", s)
    return {"pg": len(pgs), "pg_dup": len(pgs) - len(set(pgs)), "chaves": s.count("{") - s.count("}"),
            "notas": s.count("\\footnote{")}


def main():
    raiz = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else AQUI
    linhas = ["| modelo | vol | WER total | corpo | notas | \\pg (dup) | notas | Δchaves | turnos | pedaços (recusados) | tokens ent/saí | min | US$ |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    base = {}
    for vol in ("vol2", "vol1"):
        e = AQUI / "entrada" / f"{vol}.tex"
        base[vol] = wer(vol, e, tei=raiz.name.endswith("-xml"))   # entrada/volN.xml só na rodada TEI
        i = integridade(e)
        linhas.append(f"| *pipeline* | {vol} | {base[vol]['total']:.2f}% | {base[vol]['corpo']:.2f}% | "
                      f"{base[vol]['notas']:.2f}% | {i['pg']} ({i['pg_dup']}) | {i['notas']} | {i['chaves']} | | | | | |")
    tot = {}
    for d in sorted(raiz.glob("*/vol*/revisado.tex")):
        modelo, vol = d.parent.parent.name, d.parent.name
        w, i = wer(vol, d), integridade(d)
        try:
            j = json.loads((d.parent / "resultado.json").read_text())
        except (OSError, ValueError):
            j = {}
        custo, turnos, mins = j.get("total_cost_usd", 0) or 0, j.get("num_turns", "?"), (j.get("duration_ms") or 0) / 6e4
        erro = " ⚠" if (j.get("is_error") and "feitos" not in j) or not j else ""
        u = j.get("usage") or {}
        ent = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        ped = f"{j['feitos']}/{j['pedacos']} ({len(j.get('falhas') or {})})" if "feitos" in j else ""
        t = tot.setdefault(modelo, [0, 0])
        t[0] += custo
        t[1] += mins
        linhas.append(f"| {modelo}{erro} | {vol} | {w.get('total', float('nan')):.2f}% | {w.get('corpo', float('nan')):.2f}% | "
                      f"{w.get('notas', float('nan')):.2f}% | {i['pg']} ({i['pg_dup']}) | {i['notas']} | {i['chaves']} | "
                      f"{turnos} | {ped} | {ent / 1e3:.0f} k / {(u.get('output_tokens') or 0) / 1e3:.0f} k | {mins:.0f} | {custo:.2f} |")
    print("\n".join(linhas))
    print()
    for m, (c, mins) in tot.items():
        print(f"- **{m}**: US$ {c:.2f}, {mins:.0f} min (soma dos dois capítulos)")


if __name__ == "__main__":
    main()
