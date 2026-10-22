#!/usr/bin/env python3
"""Corta um no da arvore: gera <stem>.pdf (mutool merge) e <stem>.txt (fatia do
texto etiquetado).  Substitui o corte manual no iLovePDF que foi usado no vol.1.

    # um no, faixa em pagina IMPRESSA
    python3 tools/corta.py vol2/02_secao_x/01_cap_y 3 28 --offset 12

    # varios nos de uma vez, a partir do manifesto
    python3 tools/corta.py --tsv vol2/estrutura.tsv --offset 12
    python3 tools/corta.py --tsv vol2/estrutura.tsv --offset 12 --only vol2/02_secao_x

<stem> = basename do diretorio destino.  Os arquivos ficam em
<destino>/<stem>.pdf e <destino>/<stem>.txt.  Idempotente (reescreve).

Use --raw quando pag_ini/pag_fim ja forem indices de pagina do PDF (p.ex. no
miolo pre-textual, de numeracao romana).  estrutura.tsv: uma linha por no,
'caminho <tab/espacos> pag_ini <...> pag_fim', '#' inicia comentario.
"""
import argparse
import os
import re
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARC = re.compile(r"^<<<PAG (\S+) pdf=(\d+)>>>$")


def _abs(p: str) -> str:
    return p if os.path.isabs(p) else os.path.join(RAIZ, p)


def corta_pdf(src_pdf: str, p0: int, p1: int, destino: str) -> None:
    subprocess.run(["mutool", "merge", "-o", destino, src_pdf, f"{p0}-{p1}"],
                   check=True, capture_output=True)


def corta_txt(src_txt: str, p0: int, p1: int, destino: str) -> None:
    linhas = open(src_txt, encoding="utf-8", errors="replace").read().splitlines(keepends=True)
    out, dentro = [], False
    for ln in linhas:
        m = MARC.match(ln.rstrip("\n"))
        if m:
            dentro = p0 <= int(m.group(2)) <= p1
        if dentro:
            out.append(ln)
    if not out:
        sys.exit(f"nenhuma pagina pdf {p0}-{p1} encontrada em {src_txt} "
                 f"(rodou extract_paginado.py? offset certo?)")
    open(destino, "w", encoding="utf-8").write("".join(out))


def um_no(caminho, pag_ini, pag_fim, offset, raw, src_pdf, src_txt):
    d = _abs(caminho).rstrip("/")
    os.makedirs(d, exist_ok=True)
    stem = os.path.basename(d)
    p0 = pag_ini if raw else pag_ini + offset
    p1 = pag_fim if raw else pag_fim + offset
    corta_pdf(src_pdf, p0, p1, os.path.join(d, stem + ".pdf"))
    corta_txt(src_txt, p0, p1, os.path.join(d, stem + ".txt"))
    print(f"{caminho}: pdf {p0}-{p1}  ->  {stem}.pdf  {stem}.txt")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("destino", nargs="?", help="diretorio do no")
    ap.add_argument("pag_ini", nargs="?", type=int)
    ap.add_argument("pag_fim", nargs="?", type=int)
    ap.add_argument("--tsv", help="manifesto de nos (caminho pag_ini pag_fim por linha)")
    ap.add_argument("--only", help="com --tsv: so linhas cujo caminho comeca por isto")
    ap.add_argument("--offset", type=int, default=15,
                    help="impressa + offset = indice pdf (vol1: 15; vol2: descobrir)")
    ap.add_argument("--raw", action="store_true",
                    help="pag_ini/fim ja sao indices de pagina do PDF")
    ap.add_argument("--pdf", default="vol2/vol2_div_ocr.pdf")
    ap.add_argument("--txt", default="vol2/vol2_pag.txt")
    a = ap.parse_args()

    src_pdf, src_txt = _abs(a.pdf), _abs(a.txt)
    for p in (src_pdf, src_txt):
        if not os.path.exists(p):
            sys.exit(f"nao encontrado: {p}")

    if a.tsv:
        for bruta in open(_abs(a.tsv), encoding="utf-8"):
            linha = bruta.split("#", 1)[0].strip()
            if not linha:
                continue
            partes = linha.split()
            if len(partes) < 3:
                sys.exit(f"linha invalida no tsv: {bruta!r}")
            caminho, pi, pf = partes[0], int(partes[1]), int(partes[2])
            if a.only and not caminho.startswith(a.only):
                continue
            um_no(caminho, pi, pf, a.offset, a.raw, src_pdf, src_txt)
    else:
        if not (a.destino and a.pag_ini is not None and a.pag_fim is not None):
            ap.error("dar 'destino pag_ini pag_fim', ou --tsv")
        um_no(a.destino, a.pag_ini, a.pag_fim, a.offset, a.raw, src_pdf, src_txt)


if __name__ == "__main__":
    main()
