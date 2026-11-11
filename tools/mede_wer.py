#!/usr/bin/env python3
"""WER do TEI estruturado contra o padrão-ouro transcrito à mão, separado em corpo e notas.

    python3 tools/mede_wer.py                                   # vol2/vol2.estruturado.xml, pp. 421-442
    python3 tools/mede_wer.py --xml /tmp/t.xml --lista 40       # e mostra as 40 primeiras trocas
    python3 tools/mede_wer.py --corrige                         # aplica tools/corrige_ocr.py antes

É o portão da correção automática (.claude/plans/edicao-renovada/correcao-automatica.md): nenhuma
regra entra se piora o WER.  Medir corpo e notas em separado mostra também erro de ESTRUTURA: nota
deixada no corpo aparece como inserção no corpo e omissão nas notas.  O total é o WER do texto
inteiro na ordem de leitura do padrão-ouro (nota no ponto da chamada), como no protótipo.
"""
import argparse
import collections
import difflib
import re
import sys
from pathlib import Path

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"
TOK = re.compile(r"[\wÀ-ÿ'’]+(?:-[\wÀ-ÿ]+)*")


def tex_limpo(s):
    s = s.replace("---", "—").replace("--", "–")
    s = re.sub(r"\\(pg|tese|teseB|sub|subp)\{(\d+)\}", " ", s)
    s = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", s)
    return re.sub(r"[{}\\~]", " ", s)


def le_ouro(caminho):
    """(texto_inteiro, corpo, notas) do .tex: cada \\footnote{...} vai para as notas."""
    g = re.sub(r"(?m)(?<!\\)%.*$", "", Path(caminho).read_text(encoding="utf-8"))
    corpo, notas, i = [], [], 0
    while True:
        j = g.find("\\footnote{", i)
        if j < 0:
            corpo.append(g[i:])
            break
        corpo.append(g[i:j])
        k, prof = j + len("\\footnote{"), 1
        while prof:
            prof += {"{": 1, "}": -1}.get(g[k], 0)
            k += 1
        notas.append(g[j + len("\\footnote{"):k - 1])
        corpo.append(" ")
        i = k
    return tex_limpo(g), tex_limpo("".join(corpo)), tex_limpo(" ".join(notas))


def le_tei(caminho, de, ate):
    """(texto_inteiro, corpo, notas) das páginas [de, ate] do TEI (sem <fw> e <label>)."""
    raiz = etree.parse(str(caminho)).getroot()
    tudo, corpo, notas = [], [], []
    dentro = False

    def visita(el, em_nota):
        nonlocal dentro
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag == TEI + "pb" and not em_nota:
            n = int(el.get("n"))
            dentro = de <= n <= ate
        pula = tag in (TEI + "fw", TEI + "label", TEI + "teiHeader")
        nota = em_nota or tag == TEI + "note"
        if el.text and dentro and not pula:
            tudo.append(el.text)
            (notas if nota else corpo).append(el.text)
        if not pula:
            for c in el:
                visita(c, nota)
                if c.tail and dentro:
                    tudo.append(c.tail)
                    (notas if nota else corpo).append(c.tail)
        tudo.append(" ")
        (notas if nota else corpo).append(" ")

    visita(raiz, False)
    return "".join(tudo), "".join(corpo), "".join(notas)


def wer(g, o):
    G, O = TOK.findall(g), TOK.findall(o)
    if "Summario" in G:
        G = G[G.index("Summario"):]
    sm = difflib.SequenceMatcher(None, [w.lower() for w in G], [w.lower() for w in O], autojunk=False)
    err, trocas = collections.Counter(), []
    for op, a, b, c, d in sm.get_opcodes():
        if op == "equal":
            continue
        err[op] += max(b - a, d - c)
        if op == "replace" and b - a == d - c:
            trocas += list(zip(G[a:b], O[c:d]))
        else:
            trocas.append((" ".join(G[a:b]), " ".join(O[c:d])))
    return len(G), len(O), err, trocas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xml", default="vol2/vol2.estruturado.xml")
    ap.add_argument("--ouro", default="vol2/02_parte_theodicea/01_cap_existencia-de-deus.tex")
    ap.add_argument("-f", "--de", type=int, default=421)
    ap.add_argument("-l", "--ate", type=int, default=442)
    ap.add_argument("--corrige", action="store_true", help="aplica tools/corrige_ocr.py ao TEI antes de medir")
    ap.add_argument("--sem", default="", help="com --corrige: regras a desligar (vírgula)")
    ap.add_argument("--lista", type=int, default=0, help="mostra as N primeiras trocas (texto inteiro)")
    a = ap.parse_args()
    xml = a.xml
    if a.corrige:
        sys.path.insert(0, str(Path(__file__).parent))
        import corrige_ocr
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "corrigido.xml"
        sem = set(filter(None, a.sem.split(",")))
        corrige_ocr.corrige_arquivo(Path(xml), tmp, None, quieto=True,
                                    ativas=[r for r in corrige_ocr.REGRAS if r not in sem])
        xml = tmp
    ouro, tei = le_ouro(a.ouro), le_tei(xml, a.de, a.ate)
    for nome, g, o in zip(("total", "corpo", "notas"), ouro, tei):
        ng, no, err, trocas = wer(g, o)
        tot = sum(err.values())
        print(f"{nome:6} ouro {ng:6} ocr {no:6}  WER {100 * tot / max(ng, 1):5.2f}%  {dict(err)}")
        if nome == "total":
            for x in trocas[:a.lista]:
                print(f"    {x[0]!r} -> {x[1]!r}")


if __name__ == "__main__":
    main()
