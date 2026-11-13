"""Citações: o texto (`<quote>`/`<bibl>` nos blocos) e os dados (`Citacao`) andam juntos.

* `indexar_blocos(blocos)` — chamada por `servicos.salvar_blocos` depois de cada gravação: cria a
  `Citacao` de todo `<quote xml:id>` novo e atualiza `tipo`, `texto`, `referencia_autor`, `ativa` e
  a localização (volume e página do scan onde o 1º segmento está; a da 1916 prevalece);
* `reindexar()` — o mesmo para as duas edições inteiras, marcando `ativa=False` nas que sumiram;
* `marcar_edicao(edicao, aplicar)` — reconhecimento automático pelas aspas (`citacoes.marcar`) em
  todos os blocos de uma edição, gravando por `servicos.salvar_blocos` (com `Revisao`);
* `localizar(xml_id)` — onde a citação está em cada edição (bloco, página impressa).
"""
import logging
import re

from django.db import transaction
from lxml import etree

from . import citacoes, esquema, leitura
from .models import Bloco, Citacao, Edicao

logger = logging.getLogger(__name__)
COMENTARIO = "Citações reconhecidas pelas aspas (marcar_citacoes)."
_RE_ID = re.compile(r'xml:id="([^"]*cit-[^"]*)"')


def ids_em_uso():
    """Todos os xml:id de citação já usados (texto das duas edições + cadastro)."""
    usados = set(Citacao.objects.values_list("xml_id", flat=True))
    for xml in Bloco.objects.filter(xml__contains="cit-").values_list("xml", flat=True).iterator(chunk_size=1000):
        usados.update(_RE_ID.findall(xml))
    return usados


def gerador(volume_numero=None, usados=None):
    prefixo = f"v{volume_numero}." if volume_numero else ""
    return citacoes.gerador_de_ids(prefixo, ids_em_uso() if usados is None else usados)


def _pagina_do_segmento(raiz, alvo, inicial):
    """seq da página onde `alvo` começa: o último <pb> antes dele (os de notas só contam dentro da
    própria nota do alvo)."""
    nota_do_alvo = next((a for a in alvo.iterancestors() if a.tag == "note"), None)
    pagina = inicial
    for e in raiz.iter():
        if e is alvo:
            return pagina
        if e.tag == "pb":
            nota = next((a for a in e.iterancestors() if a.tag == "note"), None)
            if nota is None or nota is nota_do_alvo:
                try:
                    pagina = int(e.get("n"))
                except (TypeError, ValueError):
                    pass
    return pagina


def _dados_do_bloco(bloco):
    """[(xml_id, Ocorrencia, seq da página do 1º segmento | None)] das citações com dados do bloco."""
    if "<quote" not in bloco.xml and "<bibl" not in bloco.xml:
        return []
    try:
        raiz = etree.fromstring(bloco.xml.encode("utf-8"))
    except etree.XMLSyntaxError:
        return []
    out = []
    for k, oc in citacoes.ocorrencias(raiz).items():
        cabeca = next((s for s in oc.segmentos if s.get(citacoes.XML_ID)), None)
        if cabeca is None or oc.tipo not in esquema.TIPOS_COM_DADOS:
            continue
        out.append((k, oc, _pagina_do_segmento(raiz, cabeca, bloco.pagina)))
    return out


def indexar_blocos(blocos):
    """Cria/atualiza as `Citacao` das citações destes blocos. -> número de citações tocadas."""
    blocos = [b for b in blocos if b.procedencia != Bloco.SUPRIMIDO]
    achados = []
    for b in blocos:
        for k, oc, seq in _dados_do_bloco(b):
            achados.append((b, k, oc, seq))
    if not achados:
        return 0
    tipos_ed = dict(Edicao.objects.values_list("pk", "tipo"))
    existentes = {c.xml_id: c for c in Citacao.objects.filter(xml_id__in=[k for _, k, _, _ in achados])}
    n = 0
    with transaction.atomic():
        for b, k, oc, seq in achados:
            c = existentes.get(k)
            novo = c is None
            if novo:
                c = existentes[k] = Citacao(xml_id=k)
            da_1916 = tipos_ed.get(b.edicao_id) == Edicao.DIPLOMATICA
            # o texto e a localização da 1916 prevalecem; a nova só preenche o que falta
            if novo or da_1916 or not c.texto:
                c.texto = oc.texto[:20000]
                c.referencia_autor = oc.referencia_autor[:400]
                c.tipo = oc.tipo
                if da_1916 or c.pagina is None:
                    c.volume_id, c.pagina = b.volume_id, seq
            c.ativa = True
            c.save()
            n += 1
    return n


def reindexar():
    """Indexa as duas edições inteiras; `ativa=False` nas citações que não estão em bloco nenhum.
    -> (indexadas, inativadas)."""
    vistos = set()
    n = 0
    lote = []
    qs = (Bloco.objects.filter(xml__contains="<quote").exclude(procedencia=Bloco.SUPRIMIDO)
          .order_by("-edicao__tipo", "ordem"))   # "nova" > "diplomatica": a 1916 por último prevalece
    for b in qs.iterator(chunk_size=500):
        lote.append(b)
        vistos.update(k for k, _, _ in _dados_do_bloco(b))
        if len(lote) >= 500:
            n += indexar_blocos(lote)
            lote = []
    n += indexar_blocos(lote)
    inativas = Citacao.objects.filter(ativa=True).exclude(xml_id__in=vistos).update(ativa=False)
    return n, inativas


def localizar(xml_id):
    """[{edicao, bloco, volume, seq, impressa}] — onde a citação está, por edição."""
    imp = leitura.impressas()
    out = []
    qs = (Bloco.objects.filter(xml__contains=xml_id).exclude(procedencia=Bloco.SUPRIMIDO)
          .select_related("edicao", "volume").order_by("edicao__tipo", "ordem"))
    for b in qs:
        for k, oc, seq in _dados_do_bloco(b):
            if k == xml_id:
                out.append({"edicao": b.edicao, "bloco": b, "volume": b.volume, "seq": seq,
                            "impressa": imp.get((b.volume_id, seq), str(seq) if seq is not None else ""),
                            "ocorrencia": oc})
    return out


# ------------------------------------------------------------------- marcação em lote
def marcar_blocos(blocos, novo_id_de):
    """Detecta as citações de cada bloco. -> [(bloco, xml_novo, Relatorio)] só dos que mudam.
    `novo_id_de(bloco)` devolve o gerador de ids para o volume do bloco."""
    out = []
    for b in blocos:
        if b.tipo not in (Bloco.PARAGRAFO, Bloco.SUMARIO) or b.procedencia == Bloco.SUPRIMIDO:
            continue
        if not any(c in b.xml for c in "«»“”„\""):
            continue
        novo, rel = citacoes.marcar_xml(b.xml, novo_id_de(b))
        if rel.total and novo != b.xml:
            out.append((b, novo, rel))
    return out


def marcar_edicao(edicao, aplicar=False, autor=None, volume=None, so_estes=None):
    """Reconhecimento automático em uma edição. -> (Relatorio somado, [(bloco, xml_novo)]).

    Na nova só os blocos `adaptado`/`novo` são examinados: as cópias recebem o xml marcado da origem
    (mesmos ids) por `propagar_para_nova`, e a citação continua uma só nas duas edições."""
    from . import servicos

    usados = ids_em_uso()
    geradores = {}

    def novo_id_de(b):
        n = b.volume.numero if b.volume_id else None
        if n not in geradores:
            geradores[n] = gerador(n, usados)
        return geradores[n]

    qs = Bloco.objects.filter(edicao=edicao).select_related("volume").order_by("ordem")
    if edicao.tipo == Edicao.NOVA:
        qs = qs.filter(procedencia__in=(Bloco.ADAPTADO, Bloco.NOVO))
    if volume is not None:
        qs = qs.filter(volume__numero=volume)
    if so_estes is not None:
        qs = qs.filter(pk__in=so_estes)
    total, alterados = citacoes.Relatorio(), []
    for b, novo, rel in marcar_blocos(list(qs), novo_id_de):
        total += rel
        alterados.append((b, novo))
        if aplicar:
            servicos.salvar_blocos(edicao, [b.pk], [{"id": b.pk, "versao": b.versao, "xml": novo}], autor,
                                   COMENTARIO, volume=b.volume_id, pagina=b.pagina)
    return total, alterados


def propagar_para_nova(alterados_1916, autor=None, aplicar=False):
    """Cópias exatas (na nova) dos blocos da 1916 recém-marcados recebem o xml marcado. -> quantas."""
    from . import servicos_nova

    antigos = {b.pk: b.xml for b, _ in alterados_1916}   # xml de antes da marcação
    ids = [b.pk for b in Bloco.objects.filter(edicao__tipo=Edicao.NOVA, procedencia=Bloco.COPIA,
                                               origem_id__in=list(antigos)).only("pk", "xml", "origem_id")
           if antigos.get(b.origem_id) == b.xml]
    if aplicar and ids:
        nova = Edicao.objects.filter(tipo=Edicao.NOVA).first()
        servicos_nova.atualizar_copias(nova, ids, autor)
    return len(ids)
