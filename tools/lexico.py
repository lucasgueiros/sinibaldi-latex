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
