#!/usr/bin/env python3
"""Léxico do corpus (frequência das formas no OCR dos dois volumes) + formas válidas em dicionário.

    .venv/bin/python tools/lexico.py gera      # (re)gera tools/dados/validas.tsv (precisa de spylls)

Usado por tools/corrige_ocr.py e tools/estruturar_tei.py (dehifenização).

Frequência: contagem das formas (minúsculas) em vol*/paginas/*.txt, EXCLUÍDAS por padrão as
páginas dos padrões-ouro (TESTE: vol. 2, pp. 421-442; vol. 1, três blocos):
elas são só teste, nada é aprendido delas.

Dicionário: hunspell pt_PT e fr (pacotes hunspell-pt-pt e hunspell-fr do sistema), consultados
por spylls só no `gera`.  O resultado (as formas do corpus que algum dicionário aceita) fica
versionado em tools/dados/validas.tsv, para as ferramentas rodarem sem spylls.  O pt_PT não
conhece a grafia de 1916 (philosophia), mas essas formas são frequentes no corpus e ficam
protegidas pela frequência; o dicionário protege as palavras válidas RARAS (medo, era, entra), que
a frequência sozinha trocava pela vizinha frequente (modo, ora, outra).
"""
import re
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
VALIDAS = Path(__file__).resolve().parent / "dados" / "validas.tsv"
PALAVRA = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
COMPOSTA = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:-[A-Za-zÀ-ÖØ-öø-ÿ]+)*")   # refere-se, reduzem-se
# padrões-ouro: fora do léxico.  vol. 1: blocos de vol1/ouro/ mais a página seguinte, onde
# acabam as notas transcritas no ouro (tools/mede_wer.py).
TESTE = {"vol2": [(421, 442)], "vol1": [(62, 66), (331, 335), (577, 581)]}


def paginas_txt(excluir=TESTE):
    for vol in ("vol1", "vol2"):
        for f in sorted((RAIZ / vol / "paginas").glob("*.txt")):
            if f.stem.isdigit() and any(de <= int(f.stem) <= ate for de, ate in excluir.get(vol, ())):
                continue
            yield f


@lru_cache(maxsize=None)
def frequencias(excluir_teste=True):
    c = Counter()
    for f in paginas_txt(TESTE if excluir_teste else {}):
        c.update(w.lower() for w in PALAVRA.findall(f.read_text(encoding="utf-8")))
    return c


@lru_cache(maxsize=None)
def regentes_crase(minimo=2, razao=0.25):
    """palavras que regem crase (relação á, egual á, sujeito á): seguidas de á/à em >= `minimo`
    ocorrências e >= `razao` x as vezes em que vêm antes de "a".  Aprendidas só do vol. 2 (fora do
    padrão-ouro), cujo OCR põe acento em "a" na taxa normal da crase (12%); o do vol. 1 inventa
    acento (27%) e por isso é o que a regra "crase" de corrige_ocr.py corrige."""
    return _crase(minimo, razao)[0]


@lru_cache(maxsize=None)
def locucoes_crase(minimo=3, razao=1.0):
    """palavras que vêm depois de á/à pelo menos tanto quanto depois de "a" (á excepção, á medida):
    locuções em que a crase é a regra.  Mesmo corpus de regentes_crase."""
    return _crase(minimo, razao)[1]


@lru_cache(maxsize=None)
def _crase(minimo, razao):
    c, d = {}, {}
    excl = TESTE.get("vol2", ())
    for f in sorted((RAIZ / "vol2" / "paginas").glob("*.txt")):
        if f.stem.isdigit() and any(de <= int(f.stem) <= ate for de, ate in excl):
            continue
        toks = [w.lower() for w in COMPOSTA.findall(f.read_text(encoding="utf-8"))]
        for p, w in zip(toks, toks[1:]):
            if w in ("a", "á", "à"):
                n = c.setdefault(p, [0, 0])
                n[w != "a"] += 1
            if p in ("a", "á", "à"):
                n = d.setdefault(w, [0, 0])
                n[p != "a"] += 1
    return tuple(frozenset(p for p, (a, cr) in x.items() if cr >= minimo and cr >= razao * a) for x in (c, d))


@lru_cache(maxsize=None)
def validas():
    """{forma: 'pt'|'fr'|'pt,fr'} das formas do corpus aceitas por dicionário (vazio se não gerado)."""
    if not VALIDAS.exists():
        print(f"aviso: {VALIDAS} não existe; sem proteção por dicionário "
              f"(gerar com .venv/bin/python tools/lexico.py gera)", file=sys.stderr)
        return {}
    out = {}
    with open(VALIDAS, encoding="utf-8") as f:
        next(f)
        for l in f:
            w, d = l.rstrip("\n").split("\t")
            out[w] = d
    return out


def valida(w):
    """a forma (como está, ou em minúsculas) está em algum dicionário?"""
    v = validas()
    return w in v or w.lower() in v


def gera():
    from spylls.hunspell import Dictionary
    dics = {"pt": Dictionary.from_files("/usr/share/hunspell/pt_PT"),
            "fr": Dictionary.from_files("/usr/share/hunspell/fr")}
    formas = set()
    for f in paginas_txt({}):
        formas.update(PALAVRA.findall(f.read_text(encoding="utf-8")))
    formas |= {w.lower() for w in formas}
    VALIDAS.parent.mkdir(exist_ok=True)
    n = 0
    with open(VALIDAS, "w", encoding="utf-8") as out:
        out.write("forma\tdicionario\n")
        for w in sorted(formas):
            if len(w) < 2:
                continue
            ok = [k for k, d in dics.items() if d.lookup(w)]
            if ok:
                out.write(f"{w}\t{','.join(ok)}\n")
                n += 1
    print(f"{VALIDAS}: {n} de {len(formas)} formas aceitas por pt_PT/fr", file=sys.stderr)


if __name__ == "__main__":
    if sys.argv[1:] == ["gera"]:
        gera()
    else:
        sys.exit(__doc__)
