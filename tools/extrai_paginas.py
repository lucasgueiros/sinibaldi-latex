#!/usr/bin/env python3
"""F1a — PDF 2-up -> uma imagem PNG por pagina do livro + manifesto.tsv.

    python3 tools/extrai_paginas.py vol2/vol2.pdf -o vol2/paginas --offset -1
    python3 tools/extrai_paginas.py vol1.pdf      -o vol1/paginas --offset 15

Cada folha do PDF tem duas paginas do livro (esquerda, direita). A folha e rasterizada
por `pdftoppm` (que aplica /Rotate e junta as faixas de imagem do vol. 1) e cortada ao meio.

Numeracao (docs/02): impressa = pdf_idx - offset, onde pdf_idx = 2*(folha-1) + metade + 1
(o mesmo indice que `mutool poster` dava).  O offset e dado, nao lido do OCR.
Paginas com impressa < 1 (pre-textuais) recebem id `fNNN` (NNN = pdf_idx).

Saidas em --saida: manifesto.tsv (versionado) e <id>.png (git-ignored, regeneravel).
Idempotente: pula PNGs que ja existem.
"""
import argparse, concurrent.futures as cf, os, subprocess, sys, tempfile
from pathlib import Path

from PIL import Image


def n_folhas(pdf):
    out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, check=True).stdout
    for linha in out.splitlines():
        if linha.startswith("Pages:"):
            return int(linha.split()[1])
    sys.exit("pdfinfo nao informou o numero de paginas")


def pagina_id(impressa, pdf_idx):
    return f"{impressa:04d}" if impressa >= 1 else f"f{pdf_idx:03d}"


def manifesto(n, offset):
    linhas = []
    for folha in range(1, n + 1):
        for metade, nome in enumerate(("E", "D")):
            pdf_idx = 2 * (folha - 1) + metade + 1
            impressa = pdf_idx - offset
            linhas.append((pagina_id(impressa, pdf_idx), impressa, folha, nome, pdf_idx))
    return linhas


def corta_folha(args):
    pdf, folha, dpi, destinos = args  # destinos = {'E': Path, 'D': Path} (so os que faltam)
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "f")
        subprocess.run(["pdftoppm", "-singlefile", "-gray", "-png", "-r", str(dpi),
                        "-f", str(folha), "-l", str(folha), pdf, base],
                       check=True, capture_output=True)
        im = Image.open(base + ".png")
        w, h = im.size
        meio = w // 2
        caixas = {"E": (0, 0, meio, h), "D": (meio, 0, w, h)}
        for metade, destino in destinos.items():
            tmp = destino.with_suffix(".tmp.png")
            im.crop(caixas[metade]).save(tmp, dpi=(dpi, dpi))
            tmp.rename(destino)
    return folha


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("-o", "--saida", required=True, help="diretorio de saida (ex.: vol2/paginas)")
    ap.add_argument("--offset", type=int, required=True, help="impressa = pdf_idx - offset")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--primeira", type=int, default=1, help="primeira FOLHA a rasterizar")
    ap.add_argument("--ultima", type=int, default=0, help="ultima FOLHA (0 = ate o fim)")
    a = ap.parse_args()

    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    n = n_folhas(a.pdf)
    linhas = manifesto(n, a.offset)

    # o manifesto cobre sempre o volume inteiro; o intervalo so limita a rasterizacao
    tsv = saida / "manifesto.tsv"
    with open(tsv, "w", encoding="utf-8") as f:
        f.write("id\timpressa\tfolha\tmetade\tpdf_idx\n")
        for l in linhas:
            f.write("\t".join(map(str, l)) + "\n")
    print(f"{tsv}: {len(linhas)} paginas ({n} folhas)", file=sys.stderr)

    ultima = a.ultima or n
    trabalho = {}
    for pid, _imp, folha, metade, _idx in linhas:
        if a.primeira <= folha <= ultima:
            png = saida / f"{pid}.png"
            if not png.exists():
                trabalho.setdefault(folha, {})[metade] = png
    if not trabalho:
        print("nada a fazer: todas as imagens do intervalo ja existem", file=sys.stderr)
        return
    feitas = 0
    with cf.ProcessPoolExecutor(a.jobs) as ex:
        futs = [ex.submit(corta_folha, (a.pdf, f, a.dpi, d)) for f, d in sorted(trabalho.items())]
        for fut in cf.as_completed(futs):
            fut.result()
            feitas += 1
            if feitas % 25 == 0 or feitas == len(futs):
                print(f"  {feitas}/{len(futs)} folhas", file=sys.stderr)


if __name__ == "__main__":
    main()
