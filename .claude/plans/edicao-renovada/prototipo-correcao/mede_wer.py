# WER do TEI estruturado (pp. 421-442) contra o padrao-ouro.  python3 mede_wer.py [--fix]   (da raiz)
import os; T=os.path.dirname(os.path.abspath(__file__))
import re, difflib, sys, collections
from lxml import etree
g=open('vol2/02_parte_theodicea/01_cap_existencia-de-deus.tex',encoding='utf-8').read()
g=re.sub(r'(?m)%.*$','',g)
g=g.replace('---','—').replace('--','–')
g=re.sub(r'\\(pg|tese|teseB|sub|subp)\{(\d+)\}',' ',g)
g=re.sub(r'\\[a-zA-Z]+\*?(\[[^\]]*\])?',' ',g)
g=re.sub(r'[{}\\~]',' ',g)
s=open('vol2/vol2.estruturado.xml',encoding='utf-8').read()
i=s.find('<pb n="421"'); j=s.find('<pb n="443"')
import html
o=re.sub(r'<fw[^>]*>.*?</fw>',' ',s[i:j]); o=re.sub(r'<label>.*?</label>',' ',o); o=html.unescape(re.sub(r'<[^>]+>',' ',o))
tok=lambda t:[w for w in re.findall(r"[\wÀ-ÿ'’]+(?:-[\wÀ-ÿ]+)*",t) ]
import sys
if '--fix' in sys.argv:
    sys.path.insert(0,T); import corrige_lexico; o=corrige_lexico.corrige(o)
G,O=tok(g),tok(o)
G=G[G.index('Summario'):] if 'Summario' in G else G
print('gold',len(G),'ocr',len(O))
sm=difflib.SequenceMatcher(None,[w.lower() for w in G],[w.lower() for w in O],autojunk=False)
err=collections.Counter(); subs=[]
for op,a,b,c,d in sm.get_opcodes():
    if op=='equal': continue
    err[op]+=max(b-a,d-c)
    if op=='replace' and b-a==d-c:
        subs+=list(zip(G[a:b],O[c:d]))
    elif op!='equal': subs.append((' '.join(G[a:b]),' '.join(O[c:d])))
tot=sum(err.values()); print('erros',dict(err),'WER≈%.1f%%'%(100*tot/len(G)))
for x in subs: print(repr(x[0]),'->',repr(x[1]))
