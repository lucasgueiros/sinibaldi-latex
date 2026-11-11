#!/usr/bin/env python3
"""WER do TEI estruturado contra o padrão-ouro transcrito à mão, separado em corpo e notas.

    python3 tools/mede_wer.py                                   # vol2/vol2.estruturado.xml, pp. 421-442
    python3 tools/mede_wer.py --xml /tmp/t.xml --lista 40       # e mostra as 40 primeiras trocas
    python3 tools/mede_wer.py --corrige                         # aplica tools/corrige_ocr.py antes
    python3 tools/mede_wer.py --vol vol1 [--corrige]            # ouro do vol. 1: vol1/ouro/*.tex

Padrões-ouro (OUROS): vol. 2, pp. 421-442 (um capítulo inteiro); vol. 1, blocos de 4 páginas em
vol1/ouro/<de>-<ate>_<nome>.tex (o intervalo sai do nome do arquivo).  Com vários blocos, cada um
é medido em separado e a linha "soma" junta os erros de todos.

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


OUROS = {
    "vol2": [("vol2/vol2.estruturado.xml", "vol2/02_parte_theodicea/01_cap_existencia-de-deus.tex",
              421, 442, "Summario")],
}


def ouros(vol):
    """[(xml, tex, de, ate, desde)] do volume; o vol. 1 lê os blocos de vol1/ouro/."""
    if vol in OUROS:
        return OUROS[vol]
    blocos = []
    for f in sorted(Path(vol, "ouro").glob("*.tex")):
        m = re.match(r"(\d+)-(\d+)_", f.name)
        if m:
            blocos.append((f"{vol}/{vol}.estruturado.xml", str(f), int(m[1]), int(m[2]), None))
    return blocos


def tex_limpo(s):
    s = re.sub(r"\\(begin|end)\{[^}]*\}", " ", s)
    s = re.sub(r"\\\\(\[[^\]]*\])?", " ", s)
    s = s.replace("---", "—").replace("--", "–")
    s = re.sub(r"\\(pg|tese|teseB|sub|subp)\{(\d+)\}", " ", s)
    s = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", s)
    return re.sub(r"[{}\\~]", " ", s)


def le_ouro(caminho):
    """(texto_inteiro, corpo, notas) do .tex: cada \\footnote{...} vai para as notas."""
    g = re.sub(r"(?m)(?<!\\)%.*$", "", Path(caminho).read_text(encoding="utf-8"))
    g = re.sub(r"(?m)^\\ifdefined\\pg\\else.*$", "", g)          # cabeçalho de compilação avulsa
    g = re.sub(r"\\csname\s*\w+\\endcsname", " ", g)
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


def wer(g, o, desde=None):
    G, O = TOK.findall(g), TOK.findall(o)
    if desde and desde in G:
        G = G[G.index(desde):]
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


def corrigido(xml, sem):
    sys.path.insert(0, str(Path(__file__).parent))
    import corrige_ocr
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "corrigido.xml"
    corrige_ocr.corrige_arquivo(Path(xml), tmp, None, quieto=True,
                                ativas=[r for r in corrige_ocr.REGRAS if r not in sem])
    return tmp


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vol", default="vol2", help="vol2 (pp. 421-442) ou vol1 (blocos de vol1/ouro/)")
    ap.add_argument("--xml", help="TEI a medir (padrão: volN/volN.estruturado.xml)")
    ap.add_argument("--ouro", help="um .tex avulso (exige -f/-l)")
    ap.add_argument("-f", "--de", type=int)
    ap.add_argument("-l", "--ate", type=int)
    ap.add_argument("--corrige", action="store_true", help="aplica tools/corrige_ocr.py ao TEI antes de medir")
    ap.add_argument("--sem", default="", help="com --corrige: regras a desligar (vírgula)")
    ap.add_argument("--lista", type=int, default=0, help="mostra as N primeiras trocas (texto inteiro)")
    a = ap.parse_args()
    if a.ouro:
        blocos = [(a.xml or f"{a.vol}/{a.vol}.estruturado.xml", a.ouro, a.de, a.ate, None)]
    else:
        blocos = [(a.xml or x, t, de, ate, d) for x, t, de, ate, d in ouros(a.vol)
                  if not (a.de and a.ate) or (de <= a.ate and a.de <= ate)]
    sem = set(filter(None, a.sem.split(",")))
    cache, soma = {}, collections.defaultdict(lambda: [0, 0])
    for xml, tex, de, ate, desde in blocos:
        if xml not in cache:
            cache[xml] = corrigido(xml, sem) if a.corrige else xml
        ouro, tei = le_ouro(tex), le_tei(cache[xml], de, ate)
        if len(blocos) > 1:
            print(f"pp. {de}-{ate}  {tex}")
        for nome, g, o in zip(("total", "corpo", "notas"), ouro, tei):
            ng, no, err, trocas = wer(g, o, desde)
            tot = sum(err.values())
            soma[nome][0] += ng
            soma[nome][1] += tot
            print(f"{nome:6} ouro {ng:6} ocr {no:6}  WER {100 * tot / max(ng, 1):5.2f}%  {dict(err)}")
            if nome == "total":
                for x in trocas[:a.lista]:
                    print(f"    {x[0]!r} -> {x[1]!r}")
    if len(blocos) > 1:
        for nome, (ng, tot) in soma.items():
            print(f"soma {nome:6} ouro {ng:6}  WER {100 * tot / max(ng, 1):5.2f}%")


if __name__ == "__main__":
    main()
