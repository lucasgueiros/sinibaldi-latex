"""Conversões entre o TEI aninhado do repositório e a sequência plana de blocos.

* `achatar(tei)`  -> lista de `BlocoDado` (TEI -> blocos)
* `aninhar(blocos)` -> árvore TEI (blocos -> TEI), inverso do anterior
* `fragmento_para_html` / `html_para_fragmento` / `blocos_para_html` /
  `html_para_blocos`: dialeto HTML 1:1 para o editor WYSIWYG e a leitura pública.
"""
import re
from collections import Counter
from dataclasses import dataclass

import lxml.html
from lxml import etree

from . import esquema
from .esquema import (
    ATRIBUTOS, NIVEIS, NIVEIS_ORDEM, TIPO_DA_RAIZ, VALORES, VAZIOS,
    nome_atributo, nome_local, permitidos_em, qname_atributo,
)

NS_TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = qname_atributo("xml:id")
XML_LANG = qname_atributo("xml:lang")


@dataclass
class BlocoDado:
    tipo: str
    xml: str
    pagina: int | None = None


class Relatorio:
    """Contabiliza o que foi desembrulhado/descartado numa importação."""

    def __init__(self):
        self.desembrulhados = Counter()   # elementos fora do vocabulário (texto preservado)
        self.descartados = Counter()      # atributos/valores descartados
        self.avisos = []
        self.paginas = {}                 # seq -> radical da imagem (facs)

    def total_desembrulhados(self):
        return sum(self.desembrulhados.values())

    def __str__(self):
        linhas = []
        if self.desembrulhados:
            linhas.append("Elementos desembrulhados: " + ", ".join(
                f"<{k}> x{v}" for k, v in self.desembrulhados.most_common()))
        else:
            linhas.append("Elementos desembrulhados: nenhum")
        if self.descartados:
            linhas.append("Atributos/valores descartados: " + ", ".join(
                f"{k} x{v}" for k, v in self.descartados.most_common()))
        linhas.extend(f"Aviso: {a}" for a in self.avisos)
        return "\n".join(linhas)


# ---------------------------------------------------------------- saneamento
def _add_texto(dst, txt):
    if not txt:
        return
    if len(dst):
        dst[-1].tail = (dst[-1].tail or "") + txt
    else:
        dst.text = (dst.text or "") + txt


_CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _limpo(txt):
    return _CTRL.sub("", txt) if txt else txt


def _definir_attrs(novo, nome, src, rel, prefixo=""):
    """Copia de `src` (qualquer elemento com .get/.attrib) os atributos permitidos, em ordem canônica."""
    brutos = {nome_atributo(k): v for k, v in src.attrib.items()}
    if nome == "note":
        brutos["place"] = "foot"
    elif nome == "fw":
        brutos["type"] = "header"
    for a in brutos:
        if a not in ATRIBUTOS[nome]:
            rel.descartados[f"@{a} em <{nome}>"] += 1
    for a in ATRIBUTOS[nome]:
        v = brutos.get(a)
        if v is None:
            continue
        v = _limpo(v)
        validos = VALORES.get((nome, a))
        if validos is not None and v not in validos:
            rel.descartados[f"@{a}={v} em <{nome}>"] += 1
            continue
        if not v.strip():
            continue
        if a == "xml:id" and prefixo:
            v = prefixo + v
        novo.set(qname_atributo(a), v)
    return novo


def _valido(nome, el):
    if nome == "hi":
        return el.get("rend") in esquema.REND
    if nome == "milestone":
        return el.get("unit") in NIVEIS
    return True


def _copiar_conteudo(src, dst, ctx, rel, prefixo):
    _add_texto(dst, _limpo(src.text))
    for c in src:
        _copiar_filho(c, dst, ctx, rel, prefixo)
        _add_texto(dst, _limpo(c.tail))


def _copiar_filho(c, dst, ctx, rel, prefixo):
    if not isinstance(c.tag, str):
        return
    nome = nome_local(c.tag)
    if nome in permitidos_em(None, ctx) and _valido(nome, c):
        novo = etree.SubElement(dst, nome)
        _definir_attrs(novo, nome, c, rel, prefixo)
        if nome == "note":
            _normalizar_paragrafos(c, novo, "inline_nota", rel, prefixo)
        elif nome not in VAZIOS:
            _copiar_conteudo(c, novo, ctx, rel, prefixo)
    else:
        rel.desembrulhados[nome] += 1
        _copiar_conteudo(c, dst, ctx, rel, prefixo)


def _normalizar_paragrafos(src, dst, ctx, rel, prefixo):
    """Conteúdo de <note>/<argument>: vira uma sequência de <p> (texto solto é embrulhado)."""
    atual = None

    def garantir():
        nonlocal atual
        if atual is None:
            atual = etree.SubElement(dst, "p")
        return atual

    if src.text and src.text.strip():
        _add_texto(garantir(), _limpo(src.text))
    for c in src:
        if isinstance(c.tag, str) and nome_local(c.tag) == "p":
            atual = None
            p = etree.SubElement(dst, "p")
            _definir_attrs(p, "p", c, rel, prefixo)
            _copiar_conteudo(c, p, ctx, rel, prefixo)
        else:
            _copiar_filho(c, garantir(), ctx, rel, prefixo)
        if c.tail and (c.tail.strip() or atual is not None):
            _add_texto(garantir(), _limpo(c.tail))
    if not len(dst):
        etree.SubElement(dst, "p")


def converter_bloco(el, rel, prefixo=""):
    """Converte um elemento (qualquer namespace) em elemento do dialeto. Retorna (tipo, elemento)."""
    nome = nome_local(el.tag)
    raiz = etree.Element(nome)
    _definir_attrs(raiz, nome, el, rel, prefixo)
    if nome == "milestone":
        pass
    elif nome == "argument":
        _normalizar_paragrafos(el, raiz, "inline", rel, prefixo)
    else:
        _copiar_conteudo(el, raiz, "inline", rel, prefixo)
    return TIPO_DA_RAIZ[nome], raiz


def serializar_fragmento(el):
    return etree.tostring(el, encoding="unicode", with_tail=False)


def ultima_pagina(el):
    """`n` do último <pb> do corpo do fragmento (fora de notas), ou None."""
    ultima = None
    for e in el.iter():
        if isinstance(e.tag, str) and nome_local(e.tag) == "pb":
            if any(nome_local(a.tag) == "note" for a in e.iterancestors()):
                continue
            try:
                ultima = int(e.get("n"))
            except (TypeError, ValueError):
                pass
    return ultima


def paginas_do_fragmento(xml):
    """Todos os `n` de <pb> do fragmento (incluindo os de notas)."""
    out = []
    for m in re.finditer(r'<pb n="(-?\d+)"', xml):
        out.append(int(m.group(1)))
    return out


# ------------------------------------------------------------------- achatar
_NOMES_BLOCO = {"head", "p", "argument", "fw"}


def achatar(tei_volume, numero=None, relatorio=None):
    """TEI (raiz <TEI> ou o <div type="volume">) -> lista de `BlocoDado`.

    `xml:id` ganham o prefixo `v{numero}.` quando `numero` é dado."""
    rel = relatorio if relatorio is not None else Relatorio()
    prefixo = f"v{numero}." if numero is not None else ""
    raiz = tei_volume.getroot() if hasattr(tei_volume, "getroot") else tei_volume
    if nome_local(raiz.tag) == "TEI":
        corpo = raiz.find(f".//{{{NS_TEI}}}body")
        if corpo is None:
            corpo = raiz.find(".//body")
        raiz = corpo
    blocos = []
    estado = {"pagina": None}

    def emitir(tipo, el):
        blocos.append(BlocoDado(tipo, serializar_fragmento(el), estado["pagina"]))
        for pb in el.iter("pb"):
            if pb.get("n") and re.fullmatch(r"-?\d+", pb.get("n")):
                rel.paginas.setdefault(int(pb.get("n")), re.sub(r"\.\w+$", "", (pb.get("facs") or "").rsplit("/", 1)[-1]))
        u = ultima_pagina(el)
        if u is not None:
            estado["pagina"] = u

    def visitar(cont):
        for c in cont:
            if not isinstance(c.tag, str):
                continue
            nome = nome_local(c.tag)
            if nome == "pb":
                try:
                    estado["pagina"] = int(c.get("n"))
                except (TypeError, ValueError):
                    rel.avisos.append(f"<pb> sem n numérico: {c.get('n')!r}")
                    continue
                facs = c.get("facs") or ""
                rel.paginas.setdefault(estado["pagina"], re.sub(r"\.\w+$", "", facs.rsplit("/", 1)[-1]))
            elif nome == "div":
                unidade = c.get("type")
                if unidade in NIVEIS:
                    m = etree.Element("milestone")
                    # reaproveita o mapeamento: unit vem de @type
                    m.set("unit", unidade)
                    if c.get("n"):
                        m.set("n", c.get("n"))
                    if c.get(XML_ID):
                        m.set(XML_ID, prefixo + c.get(XML_ID))
                    emitir("marco", m)
                elif unidade != "volume":
                    rel.desembrulhados[f"div[{unidade}]"] += 1
                visitar(c)
            elif nome in _NOMES_BLOCO:
                tipo, el = converter_bloco(c, rel, prefixo)
                emitir(tipo, el)
            else:
                rel.desembrulhados[nome] += 1
                visitar(c)

    visitar(raiz)
    return blocos


# ------------------------------------------------------------------- aninhar
def _campo(b, nome, padrao=None):
    if isinstance(b, dict):
        return b.get(nome, padrao)
    return getattr(b, nome, padrao)


def _para_tei(el):
    for e in el.iter():
        if isinstance(e.tag, str):
            e.tag = f"{{{NS_TEI}}}{e.tag}"
    return el


def _tei(nome, texto=None, **attrs):
    e = etree.Element(f"{{{NS_TEI}}}{nome}")
    if texto is not None:
        e.text = texto
    for k, v in attrs.items():
        e.set(k, v)
    return e


def cabecalho_tei(titulo, autores=(), revisoes=(), fonte=""):
    h = _tei("teiHeader")
    fd = etree.SubElement(h, f"{{{NS_TEI}}}fileDesc")
    ts = etree.SubElement(fd, f"{{{NS_TEI}}}titleStmt")
    ts.append(_tei("title", titulo))
    ts.append(_tei("author", "Thiago Sinibaldi"))
    for nome in autores:
        rs = etree.SubElement(ts, f"{{{NS_TEI}}}respStmt")
        rs.append(_tei("resp", "revisão e edição"))
        rs.append(_tei("name", nome))
    ps = etree.SubElement(fd, f"{{{NS_TEI}}}publicationStmt")
    ps.append(_tei("p", "Rascunho de trabalho; não publicado."))
    sd = etree.SubElement(fd, f"{{{NS_TEI}}}sourceDesc")
    sd.append(_tei("bibl", fonte or "Thiago Sinibaldi, Elementos de Philosophia. Scan em PDF."))
    rd = etree.SubElement(h, f"{{{NS_TEI}}}revisionDesc")
    for quando, texto in revisoes:
        rd.append(_tei("change", texto, when=str(quando)))
    return h


def aninhar(blocos, *, titulo="Elementos de Philosophia", autores=(), revisoes=(),
            arquivos=None, fonte="", remover_prefixo=""):
    """Sequência plana de blocos -> árvore TEI (elemento <TEI>).

    `blocos`: objetos com `.xml` e `.pagina` (ou dicts). Um marco de nível L fecha as
    divisões abertas de nível >= L e abre `<div type=L>`. `<pb>` é reemitido quando
    `pagina` muda entre blocos. `arquivos`: dict seq -> radical da imagem.
    `remover_prefixo`: p.ex. 'v2.' para tirar o prefixo dos xml:id (exportar um volume)."""
    arquivos = arquivos or {}
    raiz = etree.Element(f"{{{NS_TEI}}}TEI", nsmap={None: NS_TEI})
    raiz.set(XML_LANG, "pt")
    raiz.append(cabecalho_tei(titulo, autores, revisoes, fonte))
    texto = etree.SubElement(raiz, f"{{{NS_TEI}}}text")
    corpo = etree.SubElement(texto, f"{{{NS_TEI}}}body")
    vol = etree.SubElement(corpo, f"{{{NS_TEI}}}div")
    vol.set("type", "volume")
    pilha = []  # [(indice_nivel, div)]
    atual = None

    def contentor():
        return pilha[-1][1] if pilha else vol

    for b in blocos:
        el = etree.fromstring(_campo(b, "xml").encode("utf-8"))
        pagina = _campo(b, "pagina")
        if remover_prefixo:
            for e in el.iter():
                if isinstance(e.tag, str):
                    v = e.get(XML_ID)
                    if v and v.startswith(remover_prefixo):
                        e.set(XML_ID, v[len(remover_prefixo):])
        nome = el.tag
        if nome == "milestone":
            idx = NIVEIS_ORDEM.index(el.get("unit"))
            while pilha and pilha[-1][0] >= idx:
                pilha.pop()
        if pagina is not None and pagina != atual:
            facs = arquivos.get(pagina) or f"{pagina:04d}"
            contentor().append(_tei("pb", n=str(pagina), facs=f"paginas/{facs}.png"))
            atual = pagina
        if nome == "milestone":
            d = etree.SubElement(contentor(), f"{{{NS_TEI}}}div")
            d.set("type", el.get("unit"))
            if el.get("n"):
                d.set("n", el.get("n"))
            if el.get(XML_ID):
                d.set(XML_ID, el.get(XML_ID))
            pilha.append((idx, d))
        else:
            contentor().append(_para_tei(el))
        u = ultima_pagina(el)
        if u is not None:
            atual = u
    return raiz


def serializar_tei(raiz):
    return etree.tostring(raiz, encoding="UTF-8", xml_declaration=True).decode("utf-8")


# ---------------------------------------------------------- fragmento -> HTML
def _h(tag, **attrs):
    e = etree.Element(tag)
    e.set("data-tei", attrs.pop("tei")) if "tei" in attrs else None
    for k, v in attrs.items():
        if v is not None:
            e.set(k.replace("_", "-"), v)
    return e


def _html_elemento(el, ctx):
    """`ctx`: 'raiz' | 'inline' | 'argumento' | 'nota'."""
    nome = el.tag
    g = el.get
    if nome == "milestone":
        h = _h("div", tei="milestone", data_unit=g("unit"), data_n=g("n"), data_xmlid=g(XML_ID))
    elif nome == "head":
        h = _h("h3", tei="head", data_type=g("type"))
    elif nome == "p":
        if ctx == "argumento":
            h = _h("p", data_xmlid=g(XML_ID))
        elif ctx == "nota":
            h = _h("span", tei="note-p")
        else:
            h = _h("p", tei="p", data_type=g("type"), data_xmlid=g(XML_ID))
    elif nome == "argument":
        h = _h("div", tei="argument")
    elif nome == "fw":
        h = _h("p", tei="fw") if ctx == "raiz" else _h("span", tei="fw")
    elif nome == "hi":
        rend = g("rend")
        h = _h("i") if rend == "it" else _h("b") if rend == "bold" else _h("span", tei="hi", data_rend=rend)
    elif nome == "label":
        h = _h("span", tei="label")
    elif nome == "foreign":
        h = _h("span", tei="foreign", lang=g(XML_LANG) or "la")
    elif nome == "note":
        h = _h("span", tei="note", data_n=g("n"), data_xmlid=g(XML_ID))
    elif nome == "pb":
        h = _h("span", tei="pb", data_n=g("n"), data_facs=g("facs"), contenteditable="false")
    else:  # não deveria ocorrer em fragmento válido
        h = _h("span", tei=f"desconhecido-{nome}")
    filho_ctx = "argumento" if nome == "argument" else "nota" if nome == "note" else "inline"
    h.text = el.text if nome not in ("argument", "note") else None
    anterior = None
    for c in el:
        if not isinstance(c.tag, str):
            continue
        novo = _html_elemento(c, filho_ctx)
        novo.tail = c.tail if nome not in ("argument", "note") else None
        h.append(novo)
    return h


def fragmento_para_html(xml):
    raiz = etree.fromstring(xml.encode("utf-8"))
    return etree.tostring(_html_elemento(raiz, "raiz"), method="html", encoding="unicode", with_tail=False)


def blocos_para_html(blocos):
    """HTML de uma sequência de blocos; cada elemento de topo leva data-bloco e data-versao."""
    partes = []
    for b in blocos:
        raiz = etree.fromstring(_campo(b, "xml").encode("utf-8"))
        h = _html_elemento(raiz, "raiz")
        pk = _campo(b, "pk", _campo(b, "id"))
        if pk is not None:
            h.set("data-bloco", str(pk))
        versao = _campo(b, "versao")
        if versao is not None:
            h.set("data-versao", str(versao))
        partes.append(etree.tostring(h, method="html", encoding="unicode", with_tail=False))
    return "\n".join(partes)


# ---------------------------------------------------------- HTML -> fragmento
_CABECALHOS_HTML = {"h1", "h2", "h3", "h4", "h5", "h6"}
_PARAGRAFOS_HTML = {"p", "li", "blockquote", "pre", "dd", "dt"}


def _bruto(h):
    """Elemento HTML -> elemento 'bruto' com nomes TEI (desconhecidos mantêm o nome HTML)."""
    tag = h.tag.lower() if isinstance(h.tag, str) else ""
    dt = h.get("data-tei")
    g = h.get
    if dt == "milestone":
        nome, attrs = "milestone", {"unit": g("data-unit"), "n": g("data-n"), XML_ID: g("data-xmlid")}
    elif dt == "head" or tag in _CABECALHOS_HTML:
        nome, attrs = "head", {"type": g("data-type")}
    elif dt == "argument":
        nome, attrs = "argument", {}
    elif dt == "fw":
        nome, attrs = "fw", {}
    elif dt == "p":
        nome, attrs = "p", {"type": g("data-type"), XML_ID: g("data-xmlid")}
    elif dt == "note-p":
        nome, attrs = "p", {}
    elif dt == "note":
        nome, attrs = "note", {"n": g("data-n"), XML_ID: g("data-xmlid")}
    elif dt == "hi":
        nome, attrs = "hi", {"rend": g("data-rend")}
    elif tag in ("i", "em"):
        nome, attrs = "hi", {"rend": "it"}
    elif tag in ("b", "strong"):
        nome, attrs = "hi", {"rend": "bold"}
    elif dt == "label":
        nome, attrs = "label", {}
    elif dt == "foreign":
        nome, attrs = "foreign", {XML_LANG: g("lang") or "la"}
    elif dt == "pb":
        nome, attrs = "pb", {"n": g("data-n"), "facs": g("data-facs")}
    elif tag == "p":
        nome, attrs = "p", {XML_ID: g("data-xmlid")}
    else:
        nome, attrs = tag or "x-desconhecido", {}
    try:
        e = etree.Element(nome)
    except ValueError:
        e = etree.Element("x-desconhecido")
    for k, v in attrs.items():
        if v:
            e.set(k, v)
    e.text = h.text
    for c in h:
        if not isinstance(c.tag, str):
            if c.tail:
                _add_texto(e, c.tail)
            continue
        novo = _bruto(c)
        novo.tail = c.tail
        e.append(novo)
    return e


def _nome_bloco(h):
    """Nome do bloco TEI se `h` é um elemento de nível de bloco, senão None."""
    tag = h.tag.lower() if isinstance(h.tag, str) else ""
    dt = h.get("data-tei")
    if dt in ("milestone", "head", "argument", "p"):
        return dt
    if dt == "fw":
        return "fw" if tag != "span" else None
    if dt:  # span de nota/hi/pb… solto: inline
        return None
    if tag in _CABECALHOS_HTML:
        return "head"
    if tag in _PARAGRAFOS_HTML:
        return "p"
    return None


def _int_ou_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def html_para_blocos(html, relatorio=None):
    """HTML do editor -> [{id|None, versao|None, xml}] (cada bloco canônico; vazios descartados)."""
    rel = relatorio if relatorio is not None else Relatorio()
    html = (html or "").replace("&nbsp;", " ").replace("\xa0", " ")
    if not html.strip():
        return []
    cont = lxml.html.fragment_fromstring(html, create_parent="div")
    saida = []
    pendente = [None]

    def descarregar():
        p = pendente[0]
        pendente[0] = None
        if p is not None and ((p.text or "").strip() or len(p)):
            emitir("p", p, None, None)

    def emitir(nome, bruto, ident, versao):
        bruto.tag = nome
        _tipo, el = converter_bloco(bruto, rel)
        if nome != "milestone" and not len(el) and not (el.text or "").strip():
            return
        saida.append({"id": ident, "versao": versao, "xml": serializar_fragmento(el)})

    def percorrer(c):
        if not isinstance(c.tag, str):
            return
        nome = _nome_bloco(c)
        if nome:
            descarregar()
            emitir(nome, _bruto(c), _int_ou_none(c.get("data-bloco")), _int_ou_none(c.get("data-versao")))
        elif (c.tag.lower() in ("div", "section", "article", "body", "main", "ul", "ol")
              and not c.get("data-tei")):
            descarregar()
            varrer(c)
            descarregar()
        else:  # inline solto: junta num parágrafo
            if pendente[0] is None:
                pendente[0] = etree.Element("p")
            novo = _bruto(c)
            novo.tail = None
            pendente[0].append(novo)

    def varrer(container):
        if container.text and container.text.strip():
            if pendente[0] is None:
                pendente[0] = etree.Element("p")
            _add_texto(pendente[0], container.text)
        for c in container:
            percorrer(c)
            if c.tail and (c.tail.strip() or pendente[0] is not None):
                if pendente[0] is None:
                    pendente[0] = etree.Element("p")
                _add_texto(pendente[0], c.tail)

    varrer(cont)
    descarregar()
    return saida


def html_para_fragmento(html):
    """HTML de UM bloco -> fragmento canônico. Vários blocos: ValueError."""
    blocos = html_para_blocos(html)
    if len(blocos) > 1:
        raise ValueError("O HTML contém mais de um bloco; use html_para_blocos.")
    return blocos[0]["xml"] if blocos else ""
