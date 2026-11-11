#!/usr/bin/env python3
"""F1b — OCR por pagina: <id>.png -> <id>.txt (+ <id>.tsv, <id>.hocr do tesseract) e paginas.tsv.

    export TESSDATA_PREFIX=$PWD/tessdata
    python3 tools/ocr_paginas.py vol2/paginas [--langs por_best+lat] [--jobs 7]

Para cada pagina do manifesto que tenha PNG e ainda nao tenha .txt:
  * roda `tesseract -l por_best+lat --psm 1 txt tsv hocr` (1 thread por processo);
  * <id>.txt  = texto com a correcao w->u do projeto (tools/corrige_w.py), VERSIONADO;
  * <id>.tsv / <id>.hocr = saida bruta do tesseract com coordenadas e confianca (git-ignored).
Depois (re)escreve paginas.tsv, uma linha por pagina com texto: palavras, confianca media,
palavras < 60, cabecalho lido e se o numero lido no cabecalho confere com o do manifesto
(so como checagem, docs/02).  Idempotente; --refaz forca o reprocessamento.
"""
import argparse, concurrent.futures as cf, csv, os, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corrige_w import corrige_w  # noqa: E402


def acha_tessdata():
    if os.environ.get("TESSDATA_PREFIX"):
        return os.environ["TESSDATA_PREFIX"]
    raiz = Path(__file__).resolve().parent.parent
    for cand in (raiz / "tessdata", *[p / "tessdata" for p in raiz.parents]):
        if (cand / "lat.traineddata").exists():
            return str(cand)
    return None


def ocr_um(args):
    png, langs, psm, tessdata = args
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    if tessdata:
        env["TESSDATA_PREFIX"] = tessdata
    base = png.with_suffix("")
    r = subprocess.run(["tesseract", str(png), str(base), "-l", langs, "--psm", str(psm),
                        "txt", "tsv", "hocr"], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        return png.stem, f"tesseract falhou: {r.stderr.strip()[-200:]}"
    bruto = base.with_suffix(".txt")
    bruto.write_text(corrige_w(bruto.read_text(encoding="utf-8")), encoding="utf-8")
    return png.stem, None


def estatisticas(pasta, pid):
    """palavras, conf. media, palavras<60 a partir do tsv do tesseract."""
    n = baixas = 0
    soma = 0.0
    tsv = pasta / f"{pid}.tsv"
    if tsv.exists():
        with open(tsv, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                if row.get("level") != "5" or not (row.get("text") or "").strip():
                    continue
                c = float(row["conf"])
                n += 1
                soma += c
                baixas += c < 60
    return n, (soma / n if n else 0.0), baixas


def cabecalho(txt):
    for linha in txt.splitlines():
        if linha.strip():
            return linha.strip()
    return ""


def numero_lido(cab):
    m = re.match(r"^\W*(\d{1,4})\b", cab) or re.search(r"\b(\d{1,4})\W*$", cab)
    return m.group(1) if m else ""


def escreve_paginas_tsv(pasta, manifesto):
    out = pasta / "paginas.tsv"
    with open(out, "w", encoding="utf-8") as f:
        f.write("id\timpressa\tfolha\tmetade\tpalavras\tconf_media\tconf_baixa\tlinhas\tnum_cabecalho\tconfere\tcabecalho\n")
        for pid, imp, folha, metade, _ in manifesto:
            txt_p = pasta / f"{pid}.txt"
            if not txt_p.exists():
                continue
            txt = txt_p.read_text(encoding="utf-8")
            n, conf, baixas = estatisticas(pasta, pid)
            cab = cabecalho(txt)
            num = numero_lido(cab)
            confere = "1" if num == str(imp) else "0"
            linhas = sum(1 for l in txt.splitlines() if l.strip())
            f.write(f"{pid}\t{imp}\t{folha}\t{metade}\t{n}\t{conf:.1f}\t{baixas}\t{linhas}\t{num}\t{confere}\t{cab.replace(chr(9), ' ')}\n")
    return out


def le_manifesto(pasta):
    with open(pasta / "manifesto.tsv", encoding="utf-8") as f:
        next(f)
        return [(p[0], int(p[1]), int(p[2]), p[3], int(p[4])) for p in (l.rstrip("\n").split("\t") for l in f)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pasta", help="diretorio com manifesto.tsv e PNGs (ex.: vol2/paginas)")
    ap.add_argument("--langs", default="por_best+lat")
    ap.add_argument("--psm", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--refaz", action="store_true", help="reprocessa mesmo com .txt existente")
    a = ap.parse_args()

    pasta = Path(a.pasta)
    manifesto = le_manifesto(pasta)
    tessdata = acha_tessdata()
    if not tessdata:
        print("aviso: tessdata local nao encontrado; usando o do sistema (sem 'por_best'?)", file=sys.stderr)

    pendentes = [pasta / f"{pid}.png" for pid, *_ in manifesto
                 if (pasta / f"{pid}.png").exists() and (a.refaz or not (pasta / f"{pid}.txt").exists())]
    print(f"{len(pendentes)} paginas a processar ({a.jobs} jobs, {a.langs})", file=sys.stderr)
    erros = []
    if pendentes:
        with cf.ProcessPoolExecutor(a.jobs) as ex:
            futs = [ex.submit(ocr_um, (p, a.langs, a.psm, tessdata)) for p in pendentes]
            for i, fut in enumerate(cf.as_completed(futs), 1):
                pid, erro = fut.result()
                if erro:
                    erros.append((pid, erro))
                    print(f"  {pid}: {erro}", file=sys.stderr)
                if i % 25 == 0 or i == len(futs):
                    print(f"  {i}/{len(futs)}", file=sys.stderr)
    print(escreve_paginas_tsv(pasta, manifesto), file=sys.stderr)
    if erros:
        sys.exit(f"{len(erros)} paginas com erro")


if __name__ == "__main__":
    main()
