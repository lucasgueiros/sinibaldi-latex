"""Parte pública: início, sumários, leitura, busca, fac-símile e downloads. Sem login."""
import re

from django.core.paginator import Paginator
from django.db.models import Count, F
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.html import escape

from . import exportacao, fac_simile, leitura, slides
from .models import Bloco, Edicao, No, Pagina, Volume, edicao_visivel_ou_404

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


def _edicao(request, slug):
    """A edição pelo slug; 404 se ela estiver escondida (`publica=False`) e o usuário não for editor."""
    return edicao_visivel_ou_404(slug, request.user)


def _fabrica_url_fac(volumes=None):
    """Função (volume_id, seq) -> URL do fac-símile, com os números dos volumes lidos uma vez."""
    if volumes is None:
        volumes = {v.pk: v for v in Volume.objects.all()}
    num = {pk: v.numero for pk, v in volumes.items()}
    return lambda volume_id, seq: reverse("obra:facsimile", args=[num.get(volume_id, volume_id), seq])


# ------------------------------------------------------------------------- início
def inicio(request):
    edicoes = Edicao.visiveis(request.user)  # 1916, atualizada, nova; as ocultas só para editores
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
    return render(request, "publico/sobre.html", {"edicoes": Edicao.visiveis(request.user),
                                                  "formatos": FORMATOS})


# ---------------------------------------------------------------------- sumário
def edicao(request, slug):
    ed = _edicao(request, slug)
    arv = leitura.Arvore(ed)
    arv.rotular_paginas(leitura.impressas())
    volumes = {v.pk: v for v in Volume.objects.all()}
    if not ed.reorganiza:  # 1916 e atualizada seguem a ordem dos volumes
        grupos = []
        for r in arv.raizes:
            if not grupos or grupos[-1]["volume"].pk != r.volume_id:
                grupos.append({"volume": volumes[r.volume_id], "raizes": []})
            grupos[-1]["raizes"].append(r)
    else:
        grupos = [{"volume": None, "raizes": arv.raizes}]
    return render(request, "publico/edicao.html", {
        "edicao": ed, "grupos": grupos, "n_nos": len(arv.nos), "nova": ed.derivada,
        "volumes_baixar": _volumes_baixar(ed, volumes.values()), **_contexto_arvore(volumes.values()),
    })


def _contexto_arvore(volumes):
    """O que `_no_arvore.html` precisa para o menu Baixar de cada nó."""
    return {"pdf_ok": exportacao.pdf_disponivel(),
            "fac_vols": [v.pk for v in volumes if fac_simile.disponivel(v)]}


def _volumes_baixar(ed, volumes):
    """Downloads do volume inteiro: TEI e PDF (LaTeX) se a edição tem texto nele; fac-símile se há scan."""
    com_texto = set(Bloco.objects.filter(edicao=ed).order_by().values_list("volume_id", flat=True).distinct())
    pdf_ok = exportacao.pdf_disponivel()
    linhas = []
    for v in volumes:
        texto = v.pk in com_texto
        fac = fac_simile.disponivel(v)
        if not (texto or fac):
            continue
        itens = []
        if texto:
            itens.append({"formato": "xml", "nome": "TEI XML", "url": reverse("obra:baixar_volume", args=[ed.slug, v.numero])})
            for k, nome in (("txt", "Texto puro"), ("html", "HTML"), ("tex", "LaTeX")):
                itens.append({"formato": k, "nome": nome,
                              "url": reverse("obra:baixar_volume_formato", args=[ed.slug, v.numero, k])})
        if texto and pdf_ok:
            itens.append({"formato": "pdf", "nome": "PDF", "url": reverse("obra:baixar_volume_pdf", args=[ed.slug, v.numero])})
        if fac:
            mb = round((fac_simile.tamanho_aproximado(v) or 0) / 2**20)
            itens.append({"formato": "fac-simile", "nome": f"Fac-símile (scan{f', ~{mb} MB' if mb else ''})",
                          "url": reverse("obra:baixar_fac_simile_volume", args=[v.numero])})
        linhas.append({"volume": v, "itens": itens})
    return linhas


def busca(request, slug):
    ed = _edicao(request, slug)
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
    ed = _edicao(request, slug)
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
    if ed.derivada:
        ed16 = Edicao.objects.filter(slug="1916").first()
        if ed16:
            arv16 = leitura.Arvore(ed16)
            for b in blocos:
                if b.origem_id and b.origem_ordem is not None:
                    alvo = arv16.cobrindo(b.origem_ordem)
                    if alvo:
                        origens[b.pk] = _url_no("1916", alvo.xml_id, b.origem_id)
    volumes = {v.pk: v for v in Volume.objects.all()}
    html, notas = leitura.renderizar(blocos, impressas_=imp, modo="web", url_facsimile=_fabrica_url_fac(volumes), origens=origens,
                                     volumes=({} if ed.derivada else None),
                                     citacoes=leitura.DadosCitacoes(), nova=ed.tipo == Edicao.NOVA)
    ctx = {
        "edicao": ed, "nova": ed.derivada, "no": n, "caminho": arv.caminho(n)[:-1], "titulo_no": leitura.titulo_do_no(n),
        "html": html, "notas": notas, "filhos": filhos, "inteiro": inteiro, "pode_tudo": pode_tudo,
        "total": total, "anterior": arv.vizinho(n, -1), "proximo": arv.vizinho(n, 1), "pai": n.pai_obj,
        "contribuintes": leitura.contribuintes(ed, n.ordem_ini, n.ordem_fim),
        "baixar": menu_baixar(ed, n, total, volumes.get(n.volume_id)),
        "slides_url": reverse("obra:slides", args=[ed.slug, n.xml_id]) if slides.disponivel(n, total) else None,
        "volume": volumes.get(n.volume_id),
        **_contexto_arvore(volumes.values()),
    }
    ctx["editar_url"] = _url_editar(request, ed, n, ctx["volume"])
    # tese cujo único conteúdo é o próprio texto: nada de sumário de filhos
    return render(request, "publico/no.html", ctx)


def _url_editar(request, ed, n, volume):
    """Tela de edição do trecho, para quem pode editar (mesma permissão da área restrita); senão None.

    Edições derivadas (atualizada, nova): o editor do próprio nó. 1916: a revisão da página onde o trecho
    começa (o editor é por página).
    """
    if not request.user.has_perm("obra.change_bloco"):
        return None
    if ed.derivada:
        return reverse("obra:nova_no", args=[ed.slug, n.xml_id])
    if volume is not None and n.pagina_ini is not None:
        return reverse("obra:revisar", args=[volume.numero, n.pagina_ini])
    return None


def menu_baixar(ed, n, total=None, vol=None):
    itens = [(k, v[0]) for k, v in FORMATOS.items() if k != "pdf"]
    if exportacao.pdf_disponivel(n, total):
        itens.append(("pdf", "PDF (LaTeX)"))
    menu = [{"formato": k, "nome": nome, "url": reverse("obra:baixar", args=[ed.slug, n.xml_id, k])}
            for k, nome in itens]
    if vol is None and n.volume_id:
        vol = Volume.objects.filter(pk=n.volume_id).first()
    if fac_simile.disponivel(vol):
        menu.append({"formato": "fac-simile", "nome": "Fac-símile (PDF do scan)",
                     "url": reverse("obra:baixar_fac_simile", args=[ed.slug, n.xml_id])})
    return menu


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
                                         url_facsimile=_fabrica_url_fac(), prefixo_id="f-",
                                         citacoes=leitura.DadosCitacoes())
    return render(request, "publico/facsimile.html", {
        "volume": vol, "pag": pag, "anterior": anterior, "proxima": proxima, "no_pagina": no_p,
        "ed16": ed16, "lado": lado, "html": html, "notas": notas,
        "continua": tem_continuacao,
        "baixar_volume": reverse("obra:baixar_fac_simile_volume", args=[vol.numero]) if fac_simile.disponivel(vol) else None,
        "baixar_volume_mb": round((fac_simile.tamanho_aproximado(vol) or 0) / 2**20) if fac_simile.disponivel(vol) else None,
    })


# ------------------------------------------------------------------------ download
def _resposta_arquivo(corpo, tipo, nome):
    resp = HttpResponse(corpo, content_type=tipo)
    resp["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resp


def _entregar(request, chave, funcao, tipo, nome, rotulo, voltar, espera=None):
    """Gera em segundo plano (esperando um pouco) e entrega o arquivo, a página "preparando" ou o erro."""
    estado, valor = exportacao.em_segundo_plano(
        chave, funcao, exportacao.ESPERA_PADRAO if espera is None else espera)
    if estado == "pronto":
        resp = FileResponse(open(valor, "rb"), content_type=tipo)
        resp["Content-Disposition"] = f'attachment; filename="{nome}"'
        return resp
    ctx = {"formato": rotulo, "voltar": voltar}
    if estado == "preparando":
        resp = render(request, "publico/preparando.html", {**ctx, "atualizar": 15}, status=202)
        resp["Retry-After"] = "15"
        resp["Cache-Control"] = "no-store"
        return resp
    return render(request, "publico/erro_baixar.html", {**ctx, "erro": valor}, status=503)


def _formato_pdf(request):
    """`?notas=sem-notas|1col|2col|corpo` escolhe a diagramação do PDF; sem ele, o PDF A5 padrão (None)."""
    fmt = request.GET.get("notas", "")
    if fmt and fmt not in exportacao.FORMATOS_PDF:
        raise Http404("Formato de PDF desconhecido.")
    return fmt or None


def baixar(request, slug, xml_id, formato):
    if formato not in FORMATOS:
        raise Http404("Formato desconhecido.")
    ed = _edicao(request, slug)
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
        if formato == "pdf":
            if not exportacao.pdf_disponivel(n):
                raise exportacao.ErroExportacao("A geração de PDF não está disponível nesta instalação; "
                                                "baixe o TEI ou o LaTeX.")
            tex = exportacao.latex_do_no(n)
            limite = exportacao.tempo_limite_pdf(exportacao.blocos_do_no(n).count())
            fmt = _formato_pdf(request)
            if fmt:
                titulo = exportacao.titulo_do_no(n)
                return _entregar(request, ("pdf", str(tex), fmt),
                                 lambda: exportacao.compilar_pdf_formato(tex, fmt, titulo, limite), tipo,
                                 nome[:-4] + f"-{fmt}.pdf", rotulo, _voltar_no(ed, n))
            return _entregar(request, ("pdf", str(tex)), lambda: exportacao.compilar_pdf(tex, limite), tipo, nome,
                             rotulo, _voltar_no(ed, n))
        caminho = exportacao.latex_do_no(n)
    except exportacao.ErroExportacao as e:
        return render(request, "publico/erro_baixar.html", {"erro": str(e), "formato": rotulo,
                                                             "voltar": _voltar_no(ed, n)}, status=503)
    resp = FileResponse(open(caminho, "rb"), content_type=tipo)
    resp["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resp


def baixar_volume(request, slug, numero):
    ed = _edicao(request, slug)
    vol = get_object_or_404(Volume, numero=numero)
    if not Bloco.objects.filter(edicao=ed, volume=vol).exists():
        raise Http404("Volume sem texto nesta edição.")
    corpo = exportacao.tei_do_volume(ed, vol)
    return _resposta_arquivo(corpo, FORMATOS["xml"][1], f"sinibaldi-{ed.slug}-vol{vol.numero}.xml")


def baixar_volume_formato(request, slug, numero, formato):
    """TXT, HTML ou LaTeX do volume inteiro (o TEI e o PDF têm rotas próprias)."""
    if formato not in ("txt", "html", "tex"):
        raise Http404("Formato desconhecido.")
    ed = _edicao(request, slug)
    vol = get_object_or_404(Volume, numero=numero)
    if not exportacao.blocos_do_volume(ed, vol).exists():
        raise Http404("Volume sem texto nesta edição.")
    rotulo, tipo, ext = FORMATOS[formato]
    nome = f"sinibaldi-{ed.slug}-vol{vol.numero}.{ext}"
    if formato == "txt":
        return _resposta_arquivo(exportacao.texto_do_volume(ed, vol), tipo, nome)
    if formato == "html":
        return _resposta_arquivo(exportacao.html_do_volume(ed, vol), tipo, nome)
    try:
        caminho = exportacao.latex_do_volume(ed, vol)
    except exportacao.ErroExportacao as e:
        return render(request, "publico/erro_baixar.html", {"erro": str(e), "formato": rotulo,
                                                             "voltar": _voltar_sumario(ed)}, status=503)
    resp = FileResponse(open(caminho, "rb"), content_type=tipo)
    resp["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resp


def _voltar_no(ed, n):
    return (reverse("obra:no", args=[ed.slug, n.xml_id]), "Voltar ao trecho")


def _voltar_sumario(ed):
    return (reverse("obra:edicao", args=[ed.slug]), "Voltar ao sumário")


def baixar_volume_pdf(request, slug, numero):
    """PDF (LaTeX) do volume inteiro: compila em segundo plano (alguns minutos na primeira vez)."""
    ed = _edicao(request, slug)
    vol = get_object_or_404(Volume, numero=numero)
    blocos = exportacao.blocos_do_volume(ed, vol)
    if not blocos.exists():
        raise Http404("Volume sem texto nesta edição.")
    rotulo = "PDF"
    try:
        if not exportacao.pdf_disponivel():
            raise exportacao.ErroExportacao("A geração de PDF não está disponível nesta instalação; baixe o TEI.")
        tex = exportacao.latex_do_volume(ed, vol)
    except exportacao.ErroExportacao as e:
        return render(request, "publico/erro_baixar.html", {"erro": str(e), "formato": rotulo,
                                                             "voltar": _voltar_sumario(ed)}, status=503)
    limite = exportacao.tempo_limite_pdf(blocos.count())
    fmt = _formato_pdf(request)
    if fmt:
        titulo = f"{exportacao.TITULO_OBRA}, vol. {vol.numero}"
        return _entregar(request, ("pdf", str(tex), fmt),
                         lambda: exportacao.compilar_pdf_formato(tex, fmt, titulo, limite), FORMATOS["pdf"][1],
                         f"sinibaldi-{ed.slug}-vol{vol.numero}-{fmt}.pdf", rotulo, _voltar_sumario(ed))
    return _entregar(request, ("pdf", str(tex)), lambda: exportacao.compilar_pdf(tex, limite), FORMATOS["pdf"][1],
                     f"sinibaldi-{ed.slug}-vol{vol.numero}.pdf", rotulo, _voltar_sumario(ed))


def baixar_fac_simile(request, slug, xml_id):
    """Fac-símile (páginas do scan original) de um trecho."""
    ed = _edicao(request, slug)
    n = get_object_or_404(No.objects.select_related("edicao", "volume"), edicao=ed, xml_id=xml_id)
    rotulo = "fac-símile em PDF"
    try:
        partes, destino = fac_simile.plano_trecho(n)
    except fac_simile.ErroFacSimile as e:
        return render(request, "publico/erro_baixar.html", {"erro": str(e), "formato": rotulo,
                                                             "voltar": _voltar_no(ed, n)}, status=503)
    return _entregar(request, ("fac", str(destino)), lambda: fac_simile.preparar_trecho(partes, destino),
                     FORMATOS["pdf"][1], exportacao.nome_arquivo(n, "pdf")[:-4] + "-fac-simile.pdf", rotulo,
                     _voltar_no(ed, n))


def baixar_fac_simile_volume(request, volume):
    """Fac-símile do volume inteiro (o scan original, uma página do livro por página do PDF)."""
    vol = get_object_or_404(Volume, numero=volume)
    rotulo = "fac-símile em PDF"
    voltar = (reverse("obra:inicio"), "Voltar ao início")
    try:
        origem, destino, total = fac_simile.plano_volume(vol)
    except fac_simile.ErroFacSimile as e:
        return render(request, "publico/erro_baixar.html", {"erro": str(e), "formato": rotulo, "voltar": voltar},
                      status=503)
    return _entregar(request, ("fac", str(destino)), lambda: fac_simile.preparar_volume(origem, destino, total),
                     FORMATOS["pdf"][1], f"sinibaldi-fac-simile-vol{vol.numero}.pdf", rotulo, voltar)
