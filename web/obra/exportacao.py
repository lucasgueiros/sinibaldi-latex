"""Exportações: TEI (nó/volume), texto puro, HTML autônomo, LaTeX e PDF.

TEI: documento completo, aninhado, com `teiHeader` (título do trecho, edição, fonte, `respStmt`
com os contribuidores e data de geração). LaTeX: `tools/tei2latex.py` sobre o TEI do nó, embrulhado
num documento autônomo (preâmbulo de `tex/preambulo.tex` embutido). PDF: esse .tex compilado com
`latexmk -lualatex`, com cache em disco em `SINIBALDI_CACHE` (padrão `web/cache/`).
"""
import fcntl
import hashlib
import html as _html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Max
from lxml import etree

from . import leitura, tei
from .models import Bloco, Pagina, Volume

_ESP = re.compile(r"[ \t]+")
NS = tei.NS_TEI
TITULO_OBRA = "Elementos de Philosophia"
PROJETO = "Academia Leão XIII de Artes e Ciências do Recife"
AVISO_OCR = ("Texto obtido por OCR e ainda em revisão: pode conter erros de leitura, "
             "especialmente nas citações latinas e nas notas de rodapé.")

TEX_TIMEOUT = 20
PDF_TIMEOUT = 120
PDF_MAX_BLOCOS = 1200          # acima disso o PDF não é oferecido (compilação passaria do limite)
_semaforo_pdf = threading.Semaphore(2)


class ErroExportacao(Exception):
    """Falha amigável (mensagem para o leitor)."""


# ---------------------------------------------------------------------------- blocos
def blocos_do_no(no):
    """Blocos do nó e descendentes, sem os suprimidos."""
    return (Bloco.objects.filter(edicao_id=no.edicao_id, ordem__gte=no.ordem_ini, ordem__lt=no.ordem_fim)
            .exclude(procedencia=Bloco.SUPRIMIDO).order_by("ordem"))


def titulo_do_no(no):
    return leitura.titulo_do_no(no)


# ------------------------------------------------------------------------------ TEI
def _e(pai, nome, texto=None, **attrs):
    el = etree.SubElement(pai, f"{{{NS}}}{nome}")
    if texto is not None:
        el.text = texto
    for k, v in attrs.items():
        el.set(k, v)
    return el


def _cabecalho(edicao, titulo, autores, volume=None, paginas=None, escopo=""):
    """`teiHeader` completo."""
    h = etree.Element(f"{{{NS}}}teiHeader")
    fd = _e(h, "fileDesc")
    ts = _e(fd, "titleStmt")
    _e(ts, "title", titulo)
    _e(ts, "author", "Thiago Sinibaldi")
    for nome in autores:
        rs = _e(ts, "respStmt")
        _e(rs, "resp", "revisão e edição")
        _e(rs, "name", nome)
    es = _e(fd, "editionStmt")
    _e(es, "edition", edicao.titulo)
    ps = _e(fd, "publicationStmt")
    _e(ps, "publisher", PROJETO)
    _e(ps, "date", date.today().isoformat(), when=date.today().isoformat())
    _e(ps, "p", "Exportado do site da edição colaborativa. " + AVISO_OCR)
    sd = _e(fd, "sourceDesc")
    bibl = f"Thiago Sinibaldi, {TITULO_OBRA}"
    if volume is not None:
        bibl += f", vol. {volume.numero} ({volume.titulo})"
        if volume.ano:
            bibl += f", {volume.ano}"
    bibl += ". Scan em PDF; transcrição por OCR em revisão."
    if paginas:
        bibl += f" Página(s) {paginas}."
    _e(sd, "bibl", bibl)
    ed = _e(h, "encodingDesc")
    _e(_e(ed, "projectDesc"), "p", f"{escopo or 'Trecho'} da edição «{edicao.titulo}». {AVISO_OCR}")
    rd = _e(h, "revisionDesc")
    _e(rd, "change", "Gerado pelo site a partir do banco de dados.", when=date.today().isoformat())
    return h


def _tei_de_blocos(edicao, blocos, titulo, volume=None, autores=(), paginas=None, escopo=""):
    arq = {}
    if volume is not None:
        arq = {s: a for s, a in Pagina.objects.filter(volume=volume).values_list("seq", "arquivo")}
    prefixo = f"v{volume.numero}." if volume is not None else ""
    raiz = tei.aninhar(blocos, titulo=titulo, arquivos=arq, remover_prefixo=prefixo)
    antigo = raiz.find(f"{{{NS}}}teiHeader")
    raiz.replace(antigo, _cabecalho(edicao, titulo, autores, volume, paginas, escopo))
    return tei.serializar_tei(raiz)


def _paginas(no, imp):
    if no.pagina_ini is None:
        return None
    a = imp.get((no.volume_id, no.pagina_ini), str(no.pagina_ini))
    z = imp.get((no.volume_id, no.pagina_fim), str(no.pagina_fim)) if no.pagina_fim is not None else a
    return a if a == z else f"{a}–{z}"


def tei_do_no(no):
    """TEI (str, com declaração XML) de um nó e seus descendentes."""
    imp = leitura.impressas()
    autores = leitura.contribuintes(no.edicao, no.ordem_ini, no.ordem_fim)
    return _tei_de_blocos(no.edicao, blocos_do_no(no).iterator(chunk_size=500), titulo_do_no(no), no.volume,
                          autores, _paginas(no, imp), escopo=f"{no.get_nivel_display()}")


def tei_do_volume(edicao, volume):
    """TEI de um volume inteiro da edição; os xml:id perdem o prefixo `vN.`."""
    blocos = (Bloco.objects.filter(edicao=edicao, volume=volume).exclude(procedencia=Bloco.SUPRIMIDO)
              .order_by("ordem").iterator(chunk_size=500))
    return _tei_de_blocos(edicao, blocos, f"{TITULO_OBRA}, vol. {volume.numero} ({volume.titulo})", volume,
                          leitura.contribuintes(edicao), escopo="Volume inteiro")


# ---------------------------------------------------------------------------- texto
def _texto_inline(el, notas, impressa):
    partes = []

    def rec(e):
        if e.text:
            partes.append(e.text)
        for c in e:
            if not isinstance(c.tag, str):
                pass
            elif c.tag == "pb":
                partes.append(f" [pág. {impressa(int(c.get('n')))}] ")
            elif c.tag == "fw":
                pass  # cabeçalho corrente que o OCR deixou no meio do parágrafo
            elif c.tag == "note":
                notas.append(c)
                partes.append(f"[{len(notas)}]")
            else:
                rec(c)
            if c.tail:
                partes.append(c.tail)

    rec(el)
    return _ESP.sub(" ", "".join(partes)).strip()


def _rodape_texto(no):
    autores = leitura.contribuintes(no.edicao, no.ordem_ini, no.ordem_fim)
    linhas = [f"Fonte: Thiago Sinibaldi, {TITULO_OBRA}. {no.edicao.titulo}. {PROJETO}.", AVISO_OCR]
    if autores:
        linhas.append("Contribuíram: " + ", ".join(autores) + ".")
    linhas.append(f"Gerado em {date.today().isoformat()}.")
    return "\n".join(linhas)


def texto_do_no(no):
    """Texto puro do nó: blocos separados por linha em branco, notas no fim,
    `[pág. N]` (página impressa) a cada mudança de página."""
    mapa = leitura.impressas()
    saida, notas = [titulo_do_no(no), no.edicao.titulo + "\n"], []
    atual = None
    for b in blocos_do_no(no).iterator(chunk_size=500):
        if b.tipo == Bloco.CABECALHO or b.tipo == Bloco.MARCO:
            if b.tipo == Bloco.MARCO and b.pagina is not None:
                pass
            continue

        def impressa(n, _v=b.volume_id):
            return mapa.get((_v, n)) or str(n)

        el = etree.fromstring(b.xml.encode("utf-8"))
        if b.pagina is not None and b.pagina != atual:
            saida.append(f"[pág. {impressa(b.pagina)}]")
            atual = b.pagina
        if b.tipo == Bloco.SUMARIO:
            saida.append("\n".join(_texto_inline(p, notas, impressa) for p in el))
        else:
            saida.append(_texto_inline(el, notas, impressa))
        u = tei.ultima_pagina(el)
        if u is not None:
            atual = u
    if notas:
        saida.append("— Notas —")
        for i, n in enumerate(notas, 1):
            corpo = " ".join(_texto_inline(p, [], lambda x: str(x)) for p in n) if len(n) else _texto_inline(n, [], str)
            saida.append(f"[{i}] {corpo}")
    saida.append("—\n" + _rodape_texto(no))
    return "\n\n".join(s for s in saida if s) + "\n"


# ------------------------------------------------------------------------------ HTML
_CSS = """body{font:18px/1.6 Georgia,'EB Garamond',serif;max-width:42rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fffdf7}
h1{font-size:1.5rem;color:#6b1414}h3{text-align:center;margin:1.6rem 0 .6rem;color:#6b1414}p{text-align:justify;margin:.15rem 0;text-indent:1.4em}
p[data-type]{text-indent:0;border-left:3px solid #c9a86a;padding-left:.7rem;margin:.5rem 0}
[data-tei=label]{font-weight:bold}[data-tei=hi][data-rend=sc]{font-variant:small-caps}[data-tei=foreign]{font-style:italic}
[data-tei=pb]::before{content:"[" attr(data-n) "]";color:#8a6d2b;font:.72rem sans-serif;margin:0 .3rem}
[data-tei=argument]{font-size:.95rem;text-align:justify;margin:1.5rem auto;max-width:36rem}[data-tei=argument]::before{content:"Summario:";font-variant:small-caps;letter-spacing:.08em}[data-tei=argument]>p{display:inline;margin:0;text-indent:0}[data-tei=argument]>p::before{content:" — "}p[data-type=anexo-titulo]{border:0;padding-left:0;text-align:center;font-variant:small-caps;margin:1.2rem 0 .3rem;text-indent:0}p[data-type=indice]{border:0;margin:.2rem 0;padding-left:1.5rem;text-indent:-1.5rem;text-align:left}
[data-tei=milestone]{margin:1.6rem 0;border-top:1px solid #d9c9a3}
sup a{text-decoration:none;color:#6b1414}.notas{font-size:.85rem;border-top:1px solid #bbb;margin-top:2rem;padding-top:.5rem}
.fonte{font-size:.8rem;color:#666;border-top:1px solid #ddd;margin-top:2rem;padding-top:.6rem}"""


def html_do_no(no):
    """HTML autônomo (str) do nó, com as notas no fim e CSS embutido."""
    corpo, notas = leitura.renderizar(blocos_do_no(no).iterator(chunk_size=500), impressas_=leitura.impressas(),
                                      modo="offline")
    partes = [corpo]
    if notas:
        partes.append('<section class="notas"><h2>Notas</h2><ol>')
        for i, h in notas:
            partes.append(f'<li id="nota-{i}" value="{i}">{h}</li>')
        partes.append("</ol></section>")
    autores = leitura.contribuintes(no.edicao, no.ordem_ini, no.ordem_fim)
    rodape = (f"Fonte: Thiago Sinibaldi, {_html.escape(TITULO_OBRA)}. {_html.escape(no.edicao.titulo)}. "
              f"{_html.escape(PROJETO)}. {_html.escape(AVISO_OCR)}")
    if autores:
        rodape += " Contribuíram: " + _html.escape(", ".join(autores)) + "."
    titulo = _html.escape(titulo_do_no(no))
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{titulo}</title><style>{_CSS}</style></head><body><h1>{titulo}</h1>\n"
            + "\n".join(partes) + f'\n<p class="fonte">{rodape}</p></body></html>\n')


# ------------------------------------------------------------------- LaTeX / PDF
def _raiz_repo():
    return Path(settings.RAIZ_REPO)


def dir_cache():
    d = Path(os.environ.get("SINIBALDI_CACHE") or Path(settings.SINIBALDI_CACHE))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _versao(no):
    """Chave de invalidação: nó + contagem e última alteração dos blocos."""
    ag = blocos_do_no(no).aggregate(n=Count("id"), m=Max("atualizado_em"), v=Max("versao"))
    bruto = f"{no.edicao.slug}|{no.xml_id}|{no.titulo}|{ag['n']}|{ag['m']}|{ag['v']}"
    return hashlib.sha1(bruto.encode()).hexdigest()[:16]


def pdf_disponivel(no, n_blocos=None):
    """O PDF só é oferecido a nós que compilam bem dentro do limite de tempo."""
    if n_blocos is None:
        n_blocos = blocos_do_no(no).count()
    return n_blocos <= PDF_MAX_BLOCOS and shutil.which("latexmk") is not None


def _preambulo():
    t = (_raiz_repo() / "tex" / "preambulo.tex").read_text(encoding="utf-8")
    return t


def _embrulhar(fragmento, titulo):
    return ("% !TEX program = lualatex\n"
            f"% {titulo} — {TITULO_OBRA}, Thiago Sinibaldi. Gerado pelo site; compile com: lualatex arquivo.tex\n"
            "\\documentclass[11pt,a5paper]{book}\n\\usepackage{fontspec}\n\\usepackage{polyglossia}\n"
            "\\setmainlanguage{portuguese}\n"
            "% ---- preâmbulo do projeto (tex/preambulo.tex) ----\n" + _preambulo() +
            "\n% ---- texto ----\n\\begin{document}\n" + fragmento + "\n\\end{document}\n")


class _Trava:
    def __init__(self, caminho):
        self.caminho = caminho

    def __enter__(self):
        self.f = open(self.caminho, "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def latex_do_no(no):
    """Caminho do .tex autônomo do nó (em cache). Levanta ErroExportacao."""
    chave = _versao(no)
    cache = dir_cache()
    alvo = cache / f"{chave}.tex"
    with _Trava(cache / f"{chave}.lock"):
        if alvo.is_file() and alvo.stat().st_size:
            return alvo
        script = _raiz_repo() / "tools" / "tei2latex.py"
        if not script.is_file():
            raise ErroExportacao("A conversão para LaTeX não está disponível nesta instalação.")
        with tempfile.TemporaryDirectory(dir=cache, prefix="tmp-") as tmp:
            xml, frag = Path(tmp) / "trecho.xml", Path(tmp) / "trecho.frag.tex"
            xml.write_text(tei_do_no(no), encoding="utf-8")
            try:
                r = subprocess.run([sys.executable, str(script), str(xml), "-o", str(frag), "--puro"],
                                   capture_output=True, text=True, timeout=TEX_TIMEOUT, cwd=str(_raiz_repo()))
            except subprocess.TimeoutExpired:
                raise ErroExportacao("A conversão para LaTeX demorou demais. Tente um trecho menor.")
            if r.returncode != 0 or not frag.is_file() or not frag.stat().st_size:
                raise ErroExportacao("Não foi possível converter este trecho para LaTeX.")
            tex = _embrulhar(frag.read_text(encoding="utf-8"), titulo_do_no(no))
            parcial = Path(tmp) / "final.tex"
            parcial.write_text(tex, encoding="utf-8")
            os.replace(parcial, alvo)
    return alvo


def pdf_do_no(no):
    """Caminho do PDF do nó (em cache), compilado com latexmk -lualatex. Levanta ErroExportacao."""
    if not pdf_disponivel(no):
        raise ErroExportacao("Este trecho é grande demais para gerar o PDF na hora; baixe o TEI ou o LaTeX.")
    tex = latex_do_no(no)
    pdf = tex.with_suffix(".pdf")
    with _Trava(tex.with_suffix(".pdflock")):
        if pdf.is_file() and pdf.stat().st_size and pdf.stat().st_mtime >= tex.stat().st_mtime:
            return pdf
        if not _semaforo_pdf.acquire(timeout=PDF_TIMEOUT):
            raise ErroExportacao("O servidor está ocupado gerando outros PDFs. Tente novamente em instantes.")
        try:
            with tempfile.TemporaryDirectory(dir=dir_cache(), prefix="pdf-") as tmp:
                job = tex.stem
                try:
                    r = subprocess.run(
                        ["latexmk", "-lualatex", "-interaction=nonstopmode", "-halt-on-error",
                         f"-outdir={tmp}", f"-jobname={job}", str(tex)],
                        capture_output=True, text=True, timeout=PDF_TIMEOUT, cwd=tmp,
                        env={**os.environ, "max_print_line": "200"})
                except subprocess.TimeoutExpired:
                    raise ErroExportacao("A geração do PDF passou do tempo limite. Baixe o TEI ou o LaTeX.")
                saida = Path(tmp) / f"{job}.pdf"
                if r.returncode != 0 or not saida.is_file() or saida.stat().st_size < 1000:
                    raise ErroExportacao("A compilação do PDF falhou para este trecho (provável erro de leitura "
                                         "do OCR). Baixe o TEI ou o LaTeX.")
                os.replace(saida, pdf)
        finally:
            _semaforo_pdf.release()
    return pdf


def nome_arquivo(no, extensao):
    partes = ["sinibaldi", no.edicao.slug, leitura.slug_arquivo(no.xml_id.replace('.', '-'), 30)]
    t = leitura.slug_arquivo(no.titulo or "", 48)
    if t:
        partes.append(t)
    return "-".join(partes) + "." + extensao
