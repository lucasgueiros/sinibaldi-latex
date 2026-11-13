"""Cadastro de citações e fontes (área restrita; login + `obra.change_bloco`).

* `citacoes/` — lista com filtros e edição em lote (autor, obra, fonte, tradução, estado);
* `citacoes/<xml_id>/` — ficha: o trecho no contexto, a página na edição de Sinibaldi (com a
  chamada ABNT e o BibTeX dela), os dados estruturados e a pré-visualização da referência precisa
  que substitui a de Sinibaldi na nova edição;
* `fontes/`, `fontes/nova/`, `fontes/<pk>/` — edições críticas, traduções… (entradas BibTeX);
* `fontes.bib` — o `.bib` de todas as fontes (ou `?usadas=1`, só as ligadas a alguma citação).
"""
import lxml.html
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import citacao as abnt
from . import leitura, referencias, servicos_citacoes, tei
from .forms import CitacaoForm, CitacoesEmLoteForm, FonteForm
from .models import Citacao, Edicao, Fonte, Volume
from .views_edicao import exige_edicao, nome_de, render_area

POR_PAGINA = 50


def _filtrar(request):
    qs = Citacao.objects.select_related("volume", "fonte", "traducao")
    g = request.GET
    if g.get("estado"):
        qs = qs.filter(estado=g["estado"])
    if g.get("fonte") == "com":
        qs = qs.exclude(fonte=None)
    elif g.get("fonte") == "sem":
        qs = qs.filter(fonte=None)
    if g.get("ref") == "com":
        qs = qs.exclude(referencia_autor="")
    elif g.get("ref") == "sem":
        qs = qs.filter(referencia_autor="")
    if g.get("volume", "").isdigit():
        qs = qs.filter(volume__numero=int(g["volume"]))
    if g.get("inativas") != "1":
        qs = qs.filter(ativa=True)
    q = (g.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(texto__icontains=q) | Q(referencia_autor__icontains=q) | Q(autor_citado__icontains=q)
                       | Q(obra_citada__icontains=q) | Q(lugar__icontains=q) | Q(xml_id=q))
    return qs.order_by("volume__numero", "pagina", "xml_id")


@exige_edicao()
def lista(request):
    qs = _filtrar(request)
    pag = Paginator(qs, POR_PAGINA).get_page(request.GET.get("page"))
    imp = leitura.impressas()
    linhas = [{"c": c, "impressa": imp.get((c.volume_id, c.pagina), c.pagina)} for c in pag]
    contagem = dict(Citacao.objects.filter(ativa=True).values_list("estado").annotate(n=Count("id")))
    filtros = request.GET.copy()
    filtros.pop("page", None)
    return render_area(request, "edicao/citacoes.html", {
        "pagina": pag, "linhas": linhas, "total": qs.count(), "estados": Citacao.ESTADOS,
        "contagens": [(v, r, contagem.get(v, 0)) for v, r in Citacao.ESTADOS],
        "f": request.GET, "filtros": filtros.urlencode(), "volumes": Volume.objects.all(),
        "lote": CitacoesEmLoteForm(), "n_fontes": Fonte.objects.count(),
    })


@exige_edicao()
@require_POST
def lote(request):
    volta = request.POST.get("next") or reverse("obra:citacoes")
    if not url_has_allowed_host_and_scheme(volta, {request.get_host()}):
        volta = reverse("obra:citacoes")
    form = CitacoesEmLoteForm(request.POST)
    ids = [i for i in request.POST.getlist("sel") if i]
    if not form.is_valid() or not ids:
        messages.error(request, "Selecione ao menos uma citação e preencha algum campo.")
        return redirect(volta)
    d = form.cleaned_data
    campos = {k: d[k] for k in ("autor_citado", "obra_citada") if d[k]}
    for k in ("fonte", "traducao"):
        if d[k] is not None:
            campos[k] = d[k]
    if d["estado"]:
        campos["estado"] = d["estado"]
    if campos.get("fonte") is not None:
        campos["estado"] = Citacao.REFERENCIADA
    if not campos:
        messages.error(request, "Nenhum campo preenchido: nada foi alterado.")
        return redirect(volta)
    n = Citacao.objects.filter(xml_id__in=ids).update(atualizado_por=request.user, **campos)
    messages.success(request, f"{n} citação(ões) atualizada(s).")
    return redirect(volta)


def _contexto_html(bloco, chave):
    """HTML de leitura do bloco com os segmentos da citação destacados."""
    h = lxml.html.fragment_fromstring(tei.fragmento_para_html(bloco.xml))
    for el in h.xpath('.//*[@data-tei="quote" or @data-tei="bibl"]'):
        k = el.get("data-xmlid") or (el.get("data-corresp") or "").lstrip("#")
        if k == chave:
            el.set("class", (el.get("class", "") + " destaque-citacao").strip())
    for pb in h.xpath('.//*[@data-tei="pb"]'):
        pb.set("data-n", f"scan {pb.get('data-n')}")
    return lxml.html.tostring(h, encoding="unicode")


def _abnt(volume, impressa):
    """`citacao.Citacao` para a página da edição de 1916/17 em que a citação está."""
    if volume is None:
        return None
    return abnt.Citacao(ano=volume.ano, volume=volume.numero, titulo_volume=volume.titulo,
                        edicao_txt=abnt.EDICAO_VOLUME.get(volume.numero, ""), pi=impressa, pf=impressa,
                        chave=f"sinibaldi{volume.ano or ''}v{volume.numero}")


def _vizinha(c, para_frente=True):
    """Próxima (ou anterior) citação ainda a conferir, na ordem do livro."""
    qs = Citacao.objects.filter(ativa=True).exclude(estado=Citacao.REFERENCIADA).exclude(pk=c.pk)
    chave = (c.volume.numero if c.volume_id else 0, c.pagina if c.pagina is not None else -10**6, c.xml_id)
    melhor = None
    for o in qs.select_related("volume").only("xml_id", "pagina", "volume__numero"):
        k = (o.volume.numero if o.volume_id else 0, o.pagina if o.pagina is not None else -10**6, o.xml_id)
        if (k > chave) if para_frente else (k < chave):
            if melhor is None or ((k < melhor[0]) if para_frente else (k > melhor[0])):
                melhor = (k, o)
    return melhor[1] if melhor else None


@exige_edicao()
def editar(request, xml_id):
    c = Citacao.objects.select_related("volume", "fonte", "traducao").filter(xml_id=xml_id).first()
    locais = servicos_citacoes.localizar(xml_id)
    if c is None:
        if not locais:
            raise Http404("Citação não encontrada (o texto foi gravado?).")
        servicos_citacoes.indexar_blocos([l["bloco"] for l in locais])
        c = Citacao.objects.select_related("volume", "fonte", "traducao").get(xml_id=xml_id)
    if request.method == "POST":
        form = CitacaoForm(request.POST, instance=c)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.estado = form.cleaned_data["estado"]
            obj.atualizado_por = request.user
            obj.save()
            messages.success(request, "Ficha gravada.")
            if request.POST.get("seguir"):
                prox = _vizinha(obj)
                if prox:
                    return redirect("obra:citacao_editar", prox.xml_id)
            return redirect("obra:citacao_editar", obj.xml_id)
    else:
        form = CitacaoForm(instance=c)
    arvores = {}
    for l in locais:
        ed = l["edicao"]
        arvores.setdefault(ed.pk, leitura.Arvore(ed))
        no = arvores[ed.pk].cobrindo(l["bloco"].ordem)
        l["url_publico"] = (reverse("obra:no", args=[ed.slug, no.xml_id]) + f"#b{l['bloco'].pk}") if no else None
        if ed.tipo == Edicao.DIPLOMATICA and l["volume"] is not None and l["seq"] is not None:
            l["url_editor"] = reverse("obra:revisar", args=[l["volume"].numero, l["seq"]])
        elif ed.derivada and no:
            l["url_editor"] = reverse("obra:nova_no", args=[ed.slug, no.xml_id])
        if l["volume"] is not None and l["seq"] is not None:
            l["url_scan"] = reverse("obra:facsimile", args=[l["volume"].numero, l["seq"]])
        l["html"] = _contexto_html(l["bloco"], xml_id)
    imp = leitura.impressas()
    impressa = imp.get((c.volume_id, c.pagina), str(c.pagina) if c.pagina is not None else "")
    sinibaldi = _abnt(c.volume, impressa)
    seg = referencias.partes(c)
    return render_area(request, "edicao/citacao.html", {
        "c": c, "form": form, "locais": locais, "impressa": impressa, "sinibaldi": sinibaldi,
        "ref_html": referencias.html(seg), "ref_latex": referencias.latex(seg), "autocite": referencias.autocite(c),
        "bib": referencias.bibtex_de([c.fonte, c.traducao]), "autor": nome_de(c.atualizado_por),
        "anterior": _vizinha(c, False), "proxima": _vizinha(c),
    })


# ------------------------------------------------------------------------- fontes
@exige_edicao()
def fontes(request):
    qs = Fonte.objects.annotate(n=Count("citacoes", distinct=True) + Count("citacoes_traduzidas", distinct=True))
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(titulo__icontains=q) | Q(autor__icontains=q) | Q(chave__icontains=q) | Q(abreviatura__icontains=q))
    return render_area(request, "edicao/fontes.html", {"fontes": qs.order_by("papel", "autor", "titulo"), "q": q})


@exige_edicao()
def fonte(request, pk=None):
    obj = get_object_or_404(Fonte, pk=pk) if pk else None
    volta = request.GET.get("volta") or request.POST.get("volta") or ""
    if volta and not url_has_allowed_host_and_scheme(volta, {request.get_host()}):
        volta = ""
    if request.method == "POST":
        form = FonteForm(request.POST, instance=obj)
        if form.is_valid():
            f = form.save()
            messages.success(request, f"Fonte «{f.chave}» gravada.")
            return redirect(volta or reverse("obra:fonte_editar", args=[f.pk]))
    else:
        inicial = {}
        if obj is None and request.GET.get("papel") in dict(Fonte.PAPEIS):
            inicial["papel"] = request.GET["papel"]
        form = FonteForm(instance=obj, initial=inicial)
    return render_area(request, "edicao/fonte.html", {
        "form": form, "obj": obj, "volta": volta, "bib": obj.bibtex() if obj else "",
        "citacoes": obj.citacoes.order_by("volume", "pagina")[:30] if obj else [],
    })


@exige_edicao()
def fontes_bib(request):
    qs = Fonte.objects.all()
    if request.GET.get("usadas"):
        qs = qs.filter(Q(citacoes__isnull=False) | Q(citacoes_traduzidas__isnull=False)).distinct()
    corpo = referencias.bibtex_de(qs.order_by("chave"))
    resp = HttpResponse(corpo, content_type="application/x-bibtex; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="fontes-sinibaldi.bib"'
    return resp

