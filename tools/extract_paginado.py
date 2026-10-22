#!/usr/bin/env python3
"""Extrai texto de um PDF OCR'd preservando o numero da pagina IMPRESSA.

O numero impresso nao e lido do OCR (os digitos do cabecalho sao a parte menos
confiavel da digitalizacao): e derivado aritmeticamente do indice da pagina no
PDF -> impressa = indice_pdf - OFFSET.  O OCR do cabecalho serve so para
conferencia (--check).

Uso:
    python3 tools/extract_paginado.py vol1_div_ocr.pdf > vol1_pag.txt
    python3 tools/extract_paginado.py vol1.txt --from-txt -f 300 -l 305
    python3 tools/extract_paginado.py vol1.txt --from-txt --check | head -40
"""
import argparse, re, subprocess, sys

from corrige_w import corrige_w  # w -> u fora de nomes proprios (ver docs/04)


def romano(n: int) -> str:
    vals = ((1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),
            (50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I"))
    out = []
    for v, s in vals:
        while n >= v:
            out.append(s); n -= v
    return "".join(out)


def paginas(src: str, from_txt: bool):
    if from_txt:
        texto = open(src, encoding="utf-8", errors="replace").read()
    else:
        texto = subprocess.run(["pdftotext", "-layout", src, "-"],
                               capture_output=True, text=True, check=True).stdout
    blocos = texto.split("\f")
    if blocos and not blocos[-1].strip():
        blocos.pop()          # \f final nao inicia pagina nova
    return blocos


def rotulo(pdf_pag: int, offset: int, offset_fm: int) -> str:
    impressa = pdf_pag - offset
    if impressa < 1:
        # front matter tem numeracao romana propria: pdf 13 = XIV, pdf 15 = XVI
        return "fm-" + romano(pdf_pag - offset_fm)
    return str(impressa)


def cabecalho_ocr(bloco: str):
    linhas = [l for l in bloco.split("\n") if l.strip()]
    if not linhas:
        return None
    nums = re.findall(r"(?<![\d.,])(\d{1,3})(?![\d.,])", linhas[0])
    return int(nums[0]) if nums else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--from-txt", action="store_true",
                    help="src ja e um .txt gerado por pdftotext -layout")
    ap.add_argument("--offset", type=int, default=15,
                    help="pdf_pag - impressa (vol1_div_ocr.pdf: 15)")
    ap.add_argument("--offset-fm", type=int, default=-1,
                    help="idem para o front matter romano (vol1: -1)")
    ap.add_argument("-f", "--first", type=int, default=1, help="1a pagina do PDF")
    ap.add_argument("-l", "--last", type=int, default=0, help="ultima pagina do PDF")
    ap.add_argument("--check", action="store_true",
                    help="so relata divergencia entre numero calculado e OCR")
    ap.add_argument("--corrige-w", action="store_true",
                    help="aplica w->u fora de nomes proprios (OCR com modelo lat)")
    a = ap.parse_args()

    blocos = paginas(a.src, a.from_txt)
    ultimo = a.last or len(blocos)
    div = tot = 0

    for i, bloco in enumerate(blocos, start=1):
        if i < a.first or i > ultimo:
            continue
        rot = rotulo(i, a.offset, a.offset_fm)
        if a.check:
            lido = cabecalho_ocr(bloco)
            if lido is None:
                continue
            tot += 1
            if str(lido) != rot:
                div += 1
                print(f"pdf {i:>3}  calculado {rot:>4}  ocr leu {lido:>4}")
            continue
        print(f"<<<PAG {rot} pdf={i}>>>")
        print(corrige_w(bloco.rstrip("\n")) if a.corrige_w else bloco.rstrip("\n"))

    if a.check:
        print(f"\n{div}/{tot} cabecalhos divergem do calculado "
              f"(esperado: OCR dos digitos e ruim; o calculado e a fonte de verdade)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
