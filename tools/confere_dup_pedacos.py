#!/usr/bin/env python3
"""Duplicatas entre pedaços vizinhos de uma rodada:  confere_dup_pedacos.py DIR [DIR…]
Para cada par de pedaços consecutivos (paginas/NNNN.revisado.xml), conta n-gramas de 10 palavras do
revisado que estão no pedaço anterior mas não na própria entrada."""
import glob, re, sys, collections
def ng(s, k=10):
    p = re.findall(r"\w+", re.sub(r"<[^>]+>", " ", s).lower())
    return collections.Counter(tuple(p[i:i + k]) for i in range(len(p) - k + 1))
for d in sys.argv[1:]:
    fs = sorted(glob.glob(f"{d}/paginas/*.revisado.xml"))
    for a, b in zip(fs, fs[1:]):
        eb = ng(open(b.replace("revisado", "entrada")).read())
        rb = ng(open(b).read())
        ra = ng(open(a).read())
        n = sum(1 for g in rb if g not in eb and g in ra)
        if n > 5:
            print(f"{b}: {n} n-gramas do pedaço anterior ({a.split('/')[-1][:4]})")
