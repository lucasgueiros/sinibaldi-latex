"""Área restrita de revisão da edição 1916/17: painel, lista de páginas, tela de revisão
(scan + editor), conversão html<->xml, gravação e histórico.

Todas as views exigem login e a permissão `obra.change_bloco` (anônimo -> login; sem
permissão -> 403). Endpoints JSON (`converter`, `gravar`) respondem 401/403 em JSON.
"""
import json
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Max, OuterRef, Subquery
from django.http import Http404, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import diffs, esquema, servicos, tei
from .models import Bloco, Edicao, Pagina, Revisao, Volume

PERMISSAO = "obra.change_bloco"
SLUG_REVISAO = "1916"
POR_PAGINA = 60


# ------------------------------------------------------------------ infra
def exige_edicao(api=False):
    """Login + permissão `obra.change_bloco`. `api=True`: erros em JSON (401/403)."""

    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if api:
                    return JsonResponse({"erros": ["Sessão expirada: entre novamente."]}, status=401)
                return redirect_to_login(request.get_full_path())
            if not request.user.has_perm(PERMISSAO):
                if api:
                    return JsonResponse({"erros": ["Sem permissão para editar."]}, status=403)
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return deco


def nome_de(usuario):
    if usuario is None:
        return None
    return usuario.get_full_name() or usuario.get_username()


def esquema_para_cliente():
    """Constantes de `esquema.py` que a barra de ferramentas do editor usa (via `json_script`)."""
    return {
        "niveis": esquema.NIVEIS,
        "tipos_paragrafo": esquema.TIPOS_PARAGRAFO,
        "rend": esquema.REND,
        "tipos_bloco": esquema.TIPOS_BLOCO,
        "prefixos_id": {"parte": "parte", "seccao": "sec", "capitulo": "cap", "artigo": "art", "tese": "t"},
    }


def _edicao():
    return get_object_or_404(Edicao, slug=SLUG_REVISAO)


def _json_corpo(request):
    try:
        dados = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return dados if isinstance(dados, dict) else None


def render_area(request, modelo, contexto):
    contexto["volumes_nav"] = list(Volume.objects.all())
    return render(request, modelo, contexto)


def _fmt_data(dt):
    return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M") if dt else ""


# -------------------------------------------------- conversão de conteúdo
def blocos_do_conteudo(formato, conteudo):
    """('html'|'xml', texto) -> lista de {id, versao, xml}. Levanta `servicos.ErroValidacao`."""
    if formato == "html":
        blocos = tei.html_para_blocos(conteudo or "")
    elif formato == "xml":
        try:
            blocos = tei.texto_xml_para_blocos(conteudo or "")
        except tei.ErroTextoXml as e:
            raise servicos.ErroValidacao(e.erros)
    else:
        raise servicos.ErroValidacao([f"Formato desconhecido: {formato!r}."])
    erros = esquema.validar_blocos(blocos)
    if erros:
        raise servicos.ErroValidacao(erros)
    return blocos


def info_dos_blocos(blocos, seq=None):
    """{pk: {versao, autor, em, pagina, comeca_antes}} para o painel de autoria por bloco."""
    info = {}
    for b in blocos:
        info[str(b.pk)] = {
            "versao": b.versao,
            "autor": nome_de(b.atualizado_por),
            "em": _fmt_data(b.atualizado_em) if b.atualizado_por_id else "",
            "pagina": b.pagina,
            "comeca_antes": seq is not None and b.pagina is not None and b.pagina != seq,
        }
    return info


def _estado_json(pagina):
    return {
        "valor": pagina.estado,
        "rotulo": pagina.get_estado_display(),
        "por": nome_de(pagina.revisada_por),
        "em": _fmt_data(pagina.revisada_em),
    }


@exige_edicao(api=True)
@require_POST
def converter(request):
    """`{de: "html"|"xml", conteudo}` -> `{html, xml, erros}` (HTTP 200 mesmo com erros de validação)."""
    dados = _json_corpo(request)
    if dados is None or dados.get("de") not in ("html", "xml"):
        return JsonResponse({"erros": ["Requisição inválida: informe `de` ('html' ou 'xml') e `conteudo`."]}, status=400)
    try:
        blocos = blocos_do_conteudo(dados["de"], dados.get("conteudo", ""))
    except servicos.ErroValidacao as e:
        return JsonResponse({"html": None, "xml": None, "erros": e.erros})
    return JsonResponse({
        "html": tei.blocos_para_html(blocos),
        "xml": tei.blocos_para_texto_xml(blocos),
        "erros": [],
    })


# ------------------------------------------------------------------ painel
@exige_edicao()
def painel(request):
    edicao = _edicao()
    volumes = []
    for vol in Volume.objects.all():
        cont = {e: 0 for e, _ in Pagina.ESTADOS}
        for linha in Pagina.objects.filter(volume=vol).values("estado").annotate(n=Count("id")):
            cont[linha["estado"]] = linha["n"]
        total = sum(cont.values())
        volumes.append({
            "volume": vol, "total": total, "contagem": cont,
            "pct_revisada": round(100 * cont["revisada"] / total, 1) if total else 0,
            "pct_validada": round(100 * cont["validada"] / total, 1) if total else 0,
            "pct_feito": round(100 * (cont["revisada"] + cont["validada"]) / total, 1) if total else 0,
        })
    ultima = (Revisao.objects.filter(edicao=edicao, autor=request.user, pagina__isnull=False, volume__isnull=False)
              .exclude(acao=Revisao.IMPORTAR).select_related("volume").order_by("-criado_em", "-pk").first())
    continuar = None
    if ultima is not None:
        pg = Pagina.objects.filter(volume=ultima.volume, seq=ultima.pagina).first()
        continuar = {"volume": ultima.volume, "seq": ultima.pagina, "impressa": pg.impressa if pg else "",
                     "quando": ultima.criado_em}
    recentes = (Revisao.objects.filter(edicao=edicao).exclude(acao=Revisao.IMPORTAR)
                .select_related("autor", "volume").order_by("-criado_em", "-pk")[:80])
    lotes, vistos = [], {}
    for r in recentes:
        if r.lote in vistos:
            vistos[r.lote]["n"] += 1
            continue
        item = {"lote": r.lote, "autor": nome_de(r.autor) or "—", "quando": r.criado_em, "volume": r.volume,
                "pagina": r.pagina, "acao": r.get_acao_display(), "comentario": r.comentario, "n": 1}
        vistos[r.lote] = item
        lotes.append(item)
    return render_area(request, "edicao/painel.html", {
        "volumes": volumes, "continuar": continuar, "lotes": lotes[:12], "edicao": edicao})


# ----------------------------------------------------------- lista de páginas
@exige_edicao()
def paginas(request, numero):
    edicao = _edicao()
    volume = get_object_or_404(Volume, numero=numero)
    ir = (request.GET.get("ir") or "").strip()
    if ir:
        alvo = Pagina.objects.filter(volume=volume, impressa=ir).first()
        if alvo is None and ir.lstrip("-").isdigit():
            alvo = Pagina.objects.filter(volume=volume, seq=int(ir)).first()
        if alvo is not None:
            return redirect("obra:revisar", numero=volume.numero, seq=alvo.seq)
    estado = request.GET.get("estado", "")
    ultima = (Revisao.objects.filter(edicao=edicao, volume=OuterRef("volume"), pagina=OuterRef("seq"))
              .exclude(acao=Revisao.IMPORTAR).order_by("-criado_em", "-pk"))
    qs = (Pagina.objects.filter(volume=volume).select_related("revisada_por")
          .annotate(ultimo_autor=Subquery(ultima.values("autor__username")[:1]),
                    ultima_edicao=Subquery(ultima.values("criado_em")[:1])).order_by("seq"))
    if estado in dict(Pagina.ESTADOS):
        qs = qs.filter(estado=estado)
    pag = Paginator(qs, POR_PAGINA).get_page(request.GET.get("page"))
    return render_area(request, "edicao/paginas.html", {
        "volume": volume, "page_obj": pag, "estado": estado, "estados": Pagina.ESTADOS,
        "erro_ir": ir if ir else "", "querystring": f"estado={estado}&" if estado else "",
        "volumes": Volume.objects.all()})


# --------------------------------------------------------- tela de revisão
def _pagina_ou_404(volume, seq):
    return get_object_or_404(Pagina.objects.select_related("volume", "revisada_por"), volume=volume, seq=seq)


@exige_edicao()
def revisar(request, numero, seq):
    edicao = _edicao()
    volume = get_object_or_404(Volume, numero=numero)
    pagina = _pagina_ou_404(volume, seq)
    ant = Pagina.objects.filter(volume=volume, seq__lt=seq).order_by("-seq").first()
    seg = Pagina.objects.filter(volume=volume, seq__gt=seq).order_by("seq").first()
    blocos = servicos.blocos_da_pagina(edicao, volume, seq)
    blocos = list(Bloco.objects.filter(pk__in=[b.pk for b in blocos]).select_related("atualizado_por").order_by("ordem"))
    dados = {
        "html": tei.blocos_para_html(blocos),
        "ids": [b.pk for b in blocos],
        "info": info_dos_blocos(blocos, seq),
        "pagina": {"n": seq, "facs": f"paginas/{pagina.arquivo or format(seq, '04d')}.png", "impressa": pagina.impressa},
        "prefixoId": f"v{volume.numero}.",
        "estado": _estado_json(pagina),
        "urlConverter": reverse("obra:converter"),
        "urlGravar": reverse("obra:gravar", args=[volume.numero, seq]),
        "urlHistoricoBloco": reverse("obra:historico_bloco", args=[0]),
        "csrf": get_token(request),
        "scan": reverse("obra:scan", args=[volume.numero, seq]),
        "chaveLocal": f"sinibaldi.revisao.v{volume.numero}",
        "urlSeguinte": reverse("obra:revisar", args=[volume.numero, seg.seq]) if seg else "",
    }
    return render_area(request, "edicao/revisar.html", {
        "edicao": edicao, "volume": volume, "pagina": pagina, "anterior": ant, "seguinte": seg,
        "dados": dados, "esquema": esquema_para_cliente(), "estados": Pagina.ESTADOS,
        "n_blocos": len(blocos)})


def _ancora_para_pagina_vazia(edicao, volume, seq):
    """Página sem blocos: insere depois do último bloco de páginas anteriores do mesmo volume."""
    ref = (Bloco.objects.filter(edicao=edicao, volume=volume, pagina__lt=seq).order_by("-ordem").first())
    return ref.pk if ref else None


@exige_edicao(api=True)
@require_POST
def gravar(request, numero, seq):
    edicao = _edicao()
    volume = get_object_or_404(Volume, numero=numero)
    pagina = _pagina_ou_404(volume, seq)
    dados = _json_corpo(request)
    if dados is None:
        return JsonResponse({"erros": ["Requisição inválida (JSON esperado)."]}, status=400)
    ids = dados.get("ids", [])
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        return JsonResponse({"erros": ["`ids` deve ser uma lista de inteiros."]}, status=400)
    comentario = str(dados.get("comentario") or "")[:2000]
    estado = dados.get("estado")
    if estado is not None and estado not in dict(Pagina.ESTADOS):
        return JsonResponse({"erros": [f"Estado inválido: {estado}."]}, status=400)
    try:
        novos = blocos_do_conteudo(dados.get("formato"), dados.get("conteudo", ""))
        ancora = _ancora_para_pagina_vazia(edicao, volume, seq) if not ids else None
        res = servicos.salvar_blocos(
            edicao, ids, novos, autor=request.user, comentario=comentario, volume=volume, pagina=seq, ancora=ancora)
    except servicos.ErroValidacao as e:
        return JsonResponse({"erros": e.erros}, status=400)
    except servicos.Conflito as e:
        detalhes = []
        for b in Bloco.objects.filter(pk__in=e.ids).select_related("atualizado_por"):
            quem = nome_de(b.atualizado_por) or "outra pessoa"
            detalhes.append({"id": b.pk, "autor": quem, "em": _fmt_data(b.atualizado_em), "versao": b.versao})
        quem = ", ".join(sorted({d["autor"] for d in detalhes})) or "outra pessoa"
        return JsonResponse({
            "conflito": True, "ids": e.ids, "detalhes": detalhes,
            "erros": [f"Conflito: {'o bloco' if len(e.ids) == 1 else 'os blocos'} "
                      f"{', '.join('#%d' % i for i in e.ids)} foi alterado por {quem} depois que você abriu esta página. "
                      "Recarregue para ver a versão atual (copie antes o seu texto, se quiser reaplicá-lo)."],
        }, status=409)
    if estado is not None and estado != pagina.estado:
        servicos.marcar_pagina(pagina, estado, request.user)
    blocos = list(Bloco.objects.filter(pk__in=[b.pk for b in res.blocos]).select_related("atualizado_por").order_by("ordem"))
    return JsonResponse({
        "ok": True,
        "alterou": res.alterou,
        "resumo": {"criados": res.criados, "editados": res.editados, "removidos": res.removidos, "movidos": res.movidos},
        "lote": str(res.lote),
        "html": tei.blocos_para_html(blocos),
        "xml": tei.blocos_para_texto_xml(blocos),
        "ids": [b.pk for b in blocos],
        "info": info_dos_blocos(blocos, seq),
        "estado": _estado_json(pagina),
    })


# ---------------------------------------------------------------- histórico
def _linhas_revisao(revisoes):
    linhas = []
    for r in revisoes:
        linhas.append({
            "rev": r,
            "diff": diffs.diff_html(r.xml_antes, r.xml_depois) if r.acao in (Revisao.EDITAR, Revisao.CRIAR, Revisao.REMOVER) else "",
        })
    return linhas


@exige_edicao()
def historico(request):
    edicao = _edicao()
    revs = Revisao.objects.filter(edicao=edicao)
    if not request.GET.get("importacoes"):
        revs = revs.exclude(acao=Revisao.IMPORTAR)
    autor = request.GET.get("autor", "")
    vol = request.GET.get("volume", "")
    pg = request.GET.get("pagina", "")
    if autor.isdigit():
        revs = revs.filter(autor_id=int(autor))
    if vol.isdigit():
        revs = revs.filter(volume__numero=int(vol))
    if pg.lstrip("-").isdigit():
        revs = revs.filter(pagina=int(pg))
    lotes = (revs.values("lote").annotate(ultimo=Max("criado_em"), n=Count("id")).order_by("-ultimo", "-lote"))
    page_obj = Paginator(lotes, 15).get_page(request.GET.get("page"))
    ids = [x["lote"] for x in page_obj]
    por_lote = {}
    for r in (revs.filter(lote__in=ids).select_related("autor", "volume", "bloco").order_by("pk")):
        por_lote.setdefault(r.lote, []).append(r)
    itens = []
    for x in page_obj:
        rs = por_lote.get(x["lote"], [])
        primeira = rs[0] if rs else None
        itens.append({
            "lote": x["lote"], "n": x["n"], "quando": x["ultimo"],
            "autor": nome_de(primeira.autor) if primeira and primeira.autor else "—",
            "comentario": primeira.comentario if primeira else "",
            "volume": primeira.volume if primeira else None,
            "pagina": primeira.pagina if primeira else None,
            "linhas": _linhas_revisao(rs[:40]), "truncado": len(rs) > 40,
        })
    from django.contrib.auth import get_user_model
    autores = get_user_model().objects.filter(revisoes_obra__edicao=edicao).distinct().order_by("username")
    qs = request.GET.copy()
    qs.pop("page", None)
    return render_area(request, "edicao/historico.html", {
        "itens": itens, "page_obj": page_obj, "autores": autores, "volumes": Volume.objects.all(),
        "f_autor": autor, "f_volume": vol, "f_pagina": pg, "f_importacoes": request.GET.get("importacoes", ""),
        "querystring": (qs.urlencode() + "&") if qs else ""})


@exige_edicao()
def historico_bloco(request, pk):
    bloco = Bloco.objects.filter(pk=pk, edicao__slug=SLUG_REVISAO).select_related("volume").first()
    if bloco is None:
        raise Http404("Bloco não encontrado.")
    revs = bloco.revisoes.select_related("autor").order_by("-criado_em", "-pk")
    page_obj = Paginator(revs, 20).get_page(request.GET.get("page"))
    return render_area(request, "edicao/historico_bloco.html", {
        "bloco": bloco, "page_obj": page_obj, "linhas": _linhas_revisao(page_obj),
        "pagina": Pagina.objects.filter(volume=bloco.volume, seq=bloco.pagina).first() if bloco.volume_id else None})
