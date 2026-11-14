"""Itens do painel «Baixar» de um nó do sumário (a mesma forma de `views_publico.menu_baixar`)."""
from django import template
from django.urls import reverse

from .. import exportacao

register = template.Library()

_FORMATOS = (("xml", "TEI XML"), ("txt", "Texto puro"), ("html", "HTML"), ("tex", "LaTeX"))


@register.simple_tag
def opcoes_notas_pdf():
    """[(chave, rótulo, papel)] das diagramações de PDF (exportacao.FORMATOS_PDF), na ordem do painel."""
    return [(k, r, p) for k, (_, r, p) in exportacao.FORMATOS_PDF.items()]


@register.simple_tag
def itens_baixar_no(edicao, no, pdf_ok, fac_vols):
    itens = [{"formato": k, "nome": n, "url": reverse("obra:baixar", args=[edicao.slug, no.xml_id, k])}
             for k, n in _FORMATOS]
    if pdf_ok:
        itens.append({"formato": "pdf", "nome": "PDF",
                      "url": reverse("obra:baixar", args=[edicao.slug, no.xml_id, "pdf"])})
    if no.volume_id in fac_vols:
        itens.append({"formato": "fac-simile", "nome": "Fac-símile (PDF do scan)",
                      "url": reverse("obra:baixar_fac_simile", args=[edicao.slug, no.xml_id])})
    return itens
