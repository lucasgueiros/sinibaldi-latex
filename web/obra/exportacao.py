"""Exportações: TEI (nó/volume), texto puro, HTML autônomo, LaTeX e PDF.

TEI: documento completo, aninhado, com `teiHeader` (título do trecho, edição, fonte, `respStmt`
com os contribuidores e data de geração). LaTeX: `tools/tei2latex.py` sobre o TEI do nó, embrulhado
num documento autônomo (preâmbulo de `tex/preambulo.tex` embutido). PDF: esse .tex compilado com
`latexmk -lualatex`, com cache em disco em `SINIBALDI_CACHE` (padrão `web/cache/`).
"""
import contextlib
import fcntl
import hashlib
import html as _html
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Max
from lxml import etree

from . import citacoes, leitura, referencias, tei
from .models import Bloco, Pagina, Volume

_ESP = re.compile(r"[ \t]+")
NS = tei.NS_TEI
TITULO_OBRA = "Elementos de Philosophia"
PROJETO = "Academia Leão XIII de Artes e Ciências do Recife"
AVISO_OCR = ("Texto obtido por OCR e ainda em revisão: pode conter erros de leitura, "
             "especialmente nas citações latinas e nas notas de rodapé.")

TEX_TIMEOUT = 20
TEX_TIMEOUT_VOLUME = 300
PDF_TIMEOUT = 120              # base; somam-se PDF_SEGUNDOS_POR_BLOCO por bloco (ver tempo_limite_pdf)
PDF_SEGUNDOS_POR_BLOCO = 0.2
ESPERA_PADRAO = 20             # segundos que a requisição espera antes de mostrar "preparando"
FILA_TTL = 6 * 3600            # pedido na fila há mais que isso (worker parado/perdido): manda de novo
logger = logging.getLogger(__name__)


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
    chaves = set()

    def vistos(bs):   # junta as chaves de citação enquanto `aninhar` consome os blocos
        for b in bs:
            if "<quote" in b.xml:
                chaves.update(citacoes.ocorrencias_xml(b.xml))
            yield b

    raiz = tei.aninhar(vistos(blocos), titulo=titulo, arquivos=arq, remover_prefixo=prefixo)
    antigo = raiz.find(f"{{{NS}}}teiHeader")
    raiz.replace(antigo, _cabecalho(edicao, titulo, autores, volume, paginas, escopo))
    back = _back_citacoes(chaves, prefixo)
    if back is not None:
        raiz.find(f"{{{NS}}}text").append(back)
    return tei.serializar_tei(raiz)


def _id_fonte(chave):
    return "fonte-" + re.sub(r"[^\w.\-]", "_", chave)


def _segmentos_tei(pai, seg):
    """Segmentos (texto, itálico) como conteúdo misto TEI de `pai` (itálico = <hi rend="it">)."""
    for t, it in seg:
        if it:
            _e(pai, "hi", t, rend="it")
        elif len(pai):
            pai[-1].tail = (pai[-1].tail or "") + t
        else:
            pai.text = (pai.text or "") + t


def _back_citacoes(chaves, prefixo=""):
    """`<back>` com as fontes (`listBibl type=fontes`) e os dados de cada citação
    (`listBibl type=citacoes`, um `<bibl corresp>` por citação), ou None se não houver dados.
    `note type=referencia` traz a referência precisa pronta (usada por tools/tei2latex.py)."""
    from .models import Citacao
    cs = list(Citacao.objects.filter(xml_id__in=chaves).select_related("fonte", "traducao").order_by("volume", "pagina"))
    if not cs:
        return None
    back = etree.Element(f"{{{NS}}}back")
    div = _e(back, "div", type="citacoes")
    fontes = {}
    for c in cs:
        for f in (c.fonte, c.traducao):
            if f is not None:
                fontes[f.chave] = f
    if fontes:
        lb = _e(div, "listBibl", type="fontes")
        for f in fontes.values():
            b = _e(lb, "bibl", type=f.papel)
            b.set(tei.XML_ID, _id_fonte(f.chave))
            for attr, nome in (("autor", "author"), ("editor", "editor"), ("tradutor", "editor")):
                for n in [x.strip() for x in (getattr(f, attr) or "").split(" and ") if x.strip()]:
                    el = _e(b, nome, n)
                    if attr == "tradutor":
                        el.set("role", "translator")
            _e(b, "title", f.titulo, level="m" if f.entrada == "book" else "a")
            if f.titulo_maior:
                _e(b, "title", f.titulo_maior, level="m" if f.entrada != "book" else "s")
            for attr, nome in (("local", "pubPlace"), ("editora", "publisher"), ("ano", "date")):
                if getattr(f, attr):
                    _e(b, nome, getattr(f, attr))
            if f.volume:
                _e(b, "biblScope", f.volume, unit="volume")
            _e(b, "idno", f.chave, type="bibtex")
            _e(b, "note", f.bibtex(), type="bibtex")
            if f.abreviatura:
                _e(b, "abbr", f.abreviatura)
            for attr in ("doi", "isbn", "url"):
                if getattr(f, attr):
                    _e(b, "idno", getattr(f, attr), type=attr.upper() if attr != "url" else "URI")
    lc = _e(div, "listBibl", type="citacoes")
    for c in cs:
        alvo = c.xml_id[len(prefixo):] if prefixo and c.xml_id.startswith(prefixo) else c.xml_id
        b = _e(lc, "bibl", type=c.tipo, corresp="#" + alvo, ana=c.estado)
        if c.autor_citado:
            _e(b, "author", c.autor_citado)
        if c.obra_citada:
            _e(b, "title", c.obra_citada)
        if c.lugar:
            _e(b, "citedRange", c.lugar, unit="lugar")
        for papel, f, pag in (("fonte", c.fonte, c.pagina_fonte), ("traducao", c.traducao, c.pagina_traducao)):
            if f is not None:
                _e(b, "ptr", type=papel, target="#" + _id_fonte(f.chave))
                if pag:
                    _e(b, "citedRange", pag, unit="page", type=papel)
        if c.referencia_autor:
            _e(b, "note", c.referencia_autor, type="original")
        seg = referencias.partes(c)
        if seg:
            _segmentos_tei(_e(b, "note", type="referencia"), seg)
        cite = referencias.autocite(c)
        if cite:
            _e(b, "note", cite, type="biblatex")
    return back


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
def _texto_inline(el, notas, impressa, dados=None, nova=False):
    """Texto de um elemento. Citações diretas e menções entre «»; na nova edição (`nova`) com
    `dados` ({xml_id: Citacao}), a referência de Sinibaldi dá lugar à precisa."""
    partes = []
    refs = {}
    if dados:
        for k, c in dados.items():
            seg = referencias.partes(c)
            if seg:
                refs[k] = referencias.texto(seg)
    com_bibl = {(b.get("corresp") or "").lstrip("#") for b in el.iter("bibl")}
    ultimos = {}
    for q in el.iter("quote"):
        ultimos[citacoes.chave(q)] = q

    def rec(e):
        if e.text:
            partes.append(e.text)
        for c in e:
            if not isinstance(c.tag, str):
                pass
            elif c.tag == "pb":
                partes.append(f" [pág. {impressa(int(c.get('n')))}] ")
            elif c.tag == "anchor":
                partes.append(" ∗ ")
            elif c.tag == "fw":
                pass  # cabeçalho corrente que o OCR deixou no meio do parágrafo
            elif c.tag == "note":
                notas.append((c, dados, nova))   # a nota leva os dados de citação do bloco
                partes.append(f"[{len(notas)}]")
            elif c.tag == "quote":
                aspas = c.get("type") != "indireta"
                partes.append("«" if aspas else "")
                rec(c)
                partes.append("»" if aspas else "")
                k = citacoes.chave(c)
                if nova and k in refs and k not in com_bibl and ultimos.get(k) is c:
                    partes.append(" " + refs[k])
            elif c.tag == "bibl" and nova and citacoes.chave(c) in refs:
                partes.append(refs[citacoes.chave(c)])
            else:
                rec(c)
            if c.tail:
                partes.append(c.tail)

    rec(el)
    return _ESP.sub(" ", "".join(partes)).strip()


def _rodape_texto(edicao, autores):
    linhas = [f"Fonte: Thiago Sinibaldi, {TITULO_OBRA}. {edicao.titulo}. {PROJETO}.", AVISO_OCR]
    if autores:
        linhas.append("Contribuíram: " + ", ".join(autores) + ".")
    linhas.append(f"Gerado em {date.today().isoformat()}.")
    return "\n".join(linhas)


def texto_do_no(no):
    """Texto puro do nó: blocos separados por linha em branco, notas no fim,
    `[pág. N]` (página impressa) a cada mudança de página."""
    return _texto_de_blocos(no.edicao, blocos_do_no(no).iterator(chunk_size=500), titulo_do_no(no),
                            leitura.contribuintes(no.edicao, no.ordem_ini, no.ordem_fim))


def texto_do_volume(edicao, volume):
    """Texto puro de um volume inteiro da edição."""
    return _texto_de_blocos(edicao, blocos_do_volume(edicao, volume).order_by("ordem").iterator(chunk_size=500),
                            f"{TITULO_OBRA}, vol. {volume.numero} ({volume.titulo})", leitura.contribuintes(edicao))


def _texto_de_blocos(edicao, blocos, titulo, autores):
    mapa = leitura.impressas()
    saida, notas = [titulo, edicao.titulo + "\n"], []
    cache, nova = leitura.DadosCitacoes(), edicao.tipo == edicao.NOVA
    atual = None
    for b in blocos:
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
        dados = cache.para(b.xml) if "<quote" in b.xml else None
        if b.tipo == Bloco.SUMARIO:
            saida.append("\n".join(_texto_inline(p, notas, impressa, dados, nova) for p in el))
        elif b.tipo == Bloco.GRAVURA:
            cab, det = el.find("head"), el.find("p")
            leg = _texto_inline(cab, notas, impressa, dados, nova) if cab is not None else ""
            saida.append(f"[Gravura: {leg}]" if leg else "[Gravura]")
            if det is not None:
                saida.append(_texto_inline(det, notas, impressa, dados, nova))
        else:
            saida.append(_texto_inline(el, notas, impressa, dados, nova))
        u = tei.ultima_pagina(el)
        if u is not None:
            atual = u
    if notas:
        saida.append("— Notas —")
        for i, n in enumerate(notas, 1):
            n, d, nv = n
            corpo = (" ".join(_texto_inline(p, [], str, d, nv) for p in n) if len(n)
                     else _texto_inline(n, [], str, d, nv))
            saida.append(f"[{i}] {corpo}")
    saida.append("—\n" + _rodape_texto(edicao, autores))
    return "\n\n".join(s for s in saida if s) + "\n"


# ------------------------------------------------------------------------------ HTML
_CSS = """body{font:18px/1.6 Georgia,'EB Garamond',serif;max-width:42rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fffdf7}
h1{font-size:1.5rem;color:#6b1414}h3{text-align:center;margin:1.6rem 0 .6rem;color:#6b1414}p{text-align:justify;margin:.15rem 0;text-indent:1.4em}
p[data-type]{text-indent:0;border-left:3px solid #c9a86a;padding-left:.7rem;margin:.5rem 0}
[data-tei=label]{font-weight:bold}[data-tei=hi][data-rend=sc]{font-variant:small-caps}[data-tei=foreign]{font-style:italic}
[data-tei=anchor]::before{content:"∗";display:block;text-align:center;margin:.5rem 0}
[data-tei=pb]::before{content:"[" attr(data-n) "]";color:#8a6d2b;font:.72rem sans-serif;margin:0 .3rem}
[data-tei=argument]{font-size:.95rem;text-align:justify;margin:1.5rem auto;max-width:36rem}[data-tei=argument]::before{content:"Summario:";font-variant:small-caps;letter-spacing:.08em}[data-tei=argument]>p{display:inline;margin:0;text-indent:0}[data-tei=argument]>p::before{content:" — "}p[data-type=anexo-titulo]{border:0;padding-left:0;text-align:center;font-variant:small-caps;margin:1.2rem 0 .3rem;text-indent:0}p[data-type=indice]{border:0;margin:.2rem 0;padding-left:1.5rem;text-indent:-1.5rem;text-align:left}p[data-type^=indice-]{border:0;margin:.2rem 0;padding-left:0;text-align:left;display:flex;align-items:baseline;gap:.4rem}p[data-type^=indice-]::after{content:"";order:1;flex:1;min-width:1rem;border-bottom:1px dotted #999}p[data-type^=indice-]>[data-tei=label]{order:2;font-weight:normal}p[data-type=indice-parte]{margin-top:1.4rem;font-weight:bold;color:#6b1414}p[data-type=indice-seccao]{margin-top:1rem;padding-left:.8rem;color:#6b1414}p[data-type=indice-capitulo]{margin-top:.5rem;padding-left:1.6rem}p[data-type=indice-artigo]{padding-left:3rem;font-size:.95em}p[data-type=titulo-obra]{border:0;padding-left:0;text-align:center;font-size:1.8rem;letter-spacing:.25em;margin:1.5rem 0;text-indent:0}p[data-type=centro]{border:0;padding-left:0;text-align:center;margin:.4rem 0;text-indent:0}p[data-type=enderecamento]{border:0;padding-left:0;text-align:center;font-variant:small-caps;margin:1.4rem 0 .2rem;text-indent:0}p[data-type=saudacao]{border:0;padding-left:0;text-align:left;margin-top:1rem;text-indent:0}p[data-type=data-local]{border:0;padding-left:0;font-style:italic;margin-top:1rem;text-indent:0}p[data-type=fecho]{border:0;padding-left:0;text-align:right;font-variant:small-caps;margin-top:.8rem;text-indent:0}
[data-tei=milestone]{margin:1.6rem 0;border-top:1px solid #d9c9a3}
q[data-tei=quote]{quotes:"«" "»" "“" "”"}q[data-type=indireta]::before,q[data-type=indireta]::after{content:none}cite[data-tei=bibl]{font-style:normal}
figure[data-tei=figure]{margin:1.2rem 0;text-align:center}figure[data-tei=figure] img{max-width:100%}figure[data-tei=figure] figcaption{font-size:.9rem;margin-top:.3rem}figure[data-tei=figure] [data-parte=detalhes]{font-size:.8rem;text-align:justify;margin:.2rem auto 0;max-width:34rem}
sup a{text-decoration:none;color:#6b1414}.notas{font-size:.85rem;border-top:1px solid #bbb;margin-top:2rem;padding-top:.5rem}
.fonte{font-size:.8rem;color:#666;border-top:1px solid #ddd;margin-top:2rem;padding-top:.6rem}"""


def html_do_no(no):
    """HTML autônomo (str) do nó, com as notas no fim e CSS embutido."""
    return _html_de_blocos(no.edicao, blocos_do_no(no).iterator(chunk_size=500), titulo_do_no(no),
                           leitura.contribuintes(no.edicao, no.ordem_ini, no.ordem_fim))


def html_do_volume(edicao, volume):
    """HTML autônomo de um volume inteiro da edição."""
    return _html_de_blocos(edicao, blocos_do_volume(edicao, volume).order_by("ordem").iterator(chunk_size=500),
                           f"{TITULO_OBRA}, vol. {volume.numero} ({volume.titulo})", leitura.contribuintes(edicao))


def _html_de_blocos(edicao, blocos, titulo, autores):
    corpo, notas = leitura.renderizar(blocos, impressas_=leitura.impressas(), modo="offline",
                                      citacoes=leitura.DadosCitacoes(), nova=edicao.tipo == edicao.NOVA)
    partes = [corpo]
    if notas:
        partes.append('<section class="notas"><h2>Notas</h2><ol>')
        for i, h in notas:
            partes.append(f'<li id="nota-{i}" value="{i}">{h}</li>')
        partes.append("</ol></section>")
    rodape = (f"Fonte: Thiago Sinibaldi, {_html.escape(TITULO_OBRA)}. {_html.escape(edicao.titulo)}. "
              f"{_html.escape(PROJETO)}. {_html.escape(AVISO_OCR)}")
    if autores:
        rodape += " Contribuíram: " + _html.escape(", ".join(autores)) + "."
    titulo = _html.escape(titulo)
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
    bruto = f"{no.edicao.slug}|{no.xml_id}|{no.titulo}|{ag['n']}|{ag['m']}|{ag['v']}|{_versao_citacoes()}"
    return hashlib.sha1(bruto.encode()).hexdigest()[:16]


def pdf_disponivel(no=None, n_blocos=None):
    """PDF via LaTeX: qualquer tamanho (os grandes compilam em segundo plano); basta haver latexmk."""
    return shutil.which("latexmk") is not None


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


@contextlib.contextmanager
def vaga_pdf(timeout):
    """Uma das `SINIBALDI_PDF_SIMULTANEOS` vagas de compilação da máquina (flock em
    `cache/vagas/pdf-N.lock`): vale entre processos — workers, comandos, vários gunicorn.
    Sem vaga em `timeout` segundos, levanta ErroExportacao."""
    n = max(1, int(getattr(settings, "SINIBALDI_PDF_SIMULTANEOS", 2)))
    d = dir_cache() / "vagas"
    d.mkdir(exist_ok=True)
    fim = time.monotonic() + timeout
    while True:
        for i in range(n):
            f = open(d / f"pdf-{i}.lock", "w")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                f.close()
                continue
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
                f.close()
            return
        if time.monotonic() >= fim:
            raise ErroExportacao("O servidor está ocupado gerando outros PDFs. Tente novamente em instantes.")
        time.sleep(0.5)


def _latex(chave, gerar_tei, titulo, timeout=TEX_TIMEOUT, opcoes=(), volume=None):
    """Caminho do .tex autônomo (em cache, nome = `chave`) a partir do TEI de `gerar_tei()`."""
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
            xml.write_text(gerar_tei(), encoding="utf-8")
            try:
                # gravuras: recortadas do scan do volume para o cache (caminho absoluto no .tex)
                extra = ["--dir-gravuras", str(cache / "gravuras-tex")]
                if volume is not None:
                    extra += ["--base", str(Path(settings.SINIBALDI_DADOS) / volume.diretorio)]
                r = subprocess.run([sys.executable, str(script), str(xml), "-o", str(frag), "--puro", *opcoes, *extra],
                                   capture_output=True, text=True, timeout=timeout, cwd=str(_raiz_repo()))
            except subprocess.TimeoutExpired:
                raise ErroExportacao("A conversão para LaTeX demorou demais. Tente um trecho menor.")
            if r.returncode != 0 or not frag.is_file() or not frag.stat().st_size:
                raise ErroExportacao("Não foi possível converter este trecho para LaTeX.")
            tex = _embrulhar(frag.read_text(encoding="utf-8"), titulo)
            parcial = Path(tmp) / "final.tex"
            parcial.write_text(tex, encoding="utf-8")
            os.replace(parcial, alvo)
    return alvo


def latex_do_no(no):
    """Caminho do .tex autônomo do nó (em cache). Levanta ErroExportacao."""
    return _latex(_versao(no), lambda: tei_do_no(no), titulo_do_no(no), opcoes=_opcoes_citacao(no.edicao),
                  volume=no.volume)


def blocos_do_volume(edicao, volume):
    return Bloco.objects.filter(edicao=edicao, volume=volume).exclude(procedencia=Bloco.SUPRIMIDO)


def _versao_volume(edicao, volume):
    ag = blocos_do_volume(edicao, volume).aggregate(n=Count("id"), m=Max("atualizado_em"), v=Max("versao"))
    bruto = f"{edicao.slug}|vol{volume.numero}|{ag['n']}|{ag['m']}|{ag['v']}|{_versao_citacoes()}"
    return "vol-" + hashlib.sha1(bruto.encode()).hexdigest()[:16]


def latex_do_volume(edicao, volume):
    """Caminho do .tex autônomo de um volume inteiro da edição (em cache). Levanta ErroExportacao."""
    return _latex(_versao_volume(edicao, volume), lambda: tei_do_volume(edicao, volume),
                  f"{TITULO_OBRA}, vol. {volume.numero}", timeout=TEX_TIMEOUT_VOLUME, opcoes=_opcoes_citacao(edicao),
                  volume=volume)


def tex_do_volume_em_cache(edicao, volume):
    """Caminho do .tex do volume se já está no cache e em dia (sem gerar nada), ou None."""
    alvo = dir_cache() / f"{_versao_volume(edicao, volume)}.tex"
    return alvo if alvo.is_file() and alvo.stat().st_size else None


def pdf_em_cache(tex, formato=None):
    """PDF já compilado e em dia com o .tex (`formato` = chave de FORMATOS_PDF ou None = A5), ou None."""
    if tex is None:
        return None
    return pdf_pronto_formato(tex, formato) if formato else pdf_pronto(tex)


def pdf_do_volume(edicao, volume, formato=None, limite=None):
    """LaTeX do volume + compilação (no formato pedido). Usa o banco: roda no worker (`tarefas.pdf_volume`)."""
    tex = latex_do_volume(edicao, volume)
    limite = limite or tempo_limite_pdf(blocos_do_volume(edicao, volume).count())
    if formato:
        return compilar_pdf_formato(tex, formato, f"{TITULO_OBRA}, vol. {volume.numero}", limite)
    return compilar_pdf(tex, limite)


def _opcoes_citacao(edicao):
    """Na nova edição, a referência de Sinibaldi dá lugar à precisa (ver `referencias.partes`)."""
    return ("--citacoes", "precisa") if edicao.tipo == edicao.NOVA else ()


def _versao_citacoes():
    """Parte da chave de cache que muda quando qualquer ficha de citação/fonte muda."""
    from .models import Citacao, Fonte
    a = Citacao.objects.aggregate(n=Count("id"), m=Max("atualizado_em"))
    f = Fonte.objects.aggregate(n=Count("id"), m=Max("atualizado_em"))
    return f"{a['n']}|{a['m']}|{f['n']}|{f['m']}"


def tempo_limite_pdf(n_blocos):
    """Tempo de compilação permitido: ~25 s medidos para 584 blocos; folga de 4 a 5 vezes."""
    return PDF_TIMEOUT + int(n_blocos * PDF_SEGUNDOS_POR_BLOCO)


def pdf_pronto(tex):
    """Caminho do PDF já compilado e em dia com o .tex, ou None."""
    pdf = Path(tex).with_suffix(".pdf")
    if pdf.is_file() and pdf.stat().st_size and pdf.stat().st_mtime >= Path(tex).stat().st_mtime:
        return pdf
    return None


def compilar_pdf(tex, timeout=PDF_TIMEOUT):
    """Compila o .tex com latexmk -lualatex (PDF ao lado, em cache). Não usa o banco. Levanta ErroExportacao."""
    tex = Path(tex)
    pdf = tex.with_suffix(".pdf")
    with _Trava(tex.with_suffix(".pdflock")):
        if pdf_pronto(tex):
            return pdf
        with vaga_pdf(timeout):
            with tempfile.TemporaryDirectory(dir=dir_cache(), prefix="pdf-") as tmp:
                job = tex.stem
                try:
                    r = subprocess.run(
                        ["latexmk", "-lualatex", "-interaction=nonstopmode", "-halt-on-error",
                         f"-outdir={tmp}", f"-jobname={job}", str(tex)],
                        capture_output=True, text=True, timeout=timeout, cwd=tmp,
                        env={**os.environ, "max_print_line": "200"})
                except subprocess.TimeoutExpired:
                    raise ErroExportacao("A geração do PDF passou do tempo limite. Baixe o TEI ou o LaTeX.")
                saida = Path(tmp) / f"{job}.pdf"
                if r.returncode != 0 or not saida.is_file() or saida.stat().st_size < 1000:
                    raise ErroExportacao("A compilação do PDF falhou para este trecho (provável erro de leitura "
                                         "do OCR). Baixe o TEI ou o LaTeX.")
                os.replace(saida, pdf)
    return pdf


# Formatos de diagramação do PDF (tex/formatos/formato-<nome>.tex): chave da URL -> (nome do mestre, rótulo, papel).
FORMATOS_PDF = {
    "sem-notas": ("sem-notas", "Sem notas", "livro 160×230 mm"),
    "1col": ("notas-1col", "Notas de rodapé, 1 coluna", "livro 160×230 mm"),
    "2col": ("notas-2col", "Notas de rodapé, 2 colunas", "A4"),
    "corpo": ("notas-corpo", "Notas no corpo do texto", "livro 160×230 mm"),
}
_INICIO_TEXTO = "\n% ---- texto ----\n\\begin{document}\n"


def _fragmento_do_tex(tex):
    """Corpo do .tex autônomo (entre \\begin{document} e \\end{document}), sem o preâmbulo A5."""
    t = Path(tex).read_text(encoding="utf-8")
    i = t.index(_INICIO_TEXTO) + len(_INICIO_TEXTO)
    return t[i:t.rindex("\\end{document}")]


def pdf_pronto_formato(tex, formato):
    pdf = Path(tex).with_suffix(f".{formato}.pdf")
    if pdf.is_file() and pdf.stat().st_size and pdf.stat().st_mtime >= Path(tex).stat().st_mtime:
        return pdf
    return None


def compilar_pdf_formato(tex, formato, titulo, timeout=PDF_TIMEOUT):
    """PDF do .tex autônomo no formato `formato` (chave de FORMATOS_PDF), com a diagramação de
    tex/formatos/ em vez do preâmbulo A5.  Cache ao lado do .tex.  Levanta ErroExportacao."""
    if formato not in FORMATOS_PDF:
        raise ErroExportacao("Formato de PDF desconhecido.")
    mestre = FORMATOS_PDF[formato][0]
    raiz = _raiz_repo()
    if not (raiz / "tex" / "formatos" / f"formato-{mestre}.tex").is_file():
        raise ErroExportacao("Este formato de PDF não está disponível nesta instalação.")
    tex = Path(tex)
    pdf = tex.with_suffix(f".{formato}.pdf")
    with _Trava(tex.with_suffix(f".{formato}.pdflock")):
        if pdf_pronto_formato(tex, formato):
            return pdf
        with vaga_pdf(timeout):
            with tempfile.TemporaryDirectory(dir=dir_cache(), prefix="pdf-") as tmp:
                job = f"{tex.stem}.{formato}"
                frag = Path(tmp) / "frag.tex"
                frag.write_text(_fragmento_do_tex(tex), encoding="utf-8")
                titulo_corrente = re.sub(r"[^\w ·.,-]", "", titulo.lower()) or "elementos de philosophia"
                pretex = f"\\def\\fragmento{{{frag.with_suffix('')}}}\\def\\titulocorrente{{{titulo_corrente}}}"
                try:
                    r = subprocess.run(
                        ["latexmk", "-lualatex", "-interaction=nonstopmode", "-halt-on-error",
                         f"-outdir={tmp}", f"-jobname={job}", f"-usepretex={pretex}",
                         f"tex/formatos/formato-{mestre}.tex"],
                        capture_output=True, text=True, timeout=timeout, cwd=str(raiz),
                        env={**os.environ, "max_print_line": "200"})
                except subprocess.TimeoutExpired:
                    raise ErroExportacao("A geração do PDF passou do tempo limite. Baixe o TEI ou o LaTeX.")
                saida = Path(tmp) / f"{job}.pdf"
                if r.returncode != 0 or not saida.is_file() or saida.stat().st_size < 1000:
                    raise ErroExportacao("A compilação do PDF falhou para este trecho (provável erro de leitura "
                                         "do OCR). Tente outro formato, ou baixe o TEI ou o LaTeX.")
                os.replace(saida, pdf)
    return pdf


def pdf_do_no(no):
    """Caminho do PDF do nó (em cache), compilado na hora. Levanta ErroExportacao."""
    if not pdf_disponivel(no):
        raise ErroExportacao("A geração de PDF não está disponível nesta instalação; baixe o TEI ou o LaTeX.")
    return compilar_pdf(latex_do_no(no), tempo_limite_pdf(blocos_do_no(no).count()))


# ------------------------------------------------------------------- segundo plano
ESTADO_FILA = "ENFILEIRADA"    # estado próprio gravado antes de enviar (o PENDING do Celery é "desconhecida")


def id_tarefa(tarefa, args):
    """Id determinístico da tarefa: o mesmo pedido, de qualquer processo, cai na mesma tarefa."""
    bruto = json.dumps([tarefa.name, list(args)], sort_keys=True, default=str, ensure_ascii=False)
    return "sinibaldi-" + hashlib.sha1(bruto.encode("utf-8")).hexdigest()[:32]


def em_segundo_plano(tarefa, args=(), espera=ESPERA_PADRAO):
    """Pede `tarefa(*args)` ao worker Celery (`obra/tarefas.py`) e espera por ela até `espera` segundos.

    A tarefa devolve ["pronto", caminho] ou ["erro", mensagem] e não usa o banco; os `args` têm de
    ser JSON. O id é derivado de (tarefa, args) e o estado fica no backend de resultados, então
    vários processos web veem o mesmo pedido e não o duplicam. Devolve ("pronto", Path),
    ("preparando", None) ou ("erro", mensagem). Um erro é esquecido quando alguém o lê (o próximo
    pedido tenta de novo); um "pronto" cujo arquivo sumiu do cache é refeito."""
    tid = id_tarefa(tarefa, args)
    if tarefa.app.conf.task_always_eager:      # testes / sem worker: roda aqui, sem passar pelo backend
        return _resultado(tarefa.apply(args, task_id=tid), tid)
    try:
        d = dir_cache() / "pedidos"
        d.mkdir(exist_ok=True)
        with _Trava(d / f"{tid}.lock"):      # ler o estado e enfileirar: um processo por vez, por pedido
            r = tarefa.AsyncResult(tid)
            estado = r.state
            if estado in ("SUCCESS", "FAILURE", "REVOKED"):
                res = _resultado(r, tid)
                if res[0] == "erro" or not res[1].is_file():
                    r.forget()
                if res[0] == "pronto" and not res[1].is_file():
                    estado = "PENDING"
                else:
                    return res
            if estado == "PENDING" or (estado == ESTADO_FILA
                                       and time.time() - ((r.info or {}).get("desde") or 0) > FILA_TTL):
                tarefa.backend.store_result(tid, {"desde": time.time()}, ESTADO_FILA)
                r = tarefa.apply_async(args, task_id=tid)
        if espera > 0 and not r.ready():
            try:
                r.get(timeout=espera, propagate=False, disable_sync_subtasks=False)
            except Exception:  # noqa: BLE001 — TimeoutError: segue "preparando"
                pass
        if not r.ready():
            return ("preparando", None)
        res = _resultado(r, tid)
    except Exception:  # noqa: BLE001 — broker/backend fora do ar
        logger.exception("fila de tarefas indisponível: %s", tid)
        return ("erro", "A fila de geração de arquivos está indisponível no momento. Tente novamente em instantes.")
    if res[0] == "erro":
        with contextlib.suppress(Exception):
            r.forget()
    return res


def _resultado(r, tid):
    if r.successful():
        v = r.result
        if isinstance(v, (list, tuple)) and len(v) >= 2 and v[0] in ("pronto", "erro"):
            return ("pronto", Path(v[1])) if v[0] == "pronto" else ("erro", str(v[1]))
    logger.error("tarefa %s terminou mal: %s %r", tid, r.state, r.result)
    return ("erro", "Falha inesperada ao gerar o arquivo.")


def nome_arquivo(no, extensao):
    partes = ["sinibaldi", no.edicao.slug, leitura.slug_arquivo(no.xml_id.replace('.', '-'), 30)]
    t = leitura.slug_arquivo(no.titulo or "", 48)
    if t:
        partes.append(t)
    return "-".join(partes) + "." + extensao
