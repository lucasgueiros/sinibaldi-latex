#!/usr/bin/env python3
"""Monta a BASE dos slides de um nó: um slide por trecho marcado %%>>> id / %%<<< id
no .tex, com o texto do livro convertido para Markdown legível (sem LaTeX).

    python3 tools/gera_slides_base.py vol2/02_secao_x/01_cap_y/01_cap_y.tex
    # -> vol2/02_secao_x/01_cap_y/01_cap_y.slides.base.md

Esse arquivo é a matéria-prima para o LLM: ele deve manter o texto citado do
livro exatamente e acrescentar título, tópicos e explicação didática ao redor,
salvando o resultado como <stem>.slides.md.  A conversão LaTeX->texto aqui é
best-effort; o par humano+LLM acerta o resto.
"""
import argparse
import os
import re
import sys

BLOCO = re.compile(r"^%%>>> *(\S+) *$\n(.*?)^%%<<< *\1 *$", re.M | re.S)
_CMD = re.compile(r"\\([A-Za-z]+)")

MAC2 = {
    "tese":   lambda a, b: f"**{a}. {b}** \u2014 ",
    "teseB":  lambda a, b: f"**{a}. {b}**\n\n",
    "sub":    lambda a, b: f"{a}) *{b}* \u2014 ",
    "secnum": lambda a, b: f"**{a}. {b}**\n\n",
}
MAC1 = {
    "emph":     lambda a: f"*{a}*",
    "textit":   lambda a: f"*{a}*",
    "textbf":   lambda a: f"**{a}**",
    "textup":   lambda a: a,
    "textsc":   lambda a: a,
    "text":     lambda a: a,
    "pg":       lambda a: f"[{a}] ",
    "pagmark":  lambda a: f"[{a}] ",
    "subp":     lambda a: f"{a}) ",
    "footnote": lambda a: f" (nota: {a})",
}


def _read_group(s: str, i: int):
    """s[i] == '{' -> (conteudo, indice apos o '}' casado)."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
    return s[i + 1:], len(s)


def _scan(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        m = _CMD.search(s, i)
        if not m:
            out.append(s[i:])
            break
        out.append(s[i:m.start()])
        name, j = m.group(1), m.end()
        groups = []
        while j < len(s) and s[j] == "{":
            g, j = _read_group(s, j)
            groups.append(_scan(g))
        if name in MAC2 and len(groups) >= 2:
            out.append(MAC2[name](groups[0], groups[1]))
            out.extend(groups[2:])
        elif name in MAC1 and len(groups) >= 1:
            out.append(MAC1[name](groups[0]))
            out.extend(groups[1:])
        elif groups:
            out.append(" ".join(groups))          # comando desconhecido: fica o argumento
        # comando sem argumento e desconhecido: descartado
        i = j
    return "".join(out)


def deteximar(s: str) -> str:
    s = _scan(s)
    s = s.replace("\\textemdash{}", "\u2014").replace("\\textemdash", "\u2014")
    s = s.replace("---", "\u2014").replace("--", "\u2013")
    s = re.sub(r"\\l?dots(\{\})?", "\u2026", s)
    s = s.replace("\\quad", " ").replace("\\qquad", " ").replace("\\enspace", " ")
    s = re.sub(r"\\[ ,;:]", " ", s)
    for cmd in ("noindent", "bigskip", "medskip", "smallskip", "vspace", "vfill"):
        s = s.replace("\\" + cmd, "")
    s = s.replace("\\par", "\n\n").replace("~", " ")
    s = re.sub(r"\{\}", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


CABECALHO = (
    "# Slides — {stem}  (base gerada por script)\n\n"
    "<!--\n"
    "Instruções para o LLM: cada bloco separado por `---` é UM slide.  O texto em\n"
    "citação (`>`) é do livro e deve ser reproduzido EXATAMENTE — não parafrasear,\n"
    "não modernizar a ortografia.  Acrescente ao redor: um título curto, tópicos de\n"
    "apoio e uma explicação didática.  Devolva Markdown com o mesmo separador `---`\n"
    "entre slides e salve como {stem}.slides.md.\n"
    "-->\n"
)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tex", help="fragmento .tex com marcadores %%>>> id / %%<<< id")
    ap.add_argument("-o", "--out", help="padrão: <tex sem .tex>.slides.base.md")
    a = ap.parse_args()

    fonte = open(a.tex, encoding="utf-8").read()
    blocos = BLOCO.findall(fonte)
    if not blocos:
        sys.exit(f"nenhum trecho %%>>> ... %%<<< em {a.tex} "
                 f"(marque os trechos que vão para os slides)")

    stem = os.path.splitext(os.path.basename(a.tex))[0]
    partes = [CABECALHO.format(stem=stem)]
    for tid, corpo in blocos:
        texto = deteximar(corpo)
        citado = "\n".join("> " + l if l.strip() else ">" for l in texto.split("\n"))
        partes.append(f"---\n\n## {tid}\n\n{citado}\n")

    saida = a.out or (os.path.splitext(a.tex)[0] + ".slides.base.md")
    open(saida, "w", encoding="utf-8").write("\n".join(partes) + "\n")
    print(f"escrito: {saida}  ({len(blocos)} slide(s))")


if __name__ == "__main__":
    main()
