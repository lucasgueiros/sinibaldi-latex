#!/usr/bin/env python3
"""F1c — textos por pagina -> primeira versao do TEI XML do volume (mecanica, ainda bruta).

    python3 tools/paginas2tei.py vol2/paginas -o vol2/vol2.xml --titulo "Elementos de Philosophia, vol. 2" --ano 1916

Le manifesto.tsv e <id>.txt (so as paginas que tem texto) e escreve um TEI unico:
  * <pb n="430" xml:id="pb430" facs="paginas/0430.png"/> no inicio de cada pagina (n = pagina impressa
    do manifesto, nao do OCR);
  * cabecalho corrente -> <fw type="header"> (1a linha, se parecer cabecalho);
  * paragrafos = blocos separados por linha em branco; hifenizacao de fim de linha desfeita;
  * blocos que comecam com "(n)" no fim da pagina -> <note place="foot" n="n">.
Estrutura (capitulos, teses), italico, latim e ids definitivos sao das fases seguintes (F2, F4-F7);
este TEI so fixa o esqueleto e a paginacao.  O resultado e validado (bem formado + checagens
de sequencia de <pb>) antes de ser gravado.
"""
import argparse, os, re, sys
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
NOTA = re.compile(r"^\(\s*(\d{1,2})\s*\)\s*")


def le_manifesto(pasta):
    with open(pasta / "manifesto.tsv", encoding="utf-8") as f:
        next(f)
        return [l.rstrip("\n").split("\t") for l in f]


def eh_cabecalho(linha):
    """Cabecalho corrente: curto, com numero de pagina nas pontas ou quase todo em maiusculas."""
    s = linha.strip()
    if not s or len(s) > 90:
        return False
    if re.match(r"^\W*\d{1,4}\W", s) or re.search(r"\W\d{1,4}\W*$", s):
        return True
    letras = [c for c in s if c.isalpha()]
    return len(letras) >= 6 and sum(c.isupper() for c in letras) / len(letras) > 0.7


def desfaz_hifen(linhas):
    """junta 'mo-' + 'vimentos' quando a linha seguinte comeca em minuscula."""
    out = []
    for l in linhas:
        l = l.strip()
        if out and out[-1].endswith("-") and l[:1].islower():
            out[-1] = out[-1][:-1] + l
        else:
            out.append(l)
    return " ".join(out)


def blocos(txt):
    txt = CTRL.sub("", txt).replace("\f", "")
    return [b for b in re.split(r"\n\s*\n", txt) if b.strip()]


def pagina_xml(pid, imp, txt):
    partes = [f'<pb n="{imp}" xml:id="pb{imp}" facs="paginas/{pid}.png"/>']
    bs = blocos(txt)
    if bs:
        linhas0 = [l for l in bs[0].splitlines() if l.strip()]
        if linhas0 and eh_cabecalho(linhas0[0]):
            partes.append(f'<fw type="header">{escape(linhas0[0].strip())}</fw>')
            resto = "\n".join(linhas0[1:])
            bs = ([resto] if resto.strip() else []) + bs[1:]
    notas, usados = [], set()
    for b in bs:
        corpo = desfaz_hifen(b.splitlines())
        m = NOTA.match(corpo)
        if m:
            nid = f"n{imp}-{m.group(1)}"
            while nid in usados:  # OCR repete o numero: sufixo a, b, ...
                nid += "x"
            usados.add(nid)
            notas.append(f'<note place="foot" n="{m.group(1)}" xml:id="{nid}">{escape(corpo[m.end():])}</note>')
        else:
            partes.append(f"<p>{escape(corpo)}</p>")
    return "\n".join(partes + notas)


def valida(raiz, esperadas):
    erros = []
    pbs = [int(pb.get("n")) for pb in raiz.iter(f"{{{TEI}}}pb")]
    if pbs != esperadas:
        erros.append(f"sequencia de <pb> difere do manifesto ({len(pbs)} vs {len(esperadas)})")
    ids = [e.get(f"{{{XML}}}id") for e in raiz.iter() if e.get(f"{{{XML}}}id")]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        erros.append(f"xml:id duplicados: {sorted(dup)[:5]}")
    return erros


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pasta", help="diretorio de paginas (manifesto.tsv + <id>.txt)")
    ap.add_argument("-o", "--saida", required=True)
    ap.add_argument("--titulo", default="Elementos de Philosophia")
    ap.add_argument("--autor", default="Thiago Sinibaldi")
    ap.add_argument("--ano", default="")
    a = ap.parse_args()

    pasta = Path(a.pasta)
    saida = Path(a.saida)
    paginas, esperadas = [], []
    for pid, imp, *_ in le_manifesto(pasta):
        t = pasta / f"{pid}.txt"
        if t.exists():
            esperadas.append(int(imp))
            paginas.append(pagina_xml(pid, int(imp), t.read_text(encoding="utf-8")))
    if not paginas:
        sys.exit("nenhuma pagina com .txt em " + str(pasta))

    # facs relativo ao XML
    rel = Path(os.path.relpath(pasta.resolve(), saida.resolve().parent)).as_posix()
    corpo = "\n".join(paginas).replace('facs="paginas/', f'facs="{rel}/')

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="{TEI}" xml:lang="pt">
<teiHeader>
  <fileDesc>
    <titleStmt>
      <title>{escape(a.titulo)}</title>
      <author>{escape(a.autor)}</author>
      <respStmt><resp>transcrição por OCR (primeira versão, sem revisão)</resp><name>tesseract</name></respStmt>
    </titleStmt>
    <publicationStmt><p>Rascunho de trabalho; não publicado.</p></publicationStmt>
    <sourceDesc><bibl>{escape(a.autor)}, {escape(a.titulo)}{', ' + escape(a.ano) if a.ano else ''}. Scan em PDF.</bibl></sourceDesc>
  </fileDesc>
  <revisionDesc><change when="{date.today().isoformat()}">TEI bruto gerado por tools/paginas2tei.py a partir do OCR por página.</change></revisionDesc>
</teiHeader>
<text><body><div type="volume">
{corpo}
</div></body></text>
</TEI>
"""
    try:
        raiz = etree.fromstring(xml.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        sys.exit(f"XML mal formado: {e}")
    erros = valida(raiz, esperadas)
    if erros:
        sys.exit("validacao falhou: " + "; ".join(erros))
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(xml, encoding="utf-8")
    n_p = len(list(raiz.iter(f"{{{TEI}}}p")))
    n_n = len(list(raiz.iter(f"{{{TEI}}}note")))
    print(f"{saida}: {len(esperadas)} paginas, {n_p} <p>, {n_n} notas", file=sys.stderr)


if __name__ == "__main__":
    main()
