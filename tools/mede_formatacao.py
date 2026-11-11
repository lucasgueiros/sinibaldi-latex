#!/usr/bin/env python3
"""Precisão/revocação da formatação detectada (tools/formatacao.py) contra o padrão-ouro.

    python3 tools/mede_formatacao.py                         # vol2, pp. 421-442, <id>.fmt.tsv
    python3 tools/mede_formatacao.py --xml vol2/vol2.estruturado.xml   # mede o TEI (<hi rend>)
    python3 tools/mede_formatacao.py --imagens DIR --erros 30           # decide de novo e lista erros

Rótulos: cada token do .tex feito à mão leva o estilo em que está (\\emph -> it, \\textsc -> sc,
\\textbf e enunciado de \\tese -> bold, rubrica de \\sub -> it; o resto rom).  As palavras do OCR
são alinhadas aos tokens do ouro (difflib, como mede_wer.py); só as que casam exatamente entram
na conta (~80% das palavras; as mal lidas ficam de fora).  É o portão de qualquer mudança nos
parâmetros de tools/formatacao.py.
"""
import argparse
import csv
import difflib
import re
import sys
from collections import Counter
from pathlib import Path

TOK = re.compile(r"[\wÀ-ÿ'’]+(?:-[\wÀ-ÿ]+)*")
EST = {"emph": "it", "textit": "it", "textsc": "sc", "textbf": "bold"}
OURO = "vol2/02_parte_theodicea/01_cap_existencia-de-deus.tex"


def tokens_ouro(caminho):
    """[(token, estilo)] do .tex do padrão-ouro, a partir do Summario."""
    s = re.sub(r"(?m)(?<!\\)%.*$", "", Path(caminho).read_text(encoding="utf-8"))
    i = s.find("Summario")
    s = s[max(0, i - 40):] if i >= 0 else s
    out, pilha, buf = [], [], []

    def estilo():
        return next((e for e in reversed(pilha) if e), "rom")

    def flush():
        for m in TOK.finditer("".join(buf)):
            out.append((m.group(), estilo()))
        buf.clear()

    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            m = re.match(r"\\([a-zA-Z]+)\*?", s[i:])
            if not m:
                i += 2
                continue
            cmd = m.group(1)
            i += m.end()
            if cmd in ("tese", "teseB", "sub"):
                i = s.index("}", i) + 1                   # 1o argumento: numero / letra
                if s[i:i + 1] == "{":
                    flush()
                    pilha.append("it" if cmd == "sub" else "bold")
                    i += 1
                continue
            if cmd in ("pg", "pgn", "subp"):
                i = s.index("}", i) + 1
                continue
            if s[i:i + 1] == "{":
                flush()
                pilha.append(EST.get(cmd))
                i += 1
                continue
            buf.append(" ")
            continue
        if c == "{":
            flush()
            pilha.append(None)
        elif c == "}":
            flush()
            if pilha:
                pilha.pop()
        else:
            buf.append(" " if c == "~" else c)
        i += 1
    flush()
    return out


def _norm(w):
    return w.lower().translate(str.maketrans("ãáàâéêíóôõúç", "aaaaeeiooouc"))


def palavras_tsv(pasta, de, ate):
    """[(pagina, chave, token)] das palavras do OCR na ordem do .tsv."""
    mani = {}
    with open(Path(pasta) / "manifesto.tsv", encoding="utf-8") as f:
        next(f)
        for l in f:
            pid, imp = l.split("\t")[:2]
            mani[int(imp)] = pid
    ws = []
    for p in range(de, ate + 1):
        tsv = Path(pasta) / f"{mani[p]}.tsv"
        with open(tsv, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                if r["level"] == "5" and r["text"].strip() and float(r["conf"]) >= 0:
                    m = TOK.search(r["text"])
                    if m:
                        ws.append((p, (r["block_num"], r["par_num"], r["line_num"], r["word_num"]), m.group()))
    return ws, mani


def rotula(ouro, pasta, de=421, ate=442):
    """{(pagina, chave): estilo} das palavras do OCR que casam com o ouro."""
    g = tokens_ouro(ouro)
    t, _ = palavras_tsv(pasta, de, ate)
    sm = difflib.SequenceMatcher(None, [_norm(w) for w, _ in g], [_norm(x[2]) for x in t], autojunk=False)
    lab = {}
    for a, b, k in sm.get_matching_blocks():
        for j in range(k):
            p, chave, _ = t[b + j]
            lab[(p, chave)] = g[a + j][1]
    return lab


def detectado_fmt(pasta, mani, de, ate):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import formatacao
    det = {}
    for p in range(de, ate + 1):
        for k, r in formatacao.le_fmt(Path(pasta) / f"{mani[p]}.fmt.tsv").items():
            det[(p, k)] = r
    return det


def relatorio(lab, det, erros=0, textos=None):
    conf = Counter()
    for k, l in lab.items():
        conf[(l, det.get(k, "") or "rom")] += 1
    linhas = []
    for e in ("it", "sc", "bold"):
        vp = conf[(e, e)]
        fp = sum(v for (l, d), v in conf.items() if d == e and l != e)
        fn = sum(v for (l, d), v in conf.items() if l == e and d != e)
        p = vp / (vp + fp) if vp + fp else 0
        r = vp / (vp + fn) if vp + fn else 0
        f1 = 2 * p * r / (p + r) if p + r else 0
        linhas.append(f"{e:5} ouro {vp + fn:5}  detect {vp + fp:5}  P {100 * p:5.1f}%  R {100 * r:5.1f}%  F1 {100 * f1:5.1f}%")
    acc = sum(v for (l, d), v in conf.items() if l == d) / max(1, sum(conf.values()))
    linhas.append(f"palavras rotuladas {sum(conf.values())}; acerto global {100 * acc:.2f}%")
    print("\n".join(linhas))
    if erros and textos:
        n = 0
        for k, l in sorted(lab.items()):
            d = det.get(k, "") or "rom"
            if d != l:
                print(f"  p.{k[0]} {'/'.join(k[1])} {textos.get(k, '?')!r}: ouro {l}, detectado {d}")
                n += 1
                if n >= erros:
                    break
    return conf


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pasta", default="vol2/paginas")
    ap.add_argument("--ouro", default=OURO)
    ap.add_argument("-f", "--de", type=int, default=421)
    ap.add_argument("-l", "--ate", type=int, default=442)
    ap.add_argument("--imagens", help="decide de novo a partir das medidas (cache) em vez de ler <id>.fmt.tsv")
    ap.add_argument("--erros", type=int, default=0, help="lista os N primeiros desacordos")
    a = ap.parse_args()
    lab = rotula(a.ouro, a.pasta, a.de, a.ate)
    t, mani = palavras_tsv(a.pasta, a.de, a.ate)
    textos = {(p, k): w for p, k, w in t}
    if a.imagens:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import formatacao as F
        pasta, imgs = Path(a.pasta), Path(a.imagens)
        pags = [(mani[p], p) for p in range(a.de, a.ate + 1)]
        med = F.mede(pasta, imgs, pags, jobs=4, quieto=True)
        gab = F.carrega_gabarito()
        gab = F.ajusta_gabarito([d["vec"] for ws in med.values() for d in ws if d["vec"] is not None], gab)
        det = {}
        for pid, p in pags:
            for d in F.decide(med[pid], gab):
                if d["rend"]:
                    det[(p, (d["block"], d["par"], d["line"], d["word"]))] = d["rend"]
    else:
        det = detectado_fmt(a.pasta, mani, a.de, a.ate)
    relatorio(lab, det, a.erros, textos)


if __name__ == "__main__":
    main()
