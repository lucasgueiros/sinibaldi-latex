"""Citação ABNT de um trecho (parte pública, sem login): tela com a citação, a referência e os
downloads em Word (.docx), LaTeX (.tex) e texto. GET sem `trecho` cita o nó inteiro; POST/GET com
`trecho` (selecionado no texto, ver `static/js/citacao.js`) cita a passagem."""
import re

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from . import citacao, leitura
from .models import Edicao, No, Volume

TIPOS = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "tex": "application/x-tex; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}


def montar(request, ed, no, dados):
    """Monta a `citacao.Citacao` para o nó e os dados (trecho, pi, pf, bloco) recebidos."""
    imp = leitura.impressas()
    vol = Volume.objects.filter(pk=no.volume_id).first()
    validas = {v for (vid, _), v in imp.items() if vid == no.volume_id}

    def pagina(chave, padrao):
        v = (dados.get(chave) or "").strip()
        return v if v in validas else padrao

    padrao_i = imp.get((no.volume_id, no.pagina_ini), "") if no.pagina_ini is not None else ""
    padrao_f = imp.get((no.volume_id, no.pagina_fim), padrao_i) if no.pagina_fim is not None else padrao_i
    trecho = citacao.limpar_trecho(dados.get("trecho"))
    pi = pagina("pi", padrao_i)
    pf = pagina("pf", pi if trecho else padrao_f)
    url = request.build_absolute_uri(reverse("obra:no", args=[ed.slug, no.xml_id]))
    bloco = (dados.get("bloco") or "").strip()
    if trecho and bloco.isdigit():
        url += f"#b{bloco}"
    nova = ed.tipo == Edicao.NOVA
    ano = vol.ano if vol else None
    num = vol.numero if vol else None
    return citacao.Citacao(
        ano=ano, volume=num, titulo_volume=vol.titulo if vol else "",
        edicao_txt="" if nova else citacao.EDICAO_VOLUME.get(num or 0, ""),
        nota_edicao="Edição digital adaptada" if nova else "",
        pi=pi, pf=pf, trecho=trecho, url=url, acesso=citacao.data_acesso(timezone.localdate()),
        chave=re.sub(r"[^a-z0-9]", "", f"sinibaldi{ano or ''}v{num or ''}{'n' if nova else ''}"),
    )


def citar(request, slug, xml_id):
    ed = get_object_or_404(Edicao, slug=slug)
    no = get_object_or_404(No, edicao=ed, xml_id=xml_id)
    dados = request.POST if request.method == "POST" else request.GET
    base = {"edicao": ed, "no": no, "titulo_no": leitura.titulo_do_no(no)}
    if len(citacao.limpar_trecho(dados.get("trecho"))) > citacao.LIMITE_TRECHO:
        return render(request, "publico/citar.html", {**base, "limite": citacao.LIMITE_TRECHO, "erro": True}, status=400)
    c = montar(request, ed, no, dados)
    formato = dados.get("formato", "")
    if formato in TIPOS:
        corpo = {"docx": c.docx, "tex": c.latex, "txt": c.texto}[formato]()
        resp = HttpResponse(corpo, content_type=TIPOS[formato])
        resp["Content-Disposition"] = f'attachment; filename="citacao-abnt-{slugify(no.xml_id)[:40]}.{formato}"'
        return resp
    return render(request, "publico/citar.html", {
        **base, "c": c, "referencia_html": c.html_referencia(), "latex": c.latex(),
        "dados": {"trecho": c.trecho, "pi": c.pi, "pf": c.pf, "bloco": (dados.get("bloco") or "").strip()},
    })
