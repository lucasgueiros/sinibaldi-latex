"""Árvore de nós derivada dos blocos `marco` (cache de navegação).

Faixa de um nó: `ordem_ini <= Bloco.ordem < ordem_fim` (fim EXCLUSIVO). O fim é a
`ordem` do bloco que encerra o nó (próximo marco de nível <= ao do nó, ou o primeiro
bloco de outro volume); o último nó de uma sequência usa `ORDEM_MAX`.
"""
import re

from django.db import transaction
from lxml import etree

from . import esquema
from .models import Bloco, No

ORDEM_MAX = 2 ** 62
_ESPACOS = re.compile(r"\s+")


def _texto(el, excluir=("note", "pb", "fw")):
    partes = []

    def rec(e):
        if e.text:
            partes.append(e.text)
        for c in e:
            if isinstance(c.tag, str) and c.tag not in excluir:
                rec(c)
            if c.tail:
                partes.append(c.tail)

    rec(el)
    return _ESPACOS.sub(" ", "".join(partes)).strip()


def _titulo_da_tese(xml, limite=80):
    raiz = etree.fromstring(xml.encode("utf-8"))
    b = next((e for e in raiz.iter("hi") if e.get("rend") == "bold"), None)
    if b is None:
        return ""
    t = _texto(b).rstrip(" .—-")
    return t if len(t) <= limite else t[: limite - 1].rstrip() + "…"


def _unico(xml_id, usados, ordem):
    base = xml_id or f"no-{ordem}"
    cand, i = base, 1
    while cand in usados:
        i += 1
        cand = f"{base}-{i}"
    usados.add(cand)
    return cand


@transaction.atomic
def reconstruir(edicao):
    """Recria todos os `No` da edição a partir dos blocos (inserção em lote). Retorna a lista de nós."""
    No.objects.filter(edicao=edicao).delete()
    ultimo = No.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
    prox_pk = ultimo + 1
    niveis = esquema.NIVEIS_ORDEM
    nos = []            # dicts na ordem de criação
    pilha = []          # nós abertos
    irmaos = {}         # id(pai) -> contador
    usados = set()
    anterior = None     # (ordem, pagina, volume_id) do bloco anterior
    pend = None         # nó cujo cabeçalho ainda está sendo lido
    vol_atual = None

    def fechar(no, ordem_fim, pag):
        no["ordem_fim"] = ordem_fim
        no["pagina_fim"] = pag

    qs = (Bloco.objects.filter(edicao=edicao).order_by("ordem")
          .values_list("pk", "ordem", "tipo", "xml", "volume_id", "pagina").iterator(chunk_size=2000))
    for pk, ordem, tipo, xml, vol, pag in qs:
        if vol is not None and vol_atual is not None and vol != vol_atual:
            while pilha:
                fechar(pilha.pop(), ordem, anterior[1] if anterior else pag)
            pend = None
        if vol is not None:
            vol_atual = vol
        if tipo == Bloco.MARCO:
            raiz = etree.fromstring(xml.encode("utf-8"))
            nivel = raiz.get("unit")
            idx = niveis.index(nivel)
            while pilha and niveis.index(pilha[-1]["nivel"]) >= idx:
                fechar(pilha.pop(), ordem, anterior[1] if anterior else pag)
            pai = pilha[-1] if pilha else None
            chave = pai["pk"] if pai else None
            irmaos[chave] = irmaos.get(chave, -1) + 1
            no = dict(
                pk=prox_pk, pai_id=chave, nivel=nivel, n=raiz.get("n") or "",
                xml_id=_unico(raiz.get(esquema.qname_atributo("xml:id")), usados, ordem),
                rotulo="", titulo="", posicao=irmaos[chave], ordem_ini=ordem, ordem_fim=ORDEM_MAX,
                volume_id=vol, pagina_ini=pag, pagina_fim=pag, _heads=True, _primeiro_p=False,
            )
            prox_pk += 1
            nos.append(no)
            pilha.append(no)
            pend = no
        elif pend is not None:
            if tipo == Bloco.TITULO and pend["_heads"]:
                raiz = etree.fromstring(xml.encode("utf-8"))
                t = _texto(raiz)
                if raiz.get("type") == "rotulo":
                    pend["rotulo"] = (pend["rotulo"] + " " + t).strip()
                else:
                    pend["titulo"] = (pend["titulo"] + " " + t).strip() if pend["titulo"] else t
            elif tipo == Bloco.CABECALHO:
                pass
            else:
                pend["_heads"] = False
                if tipo == Bloco.PARAGRAFO and pend["nivel"] == "tese" and not pend["titulo"]:
                    pend["titulo"] = _titulo_da_tese(xml)
                pend = None
        anterior = (pk, pag)
    # fecha o que sobrou: vai até o fim
    for no in pilha:
        no["ordem_fim"] = ORDEM_MAX
    objs = []
    for no in nos:
        rotulo = no["rotulo"] or (f"{esquema.NIVEIS[no['nivel']]} {no['n']}".strip() if no["n"] else "")
        objs.append(No(
            pk=no["pk"], edicao=edicao, pai_id=no["pai_id"], nivel=no["nivel"], n=no["n"][:20],
            xml_id=no["xml_id"][:80], rotulo=rotulo[:200], titulo=no["titulo"][:300], posicao=no["posicao"],
            ordem_ini=no["ordem_ini"], ordem_fim=no["ordem_fim"], volume_id=no["volume_id"],
            pagina_ini=no["pagina_ini"], pagina_fim=no["pagina_fim"],
        ))
    No.objects.bulk_create(objs, batch_size=500)
    return objs


def blocos_do_no(no):
    """QuerySet ordenado dos blocos do nó (inclui os dos descendentes)."""
    return Bloco.objects.filter(edicao_id=no.edicao_id, ordem__gte=no.ordem_ini, ordem__lt=no.ordem_fim).order_by("ordem")


def no_anterior(no, mesmo_nivel=True):
    """Nó imediatamente anterior em ordem de leitura (por padrão, do mesmo nível), ou None."""
    qs = No.objects.filter(edicao_id=no.edicao_id, ordem_ini__lt=no.ordem_ini)
    if mesmo_nivel:
        qs = qs.filter(nivel=no.nivel)
    return qs.order_by("-ordem_ini").first()


def no_proximo(no, mesmo_nivel=True):
    qs = No.objects.filter(edicao_id=no.edicao_id, ordem_ini__gt=no.ordem_ini)
    if mesmo_nivel:
        qs = qs.filter(nivel=no.nivel)
    return qs.order_by("ordem_ini").first()


def caminho(no):
    """Lista de nós da raiz até `no` (inclusive)."""
    out = [no]
    while out[-1].pai_id:
        out.append(out[-1].pai)
    return out[::-1]
