#!/usr/bin/env python3
"""TEI XML -> fragmento LaTeX (o mesmo dialeto de tex/preambulo.tex).

    python3 tools/tei2latex.py vol2/vol2.xml -f 421 -l 442 -o vol2/trecho.tex
    python3 tools/tei2latex.py sinibaldi1916/vol2/02_theodicea/01_existencia-de-deus.xml -o x.tex --puro

Entende dois TEI:

  * o **bruto** de tools/paginas2tei.py: <pb>, <fw type="header">, <p> e <note place="foot">
    solta no fim da pagina.  Cada nota e ligada a sua chamada "(n)" no corpo da *mesma pagina*
    e vira \\footnote{...} no ponto da chamada.  Nota sem chamada correspondente (OCR leu mal o
    numero) e anexada ao fim do ultimo paragrafo da pagina, com aviso no stderr e um comentario
    "% REVER" no .tex.
  * o **estruturado** do plano (tei-base-e-obra-nova.md): <div type="parte|capitulo|artigo|
    secao|tese">, <head>, <argument>, <label>, <hi rend>, <quote>/<cit>, <foreign>, <s>/<seg>,
    <choice>, <note> dentro de <p> (com <pb> dentro da nota), <list>.

Gravura (<figure><graphic url="paginas/NNNN.png#xywh=x,y,l,a" width="60%"/><head>legenda</head></figure>):
a caixa e recortada da imagem da pagina (resolvida contra --base, padrao: a pasta do XML) para
--dir-gravuras (padrao build/gravuras) com Pillow e vira \\gravura{arquivo}{0.60}{legenda}.

Mapeamento (preambulo.tex): <pb n> -> \\pg{n}  (dentro de nota -> \\pgn{n});  <fw> -> comentario;
div tese com <label> + <hi rend="bold"> iniciais -> \\tese{n}{enunciado};  <hi rend="it"> ->
\\emph;  bold -> \\textbf;  sc -> \\textsc;  <quote> em bloco -> ambiente latim.

A grafia nunca e modernizada aqui; --grafia atual so escolhe <reg>/<corr> em vez de <orig>/<sic>
onde o TEI as marcou.  Elementos desconhecidos sao percorridos (texto preservado) e listados
no fim, no stderr.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"


def T(n):
    return f"{{{TEI}}}{n}"


CABECALHO_AVULSO = (
    "% !TEX program = lualatex\n"
    "\\ifdefined\\pg\\else\\IfFileExists{tex/avulso.tex}{\\input{tex/avulso}}"
    "{\\input{../../tex/avulso}}\\fi\n"
)
RODAPE_AVULSO = "\\csname fimavulso\\endcsname\n"

ESCAPES = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%",
    "$": r"\$", "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}", "|": r"\textbar{}", "<": r"\textless{}", ">": r"\textgreater{}",
}
RE_ESC = re.compile("|".join(re.escape(c) for c in ESCAPES))
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")

SECIONAMENTO = {  # div@type -> comando
    "parte": "part", "livro": "part", "seccao": "part", "capitulo": "chapter", "artigo": "section",
    "secao": "subsection", "subsecao": "subsubsection",
    "anexo": "chapter",   # aparato do fim do volume (Synopse, Indice das materias)
}
HI = {"it": r"\emph{%s}", "italic": r"\emph{%s}", "i": r"\emph{%s}",
      "bold": r"\textbf{%s}", "b": r"\textbf{%s}",
      "sc": r"\textsc{%s}", "smallcaps": r"\textsc{%s}",
      "sup": r"\textsuperscript{%s}", "super": r"\textsuperscript{%s}"}
TRANSPARENTES = {"s", "seg", "name", "persName", "placeName", "term", "ref", "ptr", "date",
                 "num", "bibl", "abbr", "unclear", "supplied", "add", "mentioned", "title"}
IGNORADOS = {"milestone", "anchor", "teiHeader", "gap"}
CHAMADA = re.compile(r"\(\s*(\d{1,2})\s*\)")


def esc(s):
    s = CTRL.sub("", s)
    s = RE_ESC.sub(lambda m: ESCAPES[m.group(0)], s)
    s = re.sub(r"\s+[—–]\s+", " --- ", s)       # travessao do original (o .tex a mao usa ---)
    return s.replace("—", "---").replace("–", "--")


def ln(e):
    return etree.QName(e).localname


RE_URL_GRAVURA = re.compile(r"^(?P<img>[^#]+)#xywh=(\d+),(\d+),(\d+),(\d+)$")


def recorta_gravura(base, url, destino_dir):
    """Recorta a caixa `#xywh=` da imagem `base/url` em `destino_dir`; devolve o Path ou None."""
    m = RE_URL_GRAVURA.match(url or "")
    if not m or base is None or destino_dir is None:
        return None
    origem = Path(base) / m.group("img")
    if not origem.is_file():
        return None
    x, y, l, a = (int(v) for v in m.groups()[1:])
    nome = re.sub(r"[^A-Za-z0-9_-]", "_", f"{Path(base).resolve().name}_{origem.stem}_{x}_{y}_{l}_{a}")
    destino = Path(destino_dir) / f"{nome}.png"
    if destino.is_file() and destino.stat().st_mtime >= origem.stat().st_mtime:
        return destino
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(origem) as im:
        x2, y2 = min(x + l, im.width), min(y + a, im.height)
        if x >= x2 or y >= y2:
            return None
        rec = im.crop((x, y, x2, y2))
        if rec.mode not in ("L", "RGB"):
            rec = rec.convert("RGB")
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_name(destino.stem + "-tmp.png")
        dpi = im.info.get("dpi")
        rec.save(tmp, "PNG", optimize=True, **({"dpi": dpi} if dpi else {}))
        tmp.replace(destino)
    return destino


class Conv:
    def __init__(self, grafia="original", de=None, ate=None, base=None, dir_gravuras=None):
        self.base, self.dir_gravuras = base, dir_gravuras
        self.escolhe = ("reg", "corr") if grafia == "atual" else ("orig", "sic")
        self.de, self.ate = de, ate
        self.pagina = None          # n da ultima <pb> vista (impressa, int)
        self.pend_pg = []           # \pg{...} aguardando o proximo paragrafo
        self.notas_pag = {}         # n -> <note> bruta da pagina corrente (so TEI bruto)
        self.desconhecidos = Counter()
        self.avisos = []
        self.contagem = Counter()

    def dentro(self):
        """a posicao atual esta na faixa de paginas pedida?"""
        if self.pagina is None:
            return self.de is None
        return (self.de is None or self.pagina >= self.de) and \
               (self.ate is None or self.pagina <= self.ate)

    def flush_pg(self):
        s = " ".join(self.pend_pg)
        self.pend_pg = []
        return s

    # ---------- inline ----------
    def inline(self, e, em_nota=False):
        """texto + filhos de e -> string LaTeX (sem a cauda de e)."""
        out = [esc(e.text or "")]
        for c in e:
            out.append(self.elem_inline(c, em_nota))
            out.append(esc(c.tail or ""))
        return "".join(out)

    def elem_inline(self, c, em_nota):
        if not isinstance(c.tag, str):          # comentario / PI
            return ""
        n = ln(c)
        if n == "pb":
            if em_nota:
                return rf"\pgn{{{c.get('n', '?')}}}"
            self.avanca_pagina(c)               # <pb> no meio do paragrafo: \pg ali mesmo
            return (" " + self.flush_pg() + " ") if self.dentro() else ""
        if n == "note":
            return self.nota(c)
        if n == "hi":
            rend = (c.get("rend") or "").split()
            fmt = HI.get(rend[0]) if rend else None
            corpo = self.inline(c, em_nota)
            return fmt % corpo if fmt else corpo
        if n in ("foreign", "emph"):
            corpo = self.inline(c, em_nota)
            return rf"\emph{{{corpo}}}" if (n == "emph" or c.get(f"{{{XML}}}lang")) else corpo
        if n == "quote":
            corpo = self.inline(c, em_nota)
            return rf"\emph{{{corpo}}}" if c.get(f"{{{XML}}}lang") == "la" else rf"``{corpo}''"
        if n == "choice":
            for f in c:
                if isinstance(f.tag, str) and ln(f) in self.escolhe:
                    return self.inline(f, em_nota)
            return self.inline(c[0], em_nota) if len(c) else ""
        if n in ("orig", "reg", "sic", "corr", "label"):
            return self.inline(c, em_nota)
        if n == "lb":
            return " "
        if (n == "anchor" and c.get("type") == "asterisco") or (n == "milestone" and c.get("unit") == "asterisco"):
            return r" \asterisco{} "
        if n == "p":                            # paragrafo dentro de nota
            corpo = self.inline(c, em_nota)
            return (r"\par " + corpo) if (c.getprevious() is not None or (c.getparent().text or "").strip()) else corpo
        if n in IGNORADOS or n == "fw":
            return ""
        if n not in TRANSPARENTES:
            self.desconhecidos[n] += 1
        return self.inline(c, em_nota)

    def avanca_pagina(self, pb):
        try:
            self.pagina = int(pb.get("n"))
        except (TypeError, ValueError):
            self.pagina = None
            self.avisos.append(f"<pb n={pb.get('n')!r}> não numérico")
            return
        if self.dentro():
            self.pend_pg.append(rf"\pg{{{self.pagina}}}")

    def nota(self, e):
        self.contagem["notas"] += 1
        return rf"\footnote{{{self.inline(e, em_nota=True).strip()}}}"

    # ---------- blocos ----------
    def figura(self, e):
        """<figure>: \\gravura{arquivo}{fração}{legenda} (recorte do fac-símile)."""
        g = e.find(T("graphic"))
        h = e.find(T("head"))
        leg = self.inline(h).strip() if h is not None else ""
        url = g.get("url") if g is not None else None
        larg = (g.get("width") or "100%") if g is not None else "100%"
        try:
            frac = max(0.01, min(1.0, float(larg.rstrip("%")) / 100))
        except ValueError:
            frac = 1.0
        self.contagem["gravuras"] += 1
        arq = recorta_gravura(self.base, url, self.dir_gravuras)
        if arq is None:
            self.avisos.append(f"p. {self.pagina}: gravura sem imagem ({url!r})")
            return (r"\begin{center}\fbox{\footnotesize gravura indisponível}"
                    + (r"\\ {\small " + leg + "}" if leg else "")
                    + r"\end{center} % REVER: gravura " + esc(url or "sem url"))
        return rf"\gravura{{{arq.as_posix()}}}{{{frac:.2f}}}{{{leg}}}"

    def p(self, e):
        txt = self.inline(e).strip()
        if txt and e.get("type") == "anexo-titulo":     # divisão citada na Synopse/Índice
            return r"\begin{center}\small\textsc{" + txt + r"}\end{center}"
        if txt and e.get("type") == "indice":           # entrada do índice: recuo pendente
            return r"{\small\noindent\hangindent=1.5em " + txt + r"\par}"
        if txt == "*":                          # parágrafo que é só o asterisco do original
            txt = r"\asterisco{}"
        if self.notas_pag and txt:              # TEI bruto: liga "(n)" a nota da pagina
            def sub(m):
                nota = self.notas_pag.pop(m.group(1), None)
                return self.nota(nota) if nota is not None else m.group(0)
            txt = CHAMADA.sub(sub, txt)
        return txt

    def corpo(self, e, saida):
        """percorre os filhos de bloco de e, anexando blocos (strings) a saida."""
        for c in e:
            if not isinstance(c.tag, str):
                continue
            n = ln(c)
            if n == "pb":
                self.notas_orfas(saida)
                self.avanca_pagina(c)
                self.coleta_notas(c)
            elif n == "div":
                self.div(c, saida)              # a faixa pode comecar no meio de um div
            elif not self.dentro():
                continue
            elif n == "fw":
                saida.append("% cabeçalho: " + " ".join((c.text or "").split()))
            elif n == "p":
                t = self.p(c)
                if t:
                    saida.append((self.flush_pg() + " " + t).strip())
                    self.contagem["p"] += 1
            elif (n == "anchor" and c.get("type") == "asterisco") or (n == "milestone" and c.get("unit") == "asterisco"):
                saida.append(r"\asterisco{}")
            elif n == "figure":
                saida.append((self.flush_pg() + "\n" + self.figura(c)).strip())
            elif n in ("cit", "quote"):
                saida.append(self.bloco_citacao(c))
            elif n == "list":
                saida.append(self.lista(c))
            elif n == "argument":                # sumário do capítulo, onde estiver
                saida.append(r"{\small\noindent\textsc{Summario}: " + self.inline_p(c) + r"\par}")
            elif n in ("note", "head", "label") or n in IGNORADOS:
                continue                        # notas brutas: ja ligadas; head: em div()
            else:
                self.desconhecidos[n] += 1
                t = self.inline(c).strip()
                if t:
                    saida.append(t)

    def coleta_notas(self, pb):
        """TEI bruto: <note n=".."> irmas deste <pb> ate o proximo, indexadas por n."""
        self.notas_pag = {}
        for s in pb.itersiblings():
            if not isinstance(s.tag, str):
                continue
            if ln(s) == "pb":
                break
            if ln(s) == "note" and s.get("n"):
                k = s.get("n")
                while k in self.notas_pag:      # OCR repetiu o numero
                    k += "x"
                self.notas_pag[k] = s

    def notas_orfas(self, saida):
        """notas da pagina que acaba sem chamada correspondente no corpo."""
        pend, self.notas_pag = self.notas_pag, {}
        if not self.dentro():
            return
        for k, nota in pend.items():
            self.avisos.append(f"p. {self.pagina}: nota ({k}) sem chamada no corpo")
            marca = f" % REVER: nota ({k}) sem chamada"
            n = self.nota(nota)
            if saida and not saida[-1].startswith("%"):
                saida[-1] += n + marca
            else:
                saida.append(n + marca)

    def bloco_citacao(self, c):
        if ln(c) == "cit":
            txt = " ".join(t for t in (self.inline(f).strip() for f in c if isinstance(f.tag, str)) if t)
            lat = any(q.get(f"{{{XML}}}lang") == "la" for q in c.iter(T("quote")))
        else:
            txt, lat = self.inline(c).strip(), c.get(f"{{{XML}}}lang") == "la"
        env = "latim" if lat else "quote"
        return f"\\begin{{{env}}}\n{txt}\n\\end{{{env}}}"

    def lista(self, c):
        itens = [self.inline(i).strip() for i in c if isinstance(i.tag, str) and ln(i) == "item"]
        return "\\begin{itemize}\n" + "\n".join(f"\\item {i}" for i in itens) + "\n\\end{itemize}"

    def div(self, d, saida):
        tipo = d.get("type") or ""
        xid = d.get(f"{{{XML}}}id")
        if not self.dentro():
            self.corpo(d, saida)                # so para achar o <pb> de entrada na faixa
            return
        if xid and tipo in ("tese", "artigo", "capitulo", "parte", "anexo"):
            saida.append(f"%%>>> {xid}")        # marcador de tools/trecho.py
        if tipo == "tese":
            self.tese(d, saida)
            return
        if tipo in SECIONAMENTO:
            t = self.titulo(d, SECIONAMENTO[tipo])
            if t:
                saida.append(t)
        self.corpo(d, saida)

    def inline_p(self, a):
        """<argument>: um <p> por assunto -> «--- A. --- B.», como no livro."""
        ps = a.findall(T("p"))
        if not ps:
            return self.inline(a).strip()
        itens = [self.inline(p).strip().lstrip("—–- ") for p in ps]
        return " ".join("--- " + i for i in itens if i)

    def titulo(self, d, cmd):
        heads = d.findall(T("head"))
        r = " ".join(self.inline(h).strip() for h in heads if h.get("type") == "rotulo")
        t = " ".join(self.inline(h).strip() for h in heads if h.get("type") != "rotulo")
        if not (r or t):
            return ""
        if r and t:
            arg = rf"{r}\\[0.3em]\large {t}" if cmd in ("chapter", "part") else rf"{r}\\ {t}"
            toc = f"{r} --- {t}"
        else:
            arg = toc = r or t
        s = rf"\{cmd}*{{{arg}}}"
        if cmd in ("chapter", "part", "section"):
            s += f"\n\\addcontentsline{{toc}}{{{cmd}}}{{{toc}}}"
        return s

    def tese(self, d, saida):
        """<div type=tese n=6><p><label>6.</label> <hi rend=bold>enunciado</hi> — corpo</p>..."""
        for i, p in enumerate(d.findall(T("p"))):
            hi = p.find(T("hi"))
            if i == 0 and hi is not None and (hi.get("rend") or "") in ("bold", "b"):
                lab = p.find(T("label"))
                n = ((lab.text if lab is not None else d.get("n")) or "").strip().rstrip(".")
                enun = self.inline(hi).strip()
                resto = etree.Element(T("p"))
                resto.text = (hi.tail or "").lstrip(" \u2014\u2013-")
                resto.extend(list(hi.itersiblings()))
                corpo = self.p(resto).strip()
                saida.append(f"{self.flush_pg()} \\tese{{{n}}}{{{enun}}}\n{corpo}".strip())
                self.contagem["p"] += 1
            else:
                t = self.p(p)
                if t:
                    saida.append((self.flush_pg() + " " + t).strip())
                    self.contagem["p"] += 1
        outros = [c for c in d if isinstance(c.tag, str) and ln(c) != "p"]
        if outros:                              # subdivisoes, citacoes, pb entre paragrafos
            tmp = etree.Element(T("div"))
            tmp.extend(outros)
            self.corpo(tmp, saida)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xml", help="arquivo TEI (bruto ou estruturado)")
    ap.add_argument("-o", "--saida", help="arquivo .tex (padrão: stdout)")
    ap.add_argument("-f", "--de", type=int, help="primeira página impressa")
    ap.add_argument("-l", "--ate", type=int, help="última página impressa")
    ap.add_argument("--grafia", choices=["original", "atual"], default="original",
                    help="original: <orig>/<sic> (padrão); atual: <reg>/<corr>")
    ap.add_argument("--puro", action="store_true",
                    help="sem as linhas de compilação avulsa (para \\input no livro)")
    ap.add_argument("--base", help="pasta contra a qual resolver graphic/@url das gravuras (padrão: a do XML)")
    ap.add_argument("--dir-gravuras", default="build/gravuras",
                    help="onde gravar os recortes das gravuras (padrão: build/gravuras; o .tex cita este caminho)")
    a = ap.parse_args()

    try:
        arv = etree.parse(a.xml, etree.XMLParser(huge_tree=True, resolve_entities=False))
        arv.xinclude()
    except (OSError, etree.XMLSyntaxError, etree.XIncludeError) as e:
        sys.exit(f"{a.xml}: {e}")
    corpo = arv.getroot().find(f".//{T('body')}")
    if corpo is None:
        sys.exit(f"{a.xml}: TEI sem <text><body>")

    c = Conv(a.grafia, a.de, a.ate, base=a.base or Path(a.xml).parent, dir_gravuras=a.dir_gravuras)
    saida = []
    c.corpo(corpo, saida)
    c.notas_orfas(saida)
    if c.pend_pg and c.dentro():
        saida.append(c.flush_pg())

    faixa = f", pp. {a.de or ''}–{a.ate or ''}" if (a.de or a.ate) else ""
    cab = f"% Gerado por tools/tei2latex.py a partir de {Path(a.xml).name}{faixa}. Regenerar, não editar.\n"
    texto = ("" if a.puro else CABECALHO_AVULSO) + cab + "\n" + "\n\n".join(b for b in saida if b) + "\n"
    if not a.puro:
        texto += "\n" + RODAPE_AVULSO
    if a.saida:
        Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
        Path(a.saida).write_text(texto, encoding="utf-8")
    else:
        sys.stdout.write(texto)

    print(f"{c.contagem['p']} parágrafos, {c.contagem['notas']} notas"
          + (f", {c.contagem['gravuras']} gravuras" if c.contagem["gravuras"] else ""), file=sys.stderr)
    for av in c.avisos:
        print("aviso:", av, file=sys.stderr)
    if c.desconhecidos:
        print("elementos sem regra (texto preservado):",
              ", ".join(f"{k}×{v}" for k, v in c.desconhecidos.items()), file=sys.stderr)


if __name__ == "__main__":
    main()
