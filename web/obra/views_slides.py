"""Slides de um trecho: parte pública (página, PDF, .tex, .txt) e área restrita (lista, editor da fonte).

Pública, sem login: `slides` (página com o PDF embutido), `slides_pdf`, `slides_tex`, `slides_txt`. Quem
compila é a rota do PDF (a página só embute); falha de compilação vira página amigável (503).
Restrita (login + `obra.change_bloco`): `slides_lista`, `slides_editor` e as ações POST
`slides_salvar`, `slides_regenerar`, `slides_descartar`, `slides_restaurar` (formulários clássicos + redirect).
"""
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from . import exportacao, leitura, slides
from .models import Apresentacao, ApresentacaoRevisao, Edicao, No, edicao_visivel_ou_404
from .views_edicao import PERMISSAO, _fmt_data, exige_edicao, nome_de, render_area

FORMATOS = {
    "pdf": ("PDF dos slides", "application/pdf", "pdf"),
    "tex": ("LaTeX dos slides", "application/x-tex; charset=utf-8", "tex"),
    "txt": ("fonte dos slides", "text/plain; charset=utf-8", "txt"),
}


def _no(request, slug, xml_id):
    ed = edicao_visivel_ou_404(slug, request.user)
    return ed, get_object_or_404(No.objects.select_related("edicao", "volume"), edicao=ed, xml_id=xml_id)


def _nome(no, ext):
    return exportacao.nome_arquivo(no, "slides." + ext)


# ====================================================================== pública
def pagina(request, slug, xml_id):
    """Página dos slides: PDF embutido, nº de slides, selo, downloads. Não compila nada."""
    ed = edicao_visivel_ou_404(slug, request.user)
    arv = leitura.Arvore(ed)
    n = arv.por_id.get(xml_id)
    if n is None:
        raise Http404("Trecho não encontrado.")
    total = slides.n_blocos(n)
    ctx = {"edicao": ed, "no": n, "caminho": arv.caminho(n)[:-1], "titulo_no": leitura.titulo_do_no(n),
           "total": total, "pode_corrigir": request.user.is_authenticated and request.user.has_perm(PERMISSAO),
           "limite": slides.MAX_BLOCOS, "disponivel": slides.disponivel(n, total)}
    if not ctx["disponivel"]:
        ctx["filhos"] = n.filhos_lista
        return render(request, "publico/slides.html", ctx)
    try:
        ap = slides.apresentacao_do_no(n)
        fonte = slides.fonte_do_no(n, ap)
    except slides.ErroApresentacao as e:
        return render(request, "publico/erro_baixar.html", {"edicao": ed, "no": n, "erro": str(e),
                                                             "formato": "slides"}, status=503)
    n_slides, por_tipo = slides.resumo(fonte)
    ctx.update(ap=ap, n_slides=n_slides, por_tipo=por_tipo, chave=slides.chave_da_fonte(fonte)[:12],
               revisada=bool(ap and ap.editada), revisor=nome_de(ap.atualizado_por) if ap else None)
    return render(request, "publico/slides.html", ctx)


def _etag_igual(request, etag):
    candidatos = [x.strip() for x in request.META.get("HTTP_IF_NONE_MATCH", "").split(",")]
    return etag in candidatos or "*" in candidatos


def _com_cache(resp, etag):
    resp["ETag"] = etag
    resp["Cache-Control"] = "public, no-cache"   # revalida sempre; o ETag torna isso barato
    return resp


@xframe_options_sameorigin
def arquivo(request, slug, xml_id, formato):
    """PDF (inline; `?baixar=1` baixa), `.tex` ou fonte `.txt` dos slides. O PDF é compilado aqui."""
    ed, n = _no(request, slug, xml_id)
    rotulo, tipo, ext = FORMATOS[formato]
    try:
        if not slides.disponivel(n):
            raise slides.ErroApresentacao("Este trecho é grande demais para gerar slides de uma vez; "
                                          "abra um dos seus capítulos, artigos ou teses.")
        fonte = slides.fonte_do_no(n)
        etag = '"slides-%s-%s"' % (formato, slides.chave_da_fonte(fonte))
        if _etag_igual(request, etag):
            return _com_cache(HttpResponse(status=304), etag)
        baixar = bool(request.GET.get("baixar"))
        nome = _nome(n, ext)
        if formato == "pdf":
            caminho = slides.pdf_do_no(n, fonte)
            resp = FileResponse(open(caminho, "rb"), content_type=tipo, as_attachment=baixar, filename=nome)
            return _com_cache(resp, etag)
        corpo = slides.tex_do_no(n, fonte) if formato == "tex" else fonte
        resp = HttpResponse(corpo, content_type=tipo)
        resp["Content-Disposition"] = '%s; filename="%s"' % ("attachment" if baixar else "inline", nome)
        return _com_cache(resp, etag)
    except exportacao.ErroExportacao as e:
        log = getattr(e, "log", "") if request.user.has_perm(PERMISSAO) else ""
        return render(request, "publico/erro_baixar.html", {"edicao": ed, "no": n, "erro": str(e), "log": log,
                                                             "formato": rotulo}, status=503)


# ===================================================================== restrita
@exige_edicao()
def lista(request):
    itens = []
    for ap in Apresentacao.objects.select_related("edicao", "atualizado_por"):
        n = No.objects.filter(edicao=ap.edicao, xml_id=ap.xml_id).first()
        itens.append({
            "ap": ap, "no": n, "n_slides": slides.gerador().contar_slides(ap.fonte),
            "mudou": bool(n and slides.texto_mudou(n, ap)),
            "autor": nome_de(ap.atualizado_por),
        })
    return render_area(request, "edicao/slides_lista.html", {"itens": itens})


def _contexto_editor(request, ed, n, ap, *, fonte=None, erros=(), versao=None, conflito=None):
    efetiva = slides.fonte_do_no(n, ap)
    editada = fonte if fonte is not None else efetiva
    v = ap.versao if ap else 0
    ctx = {
        "edicao": ed, "no": n, "titulo_no": leitura.titulo_do_no(n), "ap": ap, "fonte": editada,
        "versao": v if versao is None else versao, "erros": list(erros),
        "tipos": slides.tipos(), "historico": slides.historico(n),
        "disponivel": slides.disponivel(n), "limite": slides.MAX_BLOCOS,
        "filhos": list(No.objects.filter(pai=n).order_by("ordem_ini")),
    }
    if not ctx["disponivel"]:
        return ctx
    ctx["chave"] = slides.chave_da_fonte(efetiva)[:12]
    ctx["n_slides"] = slides.resumo(efetiva)[0]
    ctx["erro_compilacao"] = slides.erro_da_fonte(efetiva)
    if conflito is not None:
        ctx["conflito"] = {"por": nome_de(conflito.atual.atualizado_por) if conflito.atual else None,
                           "em": _fmt_data(conflito.atual.atualizado_em) if conflito.atual else "",
                           "descartada": conflito.atual is None,
                           "diff": slides.diff_fontes(conflito.atual.fonte, editada) if conflito.atual else ""}
    if slides.texto_mudou(n, ap):
        nova = slides.fonte_automatica(n)
        ctx["mudou"] = {"diff": slides.diff_fontes(ap.fonte_gerada, nova)}
    return ctx


@exige_edicao()
def editor(request, slug, xml_id):
    ed, n = _no(request, slug, xml_id)
    ap = slides.apresentacao_do_no(n)
    try:
        ctx = _contexto_editor(request, ed, n, ap)
    except slides.ErroApresentacao as e:
        messages.error(request, str(e))
        return redirect("obra:slides_lista")
    return render_area(request, "edicao/slides_editor.html", ctx)


def _inteiro(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _renderizar_erro(request, ed, n, status, **kw):
    """Reapresenta o editor (com o texto digitado) e o código de status do erro."""
    ctx = _contexto_editor(request, ed, n, slides.apresentacao_do_no(n), **kw)
    resp = render_area(request, "edicao/slides_editor.html", ctx)
    resp.status_code = status
    return resp


def _recompilar(request, n, ap):
    """Compila o PDF da fonte salva logo após gravar; falha vira mensagem (a fonte já está salva)."""
    try:
        slides.pdf_do_no(n, ap.fonte)
    except slides.ErroApresentacao as e:
        messages.error(request, f"A fonte foi salva, mas a compilação falhou: {e}")
        return False
    return True


def _volta(ed, n):
    return redirect("obra:slides_editor", ed.slug, n.xml_id)


@exige_edicao()
@require_POST
def salvar(request, slug, xml_id):
    ed, n = _no(request, slug, xml_id)
    fonte = request.POST.get("fonte", "")
    versao = _inteiro(request.POST.get("versao"))
    if versao is None:
        return _renderizar_erro(request, ed, n, 400, fonte=fonte, erros=["Requisição inválida: falta a versão lida."])
    try:
        ap = slides.gravar(n, fonte, request.user, ApresentacaoRevisao.EDITAR, versao)
    except slides.FonteInvalida as e:
        return _renderizar_erro(request, ed, n, 400, fonte=fonte, erros=e.erros, versao=versao)
    except slides.Conflito as e:
        atual = e.atual.versao if e.atual else 0
        return _renderizar_erro(request, ed, n, 409, fonte=fonte, versao=atual, conflito=e)
    except slides.ErroApresentacao as e:
        return _renderizar_erro(request, ed, n, 503, fonte=fonte, erros=[str(e)], versao=versao)
    if _recompilar(request, n, ap):
        messages.success(request, "Slides salvos e recompilados.")
    return _volta(ed, n)


@exige_edicao()
@require_POST
def regenerar(request, slug, xml_id):
    """Substitui a fonte pela automática (a anterior fica no histórico). Com correções, exige `confirmo`."""
    ed, n = _no(request, slug, xml_id)
    ap = slides.apresentacao_do_no(n)
    if ap is not None and ap.editada and not request.POST.get("confirmo"):
        messages.error(request, "Marque a caixa de confirmação para substituir as correções pela versão automática.")
        return _volta(ed, n)
    versao = _inteiro(request.POST.get("versao"))
    try:
        ap = slides.gravar(n, "", request.user, ApresentacaoRevisao.REGENERAR, 0 if versao is None else versao)
    except slides.Conflito as e:
        return _renderizar_erro(request, ed, n, 409, conflito=e, versao=e.atual.versao if e.atual else 0,
                                fonte=request.POST.get("fonte"))
    except (slides.ErroApresentacao, slides.FonteInvalida) as e:
        messages.error(request, str(e))
        return _volta(ed, n)
    if _recompilar(request, n, ap):
        messages.success(request, "Slides gerados de novo a partir do texto do livro.")
    return _volta(ed, n)


@exige_edicao()
@require_POST
def descartar(request, slug, xml_id):
    ed, n = _no(request, slug, xml_id)
    if not request.POST.get("confirmo"):
        messages.error(request, "Marque a caixa de confirmação para descartar as correções.")
        return _volta(ed, n)
    versao = _inteiro(request.POST.get("versao"))
    try:
        slides.descartar(n, request.user, 0 if versao is None else versao)
    except slides.Conflito as e:
        return _renderizar_erro(request, ed, n, 409, conflito=e, versao=e.atual.versao if e.atual else 0)
    messages.success(request, "Correções descartadas: os slides voltaram a ser os automáticos.")
    return _volta(ed, n)


@exige_edicao()
@require_POST
def restaurar(request, slug, xml_id):
    """Põe de volta a fonte de uma revisão do histórico (como nova revisão)."""
    ed, n = _no(request, slug, xml_id)
    rev = slides.revisao_do_no(n, _inteiro(request.POST.get("revisao")) or 0)
    versao = _inteiro(request.POST.get("versao"))
    if rev is None or versao is None:
        raise Http404("Revisão não encontrada.")
    try:
        ap = slides.gravar(n, rev.fonte, request.user, ApresentacaoRevisao.RESTAURAR, versao)
    except slides.FonteInvalida as e:
        messages.error(request, "A fonte dessa revisão não passa mais na validação: " + "; ".join(e.erros[:3]))
        return _volta(ed, n)
    except slides.Conflito as e:
        return _renderizar_erro(request, ed, n, 409, conflito=e, versao=e.atual.versao if e.atual else 0)
    if _recompilar(request, n, ap):
        messages.success(request, "Versão anterior restaurada e recompilada.")
    return _volta(ed, n)
