#!/usr/bin/env python3
"""Re-OCR pagina a pagina, com latim, produzindo texto ja etiquetado por pagina impressa.

Nao gera PDF: gera o texto que alimenta a transcricao em LaTeX.  E ~50x mais barato
que refazer o ocrmypdf (que gasta a maior parte do tempo rasterizando e reempacotando
o PDF, nao reconhecendo texto).

    TESSDATA_PREFIX=$PWD/tessdata python3 tools/ocr_paginado.py vol1_div.pdf -o vol1_lat.txt

Requer tessdata/lat.traineddata e tessdata/por_best.traineddata (ver docs/04-ocr-latim.md).
"""
import argparse, concurrent.futures as cf, os, subprocess, sys, tempfile

from corrige_w import corrige_w  # w -> u fora de nomes proprios (ver docs/04)


def ocr_pagina(args):
    # cada tesseract e multithread por padrao; com N processos em paralelo isso
    # oversubscreve os nucleos e fica mais lento.  1 thread por processo.
    os.environ["OMP_THREAD_LIMIT"] = "1"
    pdf, pag, dpi, langs, psm = args
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "p")
        subprocess.run(["pdftoppm", "-singlefile", "-png", "-r", str(dpi),
                        "-f", str(pag), "-l", str(pag), pdf, base],
                       check=True, capture_output=True)
        r = subprocess.run(["tesseract", base + ".png", "-", "-l", langs, "--psm", str(psm)],
                           capture_output=True, text=True)
    return pag, corrige_w(r.stdout)


def romano(n):
    vals = ((1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),
            (50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I"))
    out = []
    for v, s in vals:
        while n >= v:
            out.append(s); n -= v
    return "".join(out)


def rotulo(pag, offset, offset_fm):
    impressa = pag - offset
    return str(impressa) if impressa >= 1 else "fm-" + romano(pag - offset_fm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--langs", default="por_best+lat")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--psm", type=int, default=6)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--offset", type=int, default=15)
    ap.add_argument("--offset-fm", type=int, default=-1)
    ap.add_argument("-f", "--first", type=int, default=1)
    ap.add_argument("-l", "--last", type=int, default=0)
    a = ap.parse_args()

    total = int(subprocess.run(["pdfinfo", a.pdf], capture_output=True, text=True)
                .stdout.split("Pages:")[1].split()[0])
    ultimo = a.last or total
    pags = range(a.first, ultimo + 1)
    tarefas = [(a.pdf, p, a.dpi, a.langs, a.psm) for p in pags]

    feito = {}
    with cf.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for n, (pag, txt) in enumerate(ex.map(ocr_pagina, tarefas), 1):
            feito[pag] = txt
            if n % 25 == 0 or n == len(tarefas):
                print(f"  {n}/{len(tarefas)} paginas", file=sys.stderr, flush=True)

    with open(a.out, "w", encoding="utf-8") as fh:
        for p in pags:
            fh.write(f"<<<PAG {rotulo(p, a.offset, a.offset_fm)} pdf={p}>>>\n")
            fh.write(feito[p].rstrip("\n") + "\n")
    print(f"escrito: {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
