"""Sugestões de correção: envio por leitores anônimos (parte pública) e triagem pelos editores."""
import hashlib

from django.contrib import messages
from django.core.cache import cache
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import diffs, leitura, servicos, servicos_sugestoes
from .forms import SugestaoForm
from .models import Bloco, Edicao, No, Sugestao
from .views_edicao import exige_edicao, render_area

LIMITE_ENVIOS = 10        # envios por IP por janela
JANELA_SEGUNDOS = 3600    # 1 hora
POR_PAGINA = 25
MSG_OBRIGADO = "Obrigado! Sua sugestão foi enviada e será avaliada pelos editores."


# ====================================================================== parte pública
def _chave_ip(request):
    """Chave de cache do limite por IP: só o hash SHA-256 do endereço (o IP cru nunca é guardado)."""
    ip = request.META.get("REMOTE_ADDR", "")
    return "sugestao-ip:" + hashlib.sha256(ip.encode("utf-8")).hexdigest()


def _registrar_envio(request):
    chave = _chave_ip(request)
    cache.add(chave, 0, JANELA_SEGUNDOS)
    try:
        cache.incr(chave)
    except ValueError:  # expirou entre o add e o incr
        cache.set(chave, 1, JANELA_SEGUNDOS)


def _limite_estourado(request):
    return (cache.get(_chave_ip(request)) or 0) >= LIMITE_ENVIOS


def _bloco_valido(ed, pk):
    """Bloco da edição que aceita sugestões (não suprimido, não cabeçalho corrente), ou None."""
    if not str(pk or "").isdigit():
        return None
    return (Bloco.objects.filter(pk=int(pk), edicao=ed).exclude(procedencia=Bloco.SUPRIMIDO)
            .exclude(tipo=Bloco.CABECALHO).first())


def sugerir(request, slug, xml_id):
    ed = get_object_or_404(Edicao, slug=slug)
    no = get_object_or_404(No, edicao=ed, xml_id=xml_id)
    status = 200
    if request.method == "POST":
        if _limite_estourado(request):
            form = SugestaoForm(request.POST, edicao=ed)
            form.add_error(None, "Muitos envios deste endereço na última hora. Tente novamente mais tarde.")
            status = 429
        else:
            form = SugestaoForm(request.POST, edicao=ed)
            if form.is_valid():
                _registrar_envio(request)
                if form.cleaned_data.get("site"):  # isca preenchida: finge sucesso, não grava
                    return _sucesso(request, ed, no, None)
                s = form.save(commit=False)
                s.no_xml_id = no.xml_id
                s.save()
                return _sucesso(request, ed, no, s.bloco_id)
    else:
        form = SugestaoForm(initial={"bloco": request.GET.get("bloco")}, edicao=ed)
    bloco = _bloco_valido(ed, form["bloco"].value())
    return render(request, "publico/sugerir.html", {
        "edicao": ed, "no": no, "form": form, "bloco": bloco,
        "texto_bloco": leitura.texto_plano(bloco.xml) if bloco else "",
        "titulo_no": leitura.titulo_do_no(no)}, status=status)


def _sucesso(request, ed, no, bloco_id):
    messages.success(request, MSG_OBRIGADO)
    url = reverse("obra:no", args=[ed.slug, no.xml_id])
    return redirect(f"{url}#b{bloco_id}" if bloco_id else url)


# ================================================================ área dos editores
def _url_editor(s, arvore_de):
    """Link para o editor do bloco: tela da página (1916) ou do nó (nova edição); None sem bloco."""
    b = s.bloco
    if b is None:
        return None
    if s.edicao.tipo == Edicao.NOVA:
        n = arvore_de(s.edicao).cobrindo(b.ordem)
        return reverse("obra:nova_no", args=[n.xml_id]) if n else reverse("obra:nova_estrutura")
    if b.volume_id and b.pagina is not None:
        return reverse("obra:revisar", args=[b.volume.numero, b.pagina])
    return None


@exige_edicao()
def lista(request):
    estado = request.GET.get("estado", Sugestao.PENDENTE)
    if estado != "todas" and estado not in dict(Sugestao.ESTADOS):
        estado = Sugestao.PENDENTE
    f_edicao = request.GET.get("edicao", "")
    qs = Sugestao.objects.select_related("edicao", "bloco", "bloco__volume", "resolvida_por")
    if estado != "todas":
        qs = qs.filter(estado=estado)
    if f_edicao:
        qs = qs.filter(edicao__slug=f_edicao)
    page_obj = Paginator(qs, POR_PAGINA).get_page(request.GET.get("page"))
    memo = {}

    def arvore_de(ed):
        if ed.pk not in memo:
            memo[ed.pk] = leitura.Arvore(ed)
        return memo[ed.pk]

    itens = []
    for s in page_obj:
        itens.append({
            "s": s,
            "url_publico": reverse("obra:no", args=[s.edicao.slug, s.no_xml_id]) + (f"#b{s.bloco_id}" if s.bloco_id else ""),
            "url_editor": _url_editor(s, arvore_de),
            "diff": diffs.diff_html(s.trecho, s.sugestao) if s.trecho or s.sugestao else "",
            "alterado": s.bloco is not None and s.bloco_versao is not None and s.bloco.versao != s.bloco_versao,
            "sem_bloco": s.bloco is None and s.estado == Sugestao.PENDENTE,
            "pode_aplicar": servicos_sugestoes.pode_aplicar(s),
        })
    qs_get = request.GET.copy()
    qs_get.pop("page", None)
    return render_area(request, "edicao/sugestoes.html", {
        "itens": itens, "page_obj": page_obj, "f_estado": estado, "f_edicao": f_edicao,
        "estados": Sugestao.ESTADOS, "edicoes": Edicao.objects.order_by("slug"),
        "querystring": (qs_get.urlencode() + "&") if qs_get else ""})


@exige_edicao()
@require_POST
def acao(request, pk):
    s = get_object_or_404(Sugestao.objects.select_related("edicao", "bloco"), pk=pk)
    destino = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        destino = reverse("obra:sugestoes")
    qual = request.POST.get("acao", "")
    resposta = (request.POST.get("resposta") or "").strip()[:2000]
    try:
        if qual == "aplicar":
            servicos_sugestoes.aplicar(s, request.user, resposta)
            messages.success(request, f"Sugestão #{s.pk} aplicada ao texto (bloco #{s.bloco_id}).")
        elif qual in ("aceitar", "rejeitar"):
            s.estado = Sugestao.ACEITA if qual == "aceitar" else Sugestao.REJEITADA
            s.resolvida_por, s.resolvida_em, s.resposta = request.user, timezone.now(), resposta
            s.save(update_fields=["estado", "resolvida_por", "resolvida_em", "resposta"])
            messages.success(request, f"Sugestão #{s.pk} " + ("marcada como aceita." if qual == "aceitar" else "rejeitada."))
        elif qual == "reabrir":
            s.estado, s.resolvida_por, s.resolvida_em = Sugestao.PENDENTE, None, None
            if resposta:
                s.resposta = resposta
            s.save(update_fields=["estado", "resolvida_por", "resolvida_em", "resposta"])
            messages.success(request, f"Sugestão #{s.pk} reaberta.")
        else:
            messages.error(request, "Ação desconhecida.")
    except servicos_sugestoes.ErroAplicacao as e:
        messages.error(request, f"Sugestão #{s.pk} não aplicada: {e}")
    except servicos.ErroValidacao as e:
        messages.error(request, f"Sugestão #{s.pk} não aplicada: o texto resultante é inválido ({'; '.join(e.erros)}).")
    except servicos.Conflito:
        messages.error(request, f"Sugestão #{s.pk} não aplicada: o bloco foi alterado por outra pessoa. Tente de novo.")
    return redirect(destino)
