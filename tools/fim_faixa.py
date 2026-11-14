#!/usr/bin/env python3
"""Fim de uma faixa de revisão que não corta nota no meio:  fim_faixa.py VOL A N  → B (≥ A+N-1)
tal que nenhuma <note> que começa em página ≤ B continua (por <pb> interno) na página B+1.
Motivo: recortar PP-QQ no meio de uma nota longa deixa o texto da nota no TEI mas as imagens
e os <pb> só até QQ; o modelo vê texto de páginas que não tem e a revisão é recusada
(vol. 2, nota das pp. 47–59)."""
import re, sys
vol, a, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
s = open(f"{vol}/{vol}.corrigido.xml", encoding="utf-8").read()
fim = {}   # página do corpo onde a nota começa → última página que ela alcança
pag = 0
for m in re.finditer(r'<pb n="(\d+)"|<note\b.*?</note>', s, flags=re.S):
    if m.group(1):
        pag = int(m.group(1))
    else:
        pbs = [int(x) for x in re.findall(r'<pb n="(\d+)"', m.group(0))]
        if pbs:
            fim[pag] = max(fim.get(pag, 0), max(pbs))
b = a + n - 1
while True:
    if not any(p <= b < q for p, q in fim.items()):
        break
    b += 1
print(b)
