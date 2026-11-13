"""Parte pública: início, sumários, leitura, busca, fac-símile e downloads. Sem login."""
import re

from django.core.paginator import Paginator
from django.db.models import Count, F
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.html import escape

from . import exportacao, leitura, slides
from .models import Bloco, Edicao, No, Pagina, Volume

LIMITE_BLOCOS = 400      # nó com filhos até este tamanho é mostrado inteiro
LIMITE_COMPLETO = 3000   # "ler tudo" só até aqui
POR_PAGINA_BUSCA = 20

FORMATOS = {
    "xml": ("TEI XML", "application/tei+xml; charset=utf-8", "xml"),
    "txt": ("Texto puro", "text/plain; charset=utf-8", "txt"),
    "html": ("HTML", "text/html; charset=utf-8", "html"),
    "tex": ("LaTeX", "application/x-tex; charset=utf-8", "tex"),
    "pdf": ("PDF", "application/pdf", "pdf"),
}


def _edicao(slug):
    return get_object_or_404(Edicao, slug=slug)


def _fabrica_url_fac():
    """Função (volume_id, seq) -> URL do fac-símile, com os números dos volumes lidos uma vez."""
    num = {v.pk: v.numero for v in Volume.objects.all()}
    return lambda volume_id, seq: reverse("obra:facsimile", args=[num.get(volume_id, volume_id), seq])


def _contexto_comum(ed):
    return {"edicao": ed, "outras_edicoes": Edicao.objects.exclude(pk=ed.pk).order_by("slug")}


# ------------------------------------------------------------------------- início
def inicio(request):
    edicoes = list(Edicao.objects.order_by("-slug"))  # "nova" antes de "1916"? ordenamos abaixo
    edicoes.sort(key=lambda e: (e.slug != "1916", e.slug))
    cont = {}
    for ed_id, nivel, c in No.objects.values_list("edicao_id", "nivel").annotate(c=Count("id")):
        cont.setdefault(ed_id, {})[nivel] = c
    for e in edicoes:
        c = cont.get(e.pk, {})
        e.n_partes = c.get("parte", 0)
        e.n_capitulos = c.get("capitulo", 0)
        e.n_teses = c.get("tese", 0)
    return render(request, "publico/inicio.html", {"edicoes": edicoes})


def sobre(request):
    return render(request, "publico/sobre.html", {"edicoes": Edicao.objects.order_by("slug"),
                                                  "formatos": FORMATOS})


# ---------------------------------------------------------------------- sumário
def edicao(request, slug):
    ed = _edicao(slug)
    arv = leitura.Arvore(ed)
    arv.rotular_paginas(leitura.impressas())
    volumes = {v.pk: v for v in Volume.objects.all()}
    if ed.tipo == Edicao.DIPLOMATICA:
        grupos = []
        for r in arv.raizes:
            if not grupos or grupos[-1]["volume"].pk != r.volume_id:
                grupos.append({"volume": volumes[r.volume_id], "raizes": []})
            grupos[-1]["raizes"].append(r)
    else:
        grupos = [{"volume": None, "raizes": arv.raizes}]
    return render(request, "publico/edicao.html", {
        "edicao": ed, "grupos": grupos, "n_nos": len(arv.nos), "nova": ed.tipo == Edicao.NOVA,
        "volumes": list(volumes.values()),
    })


def busca(request, slug):
    ed = _edicao(slug)
    q = (request.GET.get("q") or "").strip()
    pagina = None
    if q:
        achados = leitura.buscar(ed, q)
        arv = leitura.Arvore(ed)
        imp = leitura.impressas()
        arv.rotular_paginas(imp)
        resultados = []
        for pk, ordem, trecho in achados:
            n = arv.cobrindo(ordem)
            if n is None:
                continue
            resultados.append({"no": n, "caminho": arv.caminho(n)[:-1], "trecho": trecho, "bloco": pk})
        pagina = Paginator(resultados, POR_PAGINA_BUSCA).get_page(request.GET.get("page"))
        total = len(resultados)
    else:
        total = 0
    return render(request, "publico/busca.html", {
        "edicao": ed, "q": q, "page_obj": pagina, "total": total,
        "querystring": f"q={q}&" if q else "", "limite_atingido": q and total >= 1000,
    })


# ------------------------------------------------------------------------ leitura
def _url_no(slug, xml_id, bloco=None):
    u = reverse("obra:no", args=[slug, xml_id])
    return f"{u}#b{bloco}" if bloco else u


def no(request, slug, xml_id):
    ed = _edicao(slug)
    arv = leitura.Arvore(ed)
    n = arv.por_id.get(xml_id)
    if n is None:
        raise Http404("Trecho não encontrado.")
    imp = leitura.impressas()
    arv.rotular_paginas(imp)
    total = Bloco.objects.filter(edicao=ed, ordem__gte=n.ordem_ini, ordem__lt=n.ordem_fim).count()
    filhos = n.filhos_lista
    pode_tudo = bool(filhos) and LIMITE_BLOCOS < total <= LIMITE_COMPLETO
    inteiro = (not filhos) or total <= LIMITE_BLOCOS or (request.GET.get("completo") and total <= LIMITE_COMPLETO)
    fim = n.ordem_fim if inteiro else filhos[0].ordem_ini
    blocos = list(Bloco.objects.filter(edicao=ed, ordem__gte=n.ordem_ini, ordem__lt=fim)
                  .exclude(procedencia=Bloco.SUPRIMIDO).annotate(origem_ordem=F("origem__ordem")).order_by("ordem"))
    if n.nivel != "tese" and blocos and blocos[0].tipo == Bloco.MARCO and blocos[0].ordem == n.ordem_ini:
        i = 1  # o rótulo e o título do próprio nó já estão no cabeçalho da página
        while i < len(blocos) and blocos[i].tipo in (Bloco.TITULO, Bloco.CABECALHO):
            i += 1
        blocos = blocos[i:]
    origens = {}
    if ed.tipo == Edicao.NOVA:
        ed16 = Edicao.objects.filter(slug="1916").first()
        if ed16:
            arv16 = leitura.Arvore(ed16)
            for b in blocos:
                if b.origem_id and b.origem_ordem is not None:
                    alvo = arv16.cobrindo(b.origem_ordem)
                    if alvo:
                        origens[b.pk] = _url_no("1916", alvo.xml_id, b.origem_id)
    html, notas = leitura.renderizar(blocos, impressas_=imp, modo="web", url_facsimile=_fabrica_url_fac(), origens=origens,
                                     volumes=({} if ed.tipo == Edicao.NOVA else None))
    ctx = {
        "edicao": ed, "nova": ed.tipo == Edicao.NOVA, "no": n, "caminho": arv.caminho(n)[:-1], "titulo_no": leitura.titulo_do_no(n),
        "html": html, "notas": notas, "filhos": filhos, "inteiro": inteiro, "pode_tudo": pode_tudo,
        "total": total, "anterior": arv.vizinho(n, -1), "proximo": arv.vizinho(n, 1), "pai": n.pai_obj,
        "contribuintes": leitura.contribuintes(ed, n.ordem_ini, n.ordem_fim),
        "baixar": menu_baixar(ed, n, total),
        "slides_url": reverse("obra:slides", args=[ed.slug, n.xml_id]) if slides.disponivel(n, total) else None,
        "volume": Volume.objects.filter(pk=n.volume_id).first(),
    }
    # tese cujo único conteúdo é o próprio texto: nada de sumário de filhos
    return render(request, "publico/no.html", ctx)


def menu_baixar(ed, n, total=None):
    itens = [(k, v[0]) for k, v in FORMATOS.items() if k != "pdf"]
    if exportacao.pdf_disponivel(n, total):
        itens.append(("pdf", FORMATOS["pdf"][0]))
    return [{"formato": k, "nome": nome, "url": reverse("obra:baixar", args=[ed.slug, n.xml_id, k])}
            for k, nome in itens]


# --------------------------------------------------------------------- fac-símile
def facsimile(request, volume, seq):
    vol = get_object_or_404(Volume, numero=volume)
    pag = get_object_or_404(Pagina, volume=vol, seq=seq)
    anterior = Pagina.objects.filter(volume=vol, seq__lt=seq).order_by("-seq").first()
    proxima = Pagina.objects.filter(volume=vol, seq__gt=seq).order_by("seq").first()
    ed16 = Edicao.objects.filter(slug="1916").first()
    no_p, blocos, tem_continuacao = None, [], False
    lado = bool(request.GET.get("lado")) and ed16 is not None
    if ed16:
        primeiro = (Bloco.objects.filter(edicao=ed16, volume=vol, pagina=seq).order_by("ordem").first())
        ref = primeiro
        if ref is None:
            ref = Bloco.objects.filter(edicao=ed16, volume=vol, pagina__lt=seq).order_by("-ordem").first()
        if ref is not None:
            arv = leitura.Arvore(ed16)
            no_p = arv.cobrindo(ref.ordem)
        if lado:
            blocos = list(Bloco.objects.filter(edicao=ed16, volume=vol, pagina=seq).order_by("ordem"))
            continuacao = (Bloco.objects.filter(edicao=ed16, volume=vol, pagina__lt=seq).order_by("-ordem").first())
            tem_continuacao = bool(continuacao and re.search(rf'<pb\b[^>]*\bn="{seq}"', continuacao.xml))
            if tem_continuacao:
                blocos.insert(0, continuacao)
    html, notas = "", []
    if lado:
        html, notas = leitura.renderizar(blocos, impressas_=leitura.impressas(), modo="web",
                                         url_facsimile=_fabrica_url_fac(), prefixo_id="f-")
    return render(request, "publico/facsimile.html", {
        "volume": vol, "pag": pag, "anterior": anterior, "proxima": proxima, "no_pagina": no_p,
        "ed16": ed16, "lado": lado, "html": html, "notas": notas,
        "continua": tem_continuacao,
    })


# ------------------------------------------------------------------------ download
def _resposta_arquivo(corpo, tipo, nome):
    resp = HttpResponse(corpo, content_type=tipo)
    resp["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resp


def baixar(request, slug, xml_id, formato):
    if formato not in FORMATOS:
        raise Http404("Formato desconhecido.")
    ed = _edicao(slug)
    n = get_object_or_404(No.objects.select_related("edicao", "volume"), edicao=ed, xml_id=xml_id)
    rotulo, tipo, ext = FORMATOS[formato]
    nome = exportacao.nome_arquivo(n, ext)
    try:
        if formato == "xml":
            return _resposta_arquivo(exportacao.tei_do_no(n), tipo, nome)
        if formato == "txt":
            return _resposta_arquivo(exportacao.texto_do_no(n), tipo, nome)
        if formato == "html":
            return _resposta_arquivo(exportacao.html_do_no(n), tipo, nome)
        caminho = exportacao.latex_do_no(n) if formato == "tex" else exportacao.pdf_do_no(n)
    except exportacao.ErroExportacao as e:
        return render(request, "publico/erro_baixar.html", {"edicao": ed, "no": n, "erro": str(e),
                                                             "formato": rotulo}, status=503)
    resp = FileResponse(open(caminho, "rb"), content_type=tipo)
    resp["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resp


def baixar_volume(request, slug, numero):
    ed = _edicao(slug)
    vol = get_object_or_404(Volume, numero=numero)
    if not Bloco.objects.filter(edicao=ed, volume=vol).exists():
        raise Http404("Volume sem texto nesta edição.")
    corpo = exportacao.tei_do_volume(ed, vol)
    return _resposta_arquivo(corpo, FORMATOS["xml"][1], f"sinibaldi-{ed.slug}-vol{vol.numero}.xml")
