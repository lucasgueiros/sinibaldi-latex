#!/usr/bin/env python3
"""Resumo numérico de uma rodada de revisão:  resumo_rodada.py DIR   (entrada × revisado por pedaço)"""
import re, glob, sys
def an(f):
    s = open(f).read(); n = ''.join(re.findall(r'<note.*?</note>', s, flags=re.S))
    return len(re.sub(r'<[^>]+>', '', s)), len(re.sub(r'<[^>]+>', '', n)), s.count('<note'), len(re.findall('<pb', s))
for f in sorted(glob.glob(sys.argv[1] + '/paginas/*.revisado.xml')):
    a = an(f.replace('revisado', 'entrada')); b = an(f); d = 100 * (b[0] - a[0]) / max(1, a[0])
    print(f.split('/')[-1][:4], a, b, 'Δ%.1f%%' % d, '' if (a[2:] == b[2:] and abs(d) < 1.5) else '<<<')
