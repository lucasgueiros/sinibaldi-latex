"""Formatação dos dados de citação: BibTeX das fontes e a referência precisa de cada citação.

Puro: recebe objetos com os atributos de `models.Fonte`/`models.Citacao` (ou `SimpleNamespace`),
devolve texto. A referência sai em segmentos `(texto, itálico)` para cada formato desenhá-los:
`html()`, `latex()`, `texto()`; `tei_bibl()` a escreve como `<bibl>` TEI.

Forma da referência precisa (a que, na nova edição, substitui a de Sinibaldi):

    (Tomás de Aquino, *In Posteriorum Analyticorum*, lib. I, lect. 1; ed. Leonina, t. 1*/2, p. 5;
     trad.: Fulano, p. 12)
"""
from django.utils.html import escape

from .citacao import escapar_bib, escapar_tex

# campo do modelo -> campo BibTeX (biblatex aceita os dois nomes de local/periódico; damos ambos)
_CAMPOS = [
    ("autor", "author"), ("editor", "editor"), ("tradutor", "translator"), ("titulo", "title"),
    ("subtitulo", "subtitle"), ("serie", "series"), ("volume", "volume"), ("edicao", "edition"),
    ("local", "address"), ("local", "location"), ("editora", "publisher"), ("ano", "year"),
    ("paginas", "pages"), ("periodico", "journal"), ("periodico", "journaltitle"), ("idioma", "language"),
    ("isbn", "isbn"), ("doi", "doi"), ("url", "url"), ("nota", "note"),
]


def bibtex(f):
    """Entrada BibTeX/biblatex de uma Fonte."""
    campos = []
    for attr, nome in _CAMPOS:
        v = (getattr(f, attr, "") or "").strip()
        if v:
            campos.append((nome, v))
    maior = (getattr(f, "titulo_maior", "") or "").strip()
    if maior:
        campos.insert(2, ("booktitle" if f.entrada in ("incollection", "inbook") else "maintitle", maior))
    if getattr(f, "abreviatura", ""):
        campos.append(("shorthand", f.abreviatura))
    corpo = ",\n".join(f"  {k} = {{{escapar_bib(v)}}}" for k, v in campos)
    return f"@{f.entrada or 'book'}{{{f.chave},\n{corpo}\n}}"


def bibtex_de(fontes):
    """Arquivo .bib (str) com as fontes dadas, sem repetir chaves."""
    vistas, out = set(), []
    for f in fontes:
        if f is None or f.chave in vistas:
            continue
        vistas.add(f.chave)
        out.append(bibtex(f))
    return "\n\n".join(out) + ("\n" if out else "")


def _nome_curto(nomes):
    """«Torrell, Jean-Pierre and Bataillon, Louis» -> «Torrell, Bataillon»."""
    partes = [n.strip() for n in (nomes or "").split(" and ") if n.strip()]
    return ", ".join(p.split(",")[0].strip() for p in partes)


def curta(f):
    """Rótulo curto de uma fonte: a abreviatura, ou «Editor (ed.), *Título*, ano»."""
    if f.abreviatura:
        return [(f.abreviatura, False)]
    seg = []
    if f.editor:
        seg.append((f"{_nome_curto(f.editor)} (ed.), ", False))
    elif f.tradutor and f.papel == "traducao":
        seg.append((f"{_nome_curto(f.tradutor)} (trad.), ", False))
    elif f.autor:
        seg.append((f"{_nome_curto(f.autor)}, ", False))
    seg.append((f.titulo, True))
    if f.ano:
        seg.append((f", {f.ano}", False))
    return seg


def _paginas(p):
    p = (p or "").strip()
    if not p:
        return ""
    return p if p[:2] in ("p.", "pp") or not p[0].isdigit() else f"p. {p}"


def partes(c):
    """Segmentos `(texto, itálico)` da referência precisa de uma Citacao, sem os parênteses.
    Vazio se não houver nada a dizer além do que Sinibaldi já disse."""
    seg = []
    cabeca = []
    if c.autor_citado:
        cabeca.append((c.autor_citado, False))
    if c.obra_citada:
        if cabeca:
            cabeca.append((", ", False))
        cabeca.append((c.obra_citada, True))
    if c.lugar:
        if cabeca:
            cabeca.append((", ", False))
        cabeca.append((c.lugar, False))
    seg += cabeca
    fonte = getattr(c, "fonte", None)
    if fonte is not None:
        if seg:
            seg.append(("; ", False))
        seg += curta(fonte)
        if fonte.volume and not fonte.abreviatura:
            seg.append((f", t. {fonte.volume}", False))
        pg = _paginas(c.pagina_fonte)
        if pg:
            seg.append((f", {pg}", False))
    trad = getattr(c, "traducao", None)
    if trad is not None:
        if seg:
            seg.append(("; ", False))
        seg.append(("trad.: ", False))
        seg += curta(trad)
        pg = _paginas(c.pagina_traducao)
        if pg:
            seg.append((f", {pg}", False))
    return seg


def html(seg, parenteses=True):
    corpo = "".join(f"<i>{escape(t)}</i>" if it else escape(t) for t, it in seg)
    return f"({corpo})" if parenteses and corpo else corpo


def latex(seg, parenteses=True):
    corpo = "".join(f"\\emph{{{escapar_tex(t)}}}" if it else escapar_tex(t) for t, it in seg)
    return f"({corpo})" if parenteses and corpo else corpo


def texto(seg, parenteses=True):
    corpo = "".join(t for t, _ in seg)
    return f"({corpo})" if parenteses and corpo else corpo


def autocite(c):
    """Chamada biblatex da citação: `\\autocite[5]{chave}` ou `\\autocites[5]{a}[12]{b}` com tradução."""
    pares = [(f, p) for f, p in ((getattr(c, "fonte", None), c.pagina_fonte),
                                 (getattr(c, "traducao", None), c.pagina_traducao)) if f is not None]
    if not pares:
        return ""
    def um(f, p):
        return (f"[{escapar_tex(p)}]" if p else "") + f"{{{f.chave}}}"
    if len(pares) == 1:
        return "\\autocite" + um(*pares[0])
    return "\\autocites" + "".join(um(f, p) for f, p in pares)
