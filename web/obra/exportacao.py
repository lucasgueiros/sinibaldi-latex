"""Exportações: TEI (nó/volume), texto puro e HTML autônomo."""
import html as _html
import re
from datetime import date

from django.db.models import Q
from lxml import etree

from . import arvore, tei
from .models import Bloco, Pagina, Revisao

_ESP = re.compile(r"[ \t]+")


def _autores(edicao):
    from django.contrib.auth import get_user_model
    U = get_user_model()
    ids = Revisao.objects.filter(edicao=edicao, autor__isnull=False).values_list("autor", flat=True).distinct()
    return [u.get_full_name() or u.get_username() for u in U.objects.filter(pk__in=list(ids)).order_by("username")]


def _arquivos(volume_ids):
    return {(v, s): a for v, s, a in Pagina.objects.filter(volume_id__in=volume_ids)
            .values_list("volume_id", "seq", "arquivo")}


def _revisoes():
    return [(date.today().isoformat(), "Exportado do editor web.")]


def _tei_de_blocos(edicao, blocos, titulo, volume=None):
    blocos = list(blocos)
    arq = {}
    vids = {volume.pk} if volume is not None else {b.volume_id for b in blocos if b.volume_id}
    for (v, s), a in _arquivos(vids).items():
        arq[s] = a
    prefixo = f"v{volume.numero}." if volume is not None else ""
    raiz = tei.aninhar(blocos, titulo=titulo, autores=_autores(edicao), revisoes=_revisoes(),
                       arquivos=arq, remover_prefixo=prefixo)
    return tei.serializar_tei(raiz)


def tei_do_no(no):
    """TEI (str, com declaração XML) de um nó e seus descendentes."""
    blocos = arvore.blocos_do_no(no)
    vol = no.volume
    return _tei_de_blocos(no.edicao, blocos, f"{no.rotulo} {no.titulo}".strip() or no.xml_id, vol)


def tei_do_volume(edicao, volume):
    """TEI de um volume inteiro da edição; os xml:id perdem o prefixo `vN.`."""
    blocos = Bloco.objects.filter(edicao=edicao, volume=volume).order_by("ordem")
    return _tei_de_blocos(edicao, blocos, f"Elementos de Philosophia, vol. {volume.numero} ({volume.titulo})", volume)


# ------------------------------------------------------------------ texto
def _texto_inline(el, notas, impressa):
    partes = []

    def rec(e):
        if e.text:
            partes.append(e.text)
        for c in e:
            if not isinstance(c.tag, str):
                pass
            elif c.tag == "pb":
                n = int(c.get("n"))
                partes.append(f" [pág. {impressa(n)}] ")
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


def texto_do_no(no):
    """Texto puro do nó: blocos separados por linha em branco, notas no fim,
    `[pág. N]` (página impressa) a cada mudança de página."""
    blocos = list(arvore.blocos_do_no(no))
    mapa = {}
    for v, s, i in Pagina.objects.filter(volume_id__in={b.volume_id for b in blocos if b.volume_id}) \
            .values_list("volume_id", "seq", "impressa"):
        mapa[(v, s)] = i
    saida, notas = [], []
    atual = None
    for b in blocos:
        def impressa(n, _v=b.volume_id):
            return mapa.get((_v, n)) or str(n)

        el = etree.fromstring(b.xml.encode("utf-8"))
        if b.tipo == Bloco.CABECALHO:
            continue
        if b.pagina is not None and b.pagina != atual:
            saida.append(f"[pág. {impressa(b.pagina)}]")
            atual = b.pagina
        u = tei.ultima_pagina(el)
        if b.tipo == Bloco.MARCO:
            continue
        if b.tipo == Bloco.SUMARIO:
            saida.append("\n".join(_texto_inline(p, notas, impressa) for p in el))
        else:
            saida.append(_texto_inline(el, notas, impressa))
        if u is not None:
            atual = u
    if notas:
        saida.append("— Notas —")
        for i, n in enumerate(notas, 1):
            corpo = " ".join(_texto_inline(p, [], lambda x: str(x)) for p in n)
            saida.append(f"[{i}] {corpo}")
    return "\n\n".join(s for s in saida if s) + "\n"


# ------------------------------------------------------------------- html
_CSS = """body{font:18px/1.55 Georgia,serif;max-width:42rem;margin:2rem auto;padding:0 1rem;color:#222}
h1{font-size:1.5rem}h3{text-align:center;margin:1.6rem 0 .6rem}p{text-align:justify;margin:.7rem 0}
[data-tei=fw]{display:none}[data-tei=label]{font-weight:bold}[data-tei=hi][data-rend=sc]{font-variant:small-caps}
[data-tei=pb]::before{content:"[" attr(data-n) "]";color:#999;font:.75rem sans-serif;margin:0 .3rem}
[data-tei=argument]{font-size:.92rem;border-left:3px solid #ccc;padding-left:.8rem}
[data-tei=milestone]{margin-top:2rem;border-top:1px solid #ddd}
sup a{text-decoration:none}.notas{font-size:.85rem;border-top:1px solid #ccc;margin-top:2rem}"""


def html_do_no(no):
    """HTML autônomo (str) do nó, com as notas no fim."""
    blocos = list(arvore.blocos_do_no(no))
    corpo = tei.blocos_para_html([b for b in blocos if b.tipo != Bloco.CABECALHO])
    raiz = etree.HTML(f"<div>{corpo}</div>")
    div = raiz.find(".//div")
    notas = div.xpath(".//span[@data-tei='note']")
    lista = []
    for i, n in enumerate(notas, 1):
        sup = etree.Element("sup")
        a = etree.SubElement(sup, "a", href=f"#nota-{i}", id=f"ref-{i}")
        a.text = str(i)
        sup.tail = n.tail
        lista.append((i, n))
        n.getparent().replace(n, sup)
    partes = [etree.tostring(c, method="html", encoding="unicode") for c in div]
    if lista:
        partes.append('<section class="notas"><ol>')
        for i, n in lista:
            txt = "<br>".join("".join(p.itertext()) for p in n.xpath("./span[@data-tei='note-p']"))
            partes.append(f'<li id="nota-{i}">{_html.escape(txt)} <a href="#ref-{i}">↩</a></li>')
        partes.append("</ol></section>")
    titulo = _html.escape(f"{no.rotulo} {no.titulo}".strip() or no.xml_id)
    return (f'<!doctype html><html lang="pt"><head><meta charset="utf-8"><title>{titulo}</title>'
            f"<style>{_CSS}</style></head><body><h1>{titulo}</h1>\n" + "\n".join(partes) + "</body></html>\n")
