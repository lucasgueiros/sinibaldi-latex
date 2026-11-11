# Prototipo (2026-11-11): regras deterministicas + lexico do proprio OCR com tabela de confusoes.
# Medido por mede_wer.py contra o cap. transcrito a mao (pp. 421-442). Rodar da raiz do repo.
import re, collections, glob, difflib, html, sys
W=re.compile(r"[A-Za-zÀ-ÿ]+")
lex=collections.Counter()
for f in glob.glob('vol*/paginas/0*.txt'):
    if f.startswith('vol2') and 421<=int(f[-8:-4])<=442: continue
    lex.update(w.lower() for w in W.findall(open(f,encoding='utf-8').read()))
CONF={'à':'áâãa','á':'àãâa','a':'áàãâ','ã':'áàa','ä':'ãá','è':'éêe','é':'eêèi','e':'cooéê','c':'eoç','o':'eóôõc','ó':'oôõ','ò':'óo',
 'í':'iì','ì':'íi','i':'íl','t':'i','ü':'ãu','u':'nüú','n':'uñ','A':'h','z':'s','s':'z','ç':'c','6':'é','f':'t','r':'t','l':'i','x':'e','á':'ã'}
PROT=set('seria séria esta está estás este será serão e é ser sêr pôr por pela pelo pêlo cá ca nós nos vós vos dê de dá da só so então mas mais pois quae quão posto peste fé no elle elie formula'.split())
def cands(w):
    out={w}
    for _ in range(2):
        new=set()
        for x in out:
            for i,ch in enumerate(x):
                for r in CONF.get(ch,''): new.add(x[:i]+r+x[i+1:])
        out|=new
    out.discard(w); return out
def fix_word(w):
    lw=w.lower()
    if len(w)<2: return w
    if re.fullmatch(r'D[A-Za-z]{2}[sS]',w) and w not in ('Deus','Dous','Dias','Deos') : return 'Deus'
    if len(w)<3 or lw in PROT: return w
    c0=lex[lw]
    if c0>=40 and len(w)<8: return w
    # italico: h->A no meio de palavra minuscula
    best=max(cands(w), key=lambda c:lex[c.lower()], default=None)
    if best and lex[best.lower()]>=30 and lex[best.lower()]>=10*max(c0,1):
        if w[0].isupper() and not best[0].isupper(): best=best[0].upper()+best[1:]
        return best
    return w
def corrige(t):
    t=re.sub(r"(?<=[a-zç])[àáâ]o(s?)\b",r"ão\1",t)
    t=re.sub(r"c[ãáà]o(s?)\b",r"ção\1",t)
    t=re.sub(r"(?<=[a-z])[óò]e(s|m)?\b",r"õe\1",t)
    t=re.sub(r"(?<=[a-z])cóes\b","ções",t)
    t=re.sub(r"\bà\b","á",t); t=re.sub(r"\bÀ\b","A",t); t=re.sub(r"\bàs\b","ás",t)
    t=re.sub(r"(?<=[a-zà-ÿ,] )6(?= [a-zà-ÿ])","é",t)
    return W.sub(lambda m:fix_word(m.group()),t)
