"""Telas das edições DERIVADAS da 1916 (atualizada e nova): estrutura (árvore; na nova também mover,
suprimir e ordem das partes), editor de trecho paginado (texto de 1916 + scan à esquerda) e
pendências de sincronização com a 1916.

Todas exigem login + `obra.change_bloco`, recebem o `slug` da edição e operam SOMENTE nela
(`_nova(slug)`: 404 se não for derivada); os serviços filtram por edição, de modo que ids de blocos
da 1916 são recusados. As operações estruturais exigem `edicao.reorganiza` (só a nova). No contexto
dos templates a edição derivada continua se chamando `nova`."""
import time
from bisect import bisect_left
from math import ceil

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from . import arvore, diffs, leitura, partes, servicos, servicos_nova, tei
from .models import Bloco, Edicao, No, Pagina, Revisao, Volume
from .views_edicao import (_json_corpo, _fmt_data, blocos_do_conteudo, esquema_para_cliente, exige_edicao,
                           nome_de, render_area)

SLUG_NOVA = "nova"
SLUG_ATUALIZADA = "atualizada"
POR_TELA = 40          # blocos por tela do editor
POR_LISTA = 25         # itens por página nas pendências
PROCEDENCIA_ROTULO = dict(Bloco.PROCEDENCIAS)


def _nova(slug):
    return get_object_or_404(Edicao, slug=slug, tipo__in=Edicao.DERIVADAS)


def _reorganizavel(slug):
    """A edição derivada, se ela reorganiza a estrutura; senão 404 (a atualizada segue a 1916)."""
    ed = _nova(slug)
    if not ed.reorganiza:
        raise Http404("Esta edição segue a estrutura da 1916.")
    return ed


def _erro_json(msg, status=400):
    return JsonResponse({"erros": [msg] if isinstance(msg, str) else list(msg)}, status=status)


# ============================================================ árvore em memória
def _arvore_enriquecida(nova):
    """`leitura.Arvore` com, em cada nó: n_blocos, suprimido, pag, pode_subir/descer (e alvos)."""
    arv = leitura.Arvore(nova)
    ordens = list(Bloco.objects.filter(edicao=nova).order_by("ordem").values_list("ordem", flat=True))
    suprim = set(Bloco.objects.filter(edicao=nova, tipo=Bloco.MARCO, procedencia=Bloco.SUPRIMIDO)
                 .values_list("ordem", flat=True))
    imp = leitura.impressas()
    for n in arv.nos:  # ordem_ini crescente: o pai vem antes
        n.n_blocos = bisect_left(ordens, n.ordem_fim) - bisect_left(ordens, n.ordem_ini)
        n.suprimido = n.ordem_ini in suprim or bool(n.pai_obj is not None and n.pai_obj.suprimido)
        n.pag = imp.get((n.volume_id, n.pagina_ini), "") if n.pagina_ini is not None else ""
        n.abre = False
    for grupo in [arv.raizes] + [n.filhos_lista for n in arv.nos]:
        por_nivel = {}
        for n in grupo:
            por_nivel.setdefault(n.nivel, []).append(n)
        for lista in por_nivel.values():
            for i, n in enumerate(lista):
                n.irmao_ant = lista[i - 1] if i else None
                n.irmao_seg = lista[i + 1] if i + 1 < len(lista) else None
    return arv, ordens


def _trechos_soltos(nova, arv, ordens):
    """Trechos de blocos fora de qualquer nó (raiz sem parte/capítulo...). Lista de dicts."""
    out, cursor = [], 0
    for r in list(arv.raizes) + [None]:
        ini = r.ordem_ini if r is not None else arvore.ORDEM_MAX
        i0, i1 = bisect_left(ordens, cursor), bisect_left(ordens, ini)
        if i1 > i0:
            out.append({"tipo": "trecho", "ordem_ini": ordens[i0], "ordem_fim": ini, "n_blocos": i1 - i0})
        if r is not None:
            cursor = max(cursor, r.ordem_fim)
    if out:
        primeiros = {b.ordem: b for b in Bloco.objects.filter(edicao=nova, ordem__in=[t["ordem_ini"] for t in out])}
        for t in out:
            b = primeiros[t["ordem_ini"]]
            t["amostra"] = leitura.texto_plano(b.xml, notas=False)[:110]
            t["volume_id"], t["pagina"] = b.volume_id, b.pagina
    return out


def _itens_raiz(arv, trechos):
    itens = [{"tipo": "no", "no": r, "ordem_ini": r.ordem_ini} for r in arv.raizes] + trechos
    return sorted(itens, key=lambda i: i["ordem_ini"])


# ================================================================== estrutura
@exige_edicao()
def estrutura(request, slug):
    nova = _nova(slug)
    arv, ordens = _arvore_enriquecida(nova)
    foco = request.GET.get("foco", "")
    alvo = arv.por_id.get(foco)
    while alvo is not None and alvo.pai_obj is not None:  # abre as teses do pai do foco
        alvo.pai_obj.abre = True
        alvo = alvo.pai_obj
    trechos = _trechos_soltos(nova, arv, ordens)
    itens = _itens_raiz(arv, trechos)
    plano = partes.plano_partes(nova)  # o painel de partes só aparece na nova (edicao.reorganiza)
    painel = []
    for r, nome in enumerate(partes.ORDEM_PARTES):
        achadas = plano["identificadas"].get(r, [])
        painel.append({"rank": r, "nome": nome, "nos": achadas, "falta": not achadas})
    def nome_parte(p):
        r = plano["rank"][p.pk]
        return partes.ORDEM_PARTES[r] if r is not None else f"{(p.titulo or p.xml_id).title()} (segue a anterior)"

    ordem_atual = [(nome_parte(p), p) for p in plano["partes"]]
    volumes = {v.pk: v.numero for v in Volume.objects.all()}
    for t in trechos:
        t["vol"] = volumes.get(t["volume_id"])
    contagem = dict(Bloco.objects.filter(edicao=nova).values_list("procedencia").annotate(n=Count("id")))
    return render_area(request, "nova/estrutura.html", {
        "nova": nova, "itens": itens, "arv": arv, "painel": painel, "faltam": plano["faltam"],
        "faltam_nomes": [partes.ORDEM_PARTES[r] for r in plano["faltam"]],
        "completo": not plano["faltam"], "na_ordem": plano["na_ordem"],
        "ordem_atual": ordem_atual, "alvo": [(nome_parte(p), p) for p in plano["alvo"]],
        "total_blocos": len(ordens), "contagem": contagem, "foco": foco,
        "ordem_alvo": partes.ORDEM_PARTES})


def _redirect_estrutura(nova, xml_id=None):
    url = reverse("obra:nova_estrutura", args=[nova.slug])
    if xml_id:
        url += f"?foco={xml_id}#no-{xml_id}"
    return redirect(url)


def _no_ou_404(nova, xml_id):
    return get_object_or_404(No, edicao=nova, xml_id=xml_id)


@exige_edicao()
@require_POST
def aplicar_ordem(request, slug):
    nova = _reorganizavel(slug)
    t0 = time.perf_counter()
    try:
        servicos_nova.aplicar_ordem_partes(nova, autor=request.user)
    except servicos.ErroOperacao as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Partes reordenadas ({time.perf_counter() - t0:.1f} s): "
                                  + " › ".join(partes.ORDEM_PARTES) + ".")
    return _redirect_estrutura(nova)


@exige_edicao()
@require_POST
def acao_no(request, slug, xml_id):
    """subir | descer | suprimir | restaurar (POST de formulário; volta à mesma posição da árvore)."""
    nova = _reorganizavel(slug)
    no = _no_ou_404(nova, xml_id)
    acao = request.POST.get("acao", "")
    try:
        if acao in ("subir", "descer"):
            irmaos = list(No.objects.filter(edicao=nova, pai_id=no.pai_id, nivel=no.nivel).order_by("ordem_ini"))
            i = [x.pk for x in irmaos].index(no.pk)
            if acao == "subir" and i > 0:
                servicos.mover_no(no, antes_de=irmaos[i - 1], autor=request.user)
            elif acao == "descer" and i + 1 < len(irmaos):
                servicos.mover_no(no, depois_de=irmaos[i + 1], autor=request.user)
            else:
                messages.info(request, "O nó já está no limite.")
                return _redirect_estrutura(nova, xml_id)
            messages.success(request, f"Movido: {arvore_titulo(no)}.")
        elif acao in ("suprimir", "restaurar"):
            n = servicos_nova.definir_supressao(
                nova, no.ordem_ini, no.ordem_fim, acao == "suprimir", autor=request.user)
            messages.success(request, f"{'Suprimido' if acao == 'suprimir' else 'Restaurado'}: "
                                      f"{arvore_titulo(no)} ({n} bloco{'s' if n != 1 else ''}).")
        else:
            messages.error(request, "Ação desconhecida.")
    except servicos.ErroOperacao as e:
        messages.error(request, str(e))
    return _redirect_estrutura(nova, xml_id)


def arvore_titulo(no):
    return leitura.titulo_do_no(no)


@exige_edicao()
@require_http_methods(["GET", "POST"])
def mover(request, slug, xml_id):
    """Formulário "mover para…": antes/depois de outro nó do mesmo nível, ou dentro de um nó de nível superior."""
    nova = _reorganizavel(slug)
    no = _no_ou_404(nova, xml_id)
    niveis = list(arvore.esquema.NIVEIS_ORDEM)
    todos = list(No.objects.filter(edicao=nova).order_by("ordem_ini"))
    fora = [n for n in todos if not (no.ordem_ini <= n.ordem_ini < no.ordem_fim)]
    iguais = [n for n in fora if n.nivel == no.nivel]
    superiores = [n for n in fora if niveis.index(n.nivel) < niveis.index(no.nivel)]
    if no.nivel != "parte":  # sem trocar de volume: o OCR/scan do volume define a continuidade da árvore
        iguais = [n for n in iguais if n.volume_id == no.volume_id]
        superiores = [n for n in superiores if n.volume_id == no.volume_id]
    if request.method == "POST":
        alvo = next((n for n in todos if str(n.pk) == request.POST.get("alvo")), None)
        modo = request.POST.get("modo")
        try:
            if alvo is None or alvo not in iguais + superiores:
                raise servicos.ErroOperacao("Escolha um destino válido.")
            if modo == "antes":
                servicos.mover_no(no, antes_de=alvo, autor=request.user)
            elif modo == "depois":
                servicos.mover_no(no, depois_de=alvo, autor=request.user)
            elif modo == "dentro":
                servicos.mover_no(no, para_pai=alvo, autor=request.user)
            else:
                raise servicos.ErroOperacao("Escolha a posição (antes, depois ou dentro).")
        except servicos.ErroOperacao as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"Movido: {arvore_titulo(no)}.")
            return _redirect_estrutura(nova, xml_id)
    return render_area(request, "nova/mover.html", {
        "nova": nova, "no": no, "iguais": iguais, "superiores": superiores,
        "titulo_no": arvore_titulo(no)})


# =============================================================== editor de trecho
def _volumes_paginas():
    """{numero: [[seq, impressa], ...]} para o visualizador de scan (anterior/próxima)."""
    out = {}
    for numero, seq, imp in (Pagina.objects.order_by("volume__numero", "seq")
                             .values_list("volume__numero", "seq", "impressa")):
        out.setdefault(numero, []).append([seq, imp or str(seq)])
    return out


def info_nova(blocos, volumes, impressas):
    info = {}
    for b in blocos:
        info[str(b.pk)] = {
            "versao": b.versao,
            "autor": nome_de(b.atualizado_por),
            "em": _fmt_data(b.atualizado_em) if b.atualizado_por_id else "",
            "procedencia": b.procedencia,
            "origem": b.origem_id,
            "volume": volumes.get(b.volume_id),
            "pagina": b.pagina,
            "impressa": impressas.get((b.volume_id, b.pagina), "") if b.pagina is not None else "",
        }
    return info


def _blocos_por_ids(ids):
    return list(Bloco.objects.filter(pk__in=ids).select_related("atualizado_por").order_by("ordem"))


def _payload(blocos):
    volumes = {v.pk: v.numero for v in Volume.objects.all()}
    return {"html": tei.blocos_para_html(blocos), "xml": tei.blocos_para_texto_xml(blocos),
            "ids": [b.pk for b in blocos], "info": info_nova(blocos, volumes, leitura.impressas())}


def _tela_editor(request, nova, *, blocos_qs, base_url, cabecalho, no=None, ordem_ini=None, vizinhos=None):
    arv = leitura.Arvore(nova)
    ordens = list(blocos_qs.values_list("ordem", flat=True))
    total = len(ordens)
    n_telas = max(1, ceil(total / POR_TELA))
    try:
        p = min(max(int(request.GET.get("p", 1)), 1), n_telas)
    except ValueError:
        p = 1
    fatia = ordens[(p - 1) * POR_TELA:p * POR_TELA]
    if not fatia:
        raise Http404("Sem blocos neste trecho.")
    blocos = list(Bloco.objects.filter(edicao=nova, ordem__gte=fatia[0], ordem__lte=fatia[-1])
                  .select_related("atualizado_por", "origem").order_by("ordem"))
    volumes = {v.pk: v.numero for v in Volume.objects.all()}
    imp = leitura.impressas()
    # --- texto de 1916 (somente leitura), um bloco por bloco da tela
    origens = [b.origem for b in blocos if b.origem_id]
    html_1916, notas_1916 = leitura.renderizar(origens, impressas_=imp, modo="web", prefixo_id="o")
    # --- sub-nós: em que tela cada um começa
    subnos = []
    if no is not None:
        for n in arv.nos:
            if n.pk != no.pk and no.ordem_ini <= n.ordem_ini < no.ordem_fim and len(subnos) < 500:
                tela = bisect_left(ordens, n.ordem_ini) // POR_TELA + 1
                subnos.append({"xml_id": n.xml_id, "nivel": n.nivel, "tela": tela,
                               "texto": leitura.titulo_do_no(n)[:70]})
    primeiro = blocos[0]
    cobre = arv.cobrindo(primeiro.ordem)
    caminho = [leitura.titulo_do_no(c) for c in arv.caminho(cobre)] if cobre else []
    dados = {
        **_payload(blocos),
        "pagina": ({"n": primeiro.pagina, "facs": f"paginas/{format(abs(primeiro.pagina), '04d')}.png"}
                   if primeiro.pagina is not None else None),
        "prefixoId": "n.",
        "tela": p, "telas": n_telas, "total": total, "base": base_url,
        "subnos": subnos,
        "urlConverter": reverse("obra:converter"),
        "urlGravar": reverse("obra:nova_gravar", args=[nova.slug]),
        "urlAcaoBloco": reverse("obra:nova_bloco_acao", args=[nova.slug]),
        "urlHistoricoBloco": reverse("obra:historico_bloco", args=[0]),
        "urlRevisar": reverse("obra:revisar", args=[9991, 9992]),
        "urlScan": reverse("obra:scan_jpg", args=[9991, 9992]) + "?l=1600",
        "urlScanOriginal": reverse("obra:scan", args=[9991, 9992]),
        "urlEstrutura": reverse("obra:nova_estrutura", args=[nova.slug]),
        "paginas": _volumes_paginas(),
        "csrf": get_token(request),
        "chaveLocal": f"sinibaldi.{nova.slug}",
    }
    return render_area(request, "nova/editor.html", {
        "nova": nova, "dados": dados, "esquema": esquema_para_cliente(), "cabecalho": cabecalho,
        "html_1916": html_1916, "notas_1916": notas_1916, "tela": p, "telas": n_telas, "total": total,
        "n_blocos": len(blocos), "base_url": base_url, "no": no, "subnos": subnos, "caminho": caminho,
        "vizinhos": vizinhos or {}, "tem_ant": p > 1, "tem_seg": p < n_telas,
        "ini_tela": (p - 1) * POR_TELA + 1, "fim_tela": (p - 1) * POR_TELA + len(fatia)})


@exige_edicao()
def editar_no(request, slug, xml_id):
    nova = _nova(slug)
    no = _no_ou_404(nova, xml_id)
    ant = arvore.no_anterior(no, mesmo_nivel=True)
    seg = arvore.no_proximo(no, mesmo_nivel=True)
    return _tela_editor(
        request, nova, blocos_qs=arvore.blocos_do_no(no), base_url=reverse("obra:nova_no", args=[nova.slug, xml_id]),
        cabecalho={"titulo": leitura.titulo_do_no(no), "nivel": no.get_nivel_display(), "xml_id": no.xml_id},
        no=no, vizinhos={
            "ant": {"url": reverse("obra:nova_no", args=[nova.slug, ant.xml_id]), "texto": leitura.titulo_do_no(ant)} if ant else None,
            "seg": {"url": reverse("obra:nova_no", args=[nova.slug, seg.xml_id]), "texto": leitura.titulo_do_no(seg)} if seg else None})


@exige_edicao()
def editar_trecho(request, slug, ordem_ini):
    nova = _nova(slug)
    arv, ordens = _arvore_enriquecida(nova)
    if arv.cobrindo(ordem_ini) is not None:
        raise Http404("Esse trecho pertence a um nó da árvore.")
    trechos = _trechos_soltos(nova, arv, ordens)
    t = next((x for x in trechos if x["ordem_ini"] <= ordem_ini < x["ordem_fim"]), None)
    if t is None:
        raise Http404("Trecho não encontrado.")
    itens = _itens_raiz(arv, trechos)
    i = next(k for k, it in enumerate(itens) if it["tipo"] == "trecho" and it["ordem_ini"] == t["ordem_ini"])

    def ligacao(it):
        if it is None:
            return None
        if it["tipo"] == "no":
            return {"url": reverse("obra:nova_no", args=[nova.slug, it["no"].xml_id]), "texto": leitura.titulo_do_no(it["no"])}
        return {"url": reverse("obra:nova_trecho", args=[nova.slug, it["ordem_ini"]]), "texto": "trecho sem parte"}

    qs = Bloco.objects.filter(edicao=nova, ordem__gte=t["ordem_ini"], ordem__lt=t["ordem_fim"]).order_by("ordem")
    return _tela_editor(
        request, nova, blocos_qs=qs, base_url=reverse("obra:nova_trecho", args=[nova.slug, t["ordem_ini"]]),
        cabecalho={"titulo": "Trecho sem parte", "nivel": "fora da árvore", "xml_id": ""},
        vizinhos={"ant": ligacao(itens[i - 1]) if i else None,
                  "seg": ligacao(itens[i + 1]) if i + 1 < len(itens) else None})


@exige_edicao(api=True)
@require_POST
def gravar(request, slug):
    """Grava os blocos de UMA tela do editor (escopo `ids`) na edição nova."""
    nova = _nova(slug)
    dados = _json_corpo(request)
    if dados is None:
        return _erro_json("Requisição inválida (JSON esperado).")
    ids = dados.get("ids", [])
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
        return _erro_json("`ids` deve ser uma lista não vazia de inteiros.")
    comentario = str(dados.get("comentario") or "")[:2000]
    try:
        novos = blocos_do_conteudo(dados.get("formato"), dados.get("conteudo", ""))
        res = servicos.salvar_blocos(nova, ids, novos, autor=request.user, comentario=comentario)
    except servicos.ErroValidacao as e:
        return _erro_json(e.erros)
    except servicos.Conflito as e:
        quem = ", ".join(sorted({nome_de(b.atualizado_por) or "outra pessoa"
                                 for b in Bloco.objects.filter(pk__in=e.ids).select_related("atualizado_por")}))
        return JsonResponse({
            "conflito": True, "ids": e.ids,
            "erros": [f"Conflito: {'o bloco' if len(e.ids) == 1 else 'os blocos'} "
                      f"{', '.join('#%d' % i for i in e.ids)} foi alterado por {quem or 'outra pessoa'} depois que "
                      "você abriu esta tela. Recarregue para ver a versão atual (copie antes o seu texto)."]}, status=409)
    blocos = _blocos_por_ids([b.pk for b in res.blocos])
    return JsonResponse({
        "ok": True, "alterou": res.alterou, "estrutura_mudou": res.arvore_reconstruida,
        "resumo": {"criados": res.criados, "editados": res.editados, "removidos": res.removidos, "movidos": res.movidos},
        "lote": str(res.lote), **_payload(blocos)})


@exige_edicao(api=True)
@require_POST
def acao_bloco(request, slug):
    """`{acao: restaurar_1916|suprimir|restaurar_supressao, bloco, ids}` -> a tela recarregada (como gravar)."""
    nova = _nova(slug)
    d = _json_corpo(request)
    if d is None:
        return _erro_json("Requisição inválida (JSON esperado).")
    ids, pk, acao = d.get("ids"), d.get("bloco"), d.get("acao")
    if not (isinstance(ids, list) and all(isinstance(i, int) for i in ids) and isinstance(pk, int) and pk in ids):
        return _erro_json("Informe `bloco` e os `ids` da tela.")
    bloco = Bloco.objects.filter(pk=pk, edicao=nova).first()
    if bloco is None:
        return _erro_json(f"Bloco não encontrado na edição {nova.titulo.lower()}.", 404)
    try:
        if acao == "restaurar_1916":
            if bloco.origem_id is None:
                return _erro_json("Este bloco não tem origem na edição de 1916.")
            servicos_nova.restaurar_texto_1916(nova, [pk], autor=request.user)
        elif acao in ("suprimir", "restaurar_supressao"):
            if not nova.reorganiza:
                return _erro_json("Esta edição não suprime trechos.")
            servicos_nova.definir_supressao(nova, bloco.ordem, bloco.ordem + 1, acao == "suprimir", autor=request.user)
        else:
            return _erro_json("Ação desconhecida.")
    except servicos.ErroOperacao as e:
        return _erro_json(str(e))
    blocos = _blocos_por_ids([i for i in ids if Bloco.objects.filter(pk=i, edicao=nova).exists()])
    return JsonResponse({"ok": True, "acao": acao, **_payload(blocos)})


# ===================================================== resumo para o painel
def resumo_nova(slug=SLUG_NOVA):
    """Dados do cartão de uma edição derivada no painel (None se a edição não existir)."""
    nova = Edicao.objects.filter(slug=slug, tipo__in=Edicao.DERIVADAS).first()
    if nova is None:
        return None
    cont = dict(Bloco.objects.filter(edicao=nova).values_list("procedencia").annotate(n=Count("id")))
    total = sum(cont.values())
    plano = partes.plano_partes(nova) if nova.reorganiza else None
    return {
        "edicao": nova, "total": total,
        "procedencias": [(PROCEDENCIA_ROTULO[k], k, cont.get(k, 0)) for k in PROCEDENCIA_ROTULO
                         if nova.reorganiza or k != Bloco.SUPRIMIDO],
        "pendentes": {"copias": servicos_nova.copias_desatualizadas(nova).count(),
                      "adaptados": servicos_nova.adaptados_pendentes(nova).count(),
                      "cobertura": servicos_nova.sem_correspondente(nova).count()},
        "faltam": [partes.ORDEM_PARTES[r] for r in plano["faltam"]] if plano else [],
        "na_ordem": plano["na_ordem"] if plano else True,
    }


def resumos_derivadas():
    """Cartões do painel: atualizada e depois nova (as que existirem)."""
    return [r for r in (resumo_nova(SLUG_ATUALIZADA), resumo_nova(SLUG_NOVA)) if r]


# ================================================================== pendências
ABAS = [("copias", "Cópias desatualizadas"), ("adaptados", "Adaptados com origem alterada"),
        ("cobertura", "Cobertura da 1916")]


@exige_edicao()
def pendencias(request, slug):
    nova = _nova(slug)
    aba = request.GET.get("aba", "copias")
    if aba not in dict(ABAS):
        aba = "copias"
    contagens = {
        "copias": servicos_nova.copias_desatualizadas(nova).count(),
        "adaptados": servicos_nova.adaptados_pendentes(nova).count(),
        "cobertura": servicos_nova.sem_correspondente(nova).count(),
    }
    volumes = {v.pk: v.numero for v in Volume.objects.all()}
    imp = leitura.impressas()
    itens = []
    if aba == "copias":
        qs = servicos_nova.copias_desatualizadas(nova).select_related("origem")
    elif aba == "adaptados":
        qs = servicos_nova.adaptados_pendentes(nova)
    else:
        qs = servicos_nova.sem_correspondente(nova)
    page_obj = Paginator(qs, POR_LISTA).get_page(request.GET.get("page"))
    lista = list(page_obj)
    revisoes = {}
    if aba == "adaptados":
        for r in (Revisao.objects.filter(bloco_id__in=[b.origem_id for b in lista], acao=Revisao.EDITAR)
                  .select_related("autor").order_by("criado_em")):
            revisoes.setdefault(r.bloco_id, []).append(r)
    for b in lista:
        item = {"bloco": b, "vol": volumes.get(b.volume_id), "impressa": imp.get((b.volume_id, b.pagina), "")
                if b.pagina is not None else ""}
        if aba == "copias":
            item["diff"] = diffs.diff_html(b.xml, b.origem.xml)
            item["no"] = _no_do_bloco(nova, b)
        elif aba == "adaptados":
            item["diff"] = diffs.diff_html(b.origem.xml, b.xml)
            item["mudancas"] = [
                {"rev": r, "diff": diffs.diff_html(r.xml_antes, r.xml_depois)}
                for r in revisoes.get(b.origem_id, []) if r.criado_em > b.atualizado_em][-4:]
            item["no"] = _no_do_bloco(nova, b)
        else:
            item["amostra"] = leitura.texto_plano(b.xml, notas=False)[:160]
        itens.append(item)
    return render_area(request, "nova/pendencias.html", {
        "nova": nova, "aba": aba, "abas": ABAS, "contagens": contagens, "itens": itens, "page_obj": page_obj,
        "querystring": f"aba={aba}&"})


def _no_do_bloco(nova, bloco):
    """Link para a tela do editor que contém o bloco (nó mais profundo que não seja tese, ou o trecho)."""
    no = (No.objects.filter(edicao=nova, ordem_ini__lte=bloco.ordem, ordem_fim__gt=bloco.ordem)
          .order_by("-ordem_ini").first())
    if no is None:
        return None
    return no


@exige_edicao()
@require_POST
def acao_pendencias(request, slug):
    nova = _nova(slug)
    acao = request.POST.get("acao", "")
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    aba = request.POST.get("aba", "copias")
    t0 = time.perf_counter()
    try:
        if acao == "atualizar_todas":
            n = servicos_nova.atualizar_copias(nova, autor=request.user)
            messages.success(request, f"{n} cópia{'s' if n != 1 else ''} atualizada{'s' if n != 1 else ''} "
                                      f"a partir da edição de 1916 ({time.perf_counter() - t0:.1f} s).")
        elif acao == "atualizar":
            n = servicos_nova.atualizar_copias(nova, ids=ids, autor=request.user)
            messages.success(request, f"{n} cópia{'s' if n != 1 else ''} atualizada{'s' if n != 1 else ''}.")
        elif acao == "visto":
            n = servicos_nova.marcar_origem_vista(nova, ids, autor=request.user)
            messages.success(request, f"{n} bloco{'s' if n != 1 else ''} marcado{'s' if n != 1 else ''} como visto{'s' if n != 1 else ''}.")
        else:
            messages.error(request, "Ação desconhecida.")
    except servicos.ErroOperacao as e:
        messages.error(request, str(e))
    return redirect(reverse("obra:nova_pendencias", args=[nova.slug]) + f"?aba={aba}")
