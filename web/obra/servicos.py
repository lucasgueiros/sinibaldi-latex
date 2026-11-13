"""Operações de escrita sobre os blocos (sempre transacionais e com autoria)."""
import logging
import uuid
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Max, Min, Q
from django.utils import timezone
from lxml import etree

from . import arvore, esquema
from .models import PASSO_ORDEM, Bloco, Edicao, No, Pagina, Revisao


XML_ID = esquema.qname_atributo("xml:id")


logger = logging.getLogger(__name__)


class ErroValidacao(Exception):
    def __init__(self, erros):
        self.erros = list(erros)
        super().__init__("; ".join(self.erros))


class Conflito(Exception):
    """Alguém gravou os blocos depois que o editor os carregou."""

    def __init__(self, ids):
        self.ids = list(ids)
        super().__init__(f"Conflito de versão nos blocos {self.ids}.")


class ErroOperacao(Exception):
    """Operação não permitida (ex.: mover nó em edição diplomática)."""


@dataclass
class ResultadoSalvar:
    lote: uuid.UUID
    blocos: list = field(default_factory=list)   # Bloco, na ordem final do escopo
    criados: int = 0
    editados: int = 0
    removidos: int = 0
    movidos: int = 0
    arvore_reconstruida: bool = False

    @property
    def alterou(self):
        return bool(self.criados or self.editados or self.removidos or self.movidos)


# ---------------------------------------------------------------- consultas
def blocos_da_pagina(edicao, volume, seq):
    """Blocos que começam na página `seq` + os que a atravessam (têm <pb n="seq"> inline)."""
    cond = Q(pagina=seq) | Q(xml__contains=f'<pb n="{seq}" ')
    qs = Bloco.objects.filter(edicao=edicao, volume=volume).filter(cond).order_by("ordem")
    return list(qs)


# ------------------------------------------------------------------ ordem
def _renumerar(edicao):
    """Reatribui `ordem` com folga (PASSO_ORDEM) a toda a edição, preservando a sequência."""
    blocos = list(Bloco.objects.filter(edicao=edicao).order_by("ordem", "pk").only("pk", "ordem"))
    for i, b in enumerate(blocos, 1):
        b.ordem = i * PASSO_ORDEM
    Bloco.objects.bulk_update(blocos, ["ordem"], batch_size=500)


def _alocar(esq, dir_, k):
    """k ordens estritamente entre `esq` e `dir_` (None = aberto). None se não couber."""
    if dir_ is None:
        return [esq + PASSO_ORDEM * (j + 1) for j in range(k)]
    folga = dir_ - esq
    passo = folga // (k + 1)
    if passo < 1:
        return None
    return [esq + passo * (j + 1) for j in range(k)]


class _Recomecar(Exception):
    pass


# --------------------------------------------------------------- salvar
def _desduplicar_ids(novos):
    """Parágrafo dividido no editor: a 2ª metade repete o id do bloco E os xml:id do
    original. Nos blocos de id repetido, remove os xml:id já usados antes."""
    vistos_bloco, vistos_xml = set(), set()
    for n in novos:
        repetido = n.get("id") is not None and n["id"] in vistos_bloco
        if n.get("id") is not None:
            vistos_bloco.add(n["id"])
        if repetido:
            try:
                raiz = etree.fromstring(n["xml"].encode("utf-8"))
            except etree.XMLSyntaxError:
                continue
            for e in raiz.iter():
                if isinstance(e.tag, str) and e.get(XML_ID) in vistos_xml:
                    del e.attrib[XML_ID]
            n["xml"] = etree.tostring(raiz, encoding="unicode")
        vistos_xml.update(esquema.ids_do_fragmento(n["xml"]))


def salvar_blocos(edicao, ids_no_escopo, novos, autor, comentario="", volume=None, pagina=None, ancora=None):
    """Substitui os blocos do escopo pela lista ordenada `novos` ({id|None, versao|None, xml}).

    * valida tudo antes (ErroValidacao); versão divergente -> Conflito;
    * id repetido em `novos` (parágrafo dividido): o 2º vira bloco novo;
    * grava uma Revisao por bloco realmente alterado, todas com o mesmo `lote`;
    * `ancora`: pk do bloco APÓS o qual inserir, usado só quando o escopo é vazio
      (None = no fim da edição);
    * reconstrói a árvore se algum marco/título (ou o parágrafo logo após eles) mudou.
    """
    novos = [dict(n) if isinstance(n, dict) else {"id": n.id, "versao": n.versao, "xml": n.xml} for n in novos]
    _desduplicar_ids(novos)
    erros = esquema.validar_blocos(novos)
    if erros:
        raise ErroValidacao(erros)
    _verificar_ids_livres(edicao, list(ids_no_escopo), novos)
    try:
        res = _salvar(edicao, list(ids_no_escopo), novos, autor, comentario, volume, pagina, ancora, 0)
    except _Recomecar:
        with transaction.atomic():
            _renumerar(edicao)
        res = _salvar(edicao, list(ids_no_escopo), novos, autor, comentario, volume, pagina, ancora, 1)
    if res.alterou and any("<quote" in b.xml for b in res.blocos):
        from . import servicos_citacoes
        try:
            servicos_citacoes.indexar_blocos(res.blocos)
        except Exception:   # o texto já foi gravado; o cadastro se refaz com `marcar_citacoes --reindexar`
            logger.exception("Falha ao indexar as citações do lote %s", res.lote)
    return res


def _verificar_ids_livres(edicao, ids_no_escopo, novos):
    """Todo `xml:id` que surge agora (e não existia nos blocos do escopo) não pode existir em outro
    bloco da edição: a árvore renomearia o nó em silêncio."""
    antigos = set()
    for xml in Bloco.objects.filter(edicao=edicao, pk__in=ids_no_escopo).values_list("xml", flat=True):
        antigos.update(esquema.ids_do_fragmento(xml))
    erros = []
    for n in novos:
        for ident in esquema.ids_do_fragmento(n["xml"]):
            if ident in antigos:
                continue
            outro = (Bloco.objects.filter(edicao=edicao, xml__contains=f'xml:id="{ident}"')
                     .exclude(pk__in=ids_no_escopo).first())
            if outro is not None:
                erros.append(f"O xml:id '{ident}' já é usado em outro bloco da edição (bloco #{outro.pk}). "
                             "Escolha outro identificador.")
    if erros:
        raise ErroValidacao(erros)


@transaction.atomic
def _salvar(edicao, ids, novos, autor, comentario, volume, pagina, ancora, tentativa):
    existentes = {b.pk: b for b in Bloco.objects.select_for_update().filter(edicao=edicao, pk__in=ids)}
    faltam = [i for i in ids if i not in existentes]
    if faltam:
        raise ErroValidacao([f"Bloco {i} não existe nesta edição (removido por outra pessoa?)." for i in faltam])

    # --- casar `novos` com blocos existentes
    usados = set()
    pares = []  # (novo, bloco|None)
    conflitos = []
    for n in novos:
        b = None
        i = n.get("id")
        if i is not None and i in existentes and i not in usados:
            b = existentes[i]
            usados.add(i)
            if n.get("versao") is not None and n["versao"] != b.versao and n["xml"] != b.xml:
                conflitos.append(i)
        elif i is not None and i not in existentes and i not in usados:
            raise ErroValidacao([f"Bloco {i} fora do escopo informado."])
        pares.append((n, b))
    if conflitos:
        raise Conflito(conflitos)
    removidos = [b for i, b in existentes.items() if i not in usados]

    # --- limites da faixa
    if existentes:
        mn = min(b.ordem for b in existentes.values())
        mx = max(b.ordem for b in existentes.values())
        esq_base = Bloco.objects.filter(edicao=edicao, ordem__lt=mn).aggregate(m=Max("ordem"))["m"] or 0
        dir_base = Bloco.objects.filter(edicao=edicao, ordem__gt=mx).aggregate(m=Min("ordem"))["m"]
        viz = Bloco.objects.filter(edicao=edicao, ordem__lt=mn).order_by("-ordem").first()
    else:
        if ancora is not None:
            ref = Bloco.objects.filter(edicao=edicao, pk=ancora).first()
            if ref is None:
                raise ErroValidacao([f"Âncora {ancora} não existe."])
            esq_base = ref.ordem
            dir_base = Bloco.objects.filter(edicao=edicao, ordem__gt=ref.ordem).aggregate(m=Min("ordem"))["m"]
            viz = ref
        else:
            esq_base = Bloco.objects.filter(edicao=edicao).aggregate(m=Max("ordem"))["m"] or 0
            dir_base = None
            viz = Bloco.objects.filter(edicao=edicao).order_by("-ordem").first()

    # --- ordem final: mantém a ordem existente quando crescente, aloca o resto
    final = [None] * len(pares)
    ultimo = esq_base
    for idx, (n, b) in enumerate(pares):
        if b is not None and b.ordem > ultimo and (dir_base is None or b.ordem < dir_base):
            final[idx] = b.ordem
            ultimo = b.ordem
    idx = 0
    esq = esq_base
    while idx < len(pares):
        if final[idx] is not None:
            esq = final[idx]
            idx += 1
            continue
        j = idx
        while j < len(pares) and final[j] is None:
            j += 1
        dir_ = final[j] if j < len(pares) else dir_base
        slots = _alocar(esq, dir_, j - idx)
        if slots is None:
            if tentativa:
                raise RuntimeError("Não foi possível alocar ordens mesmo após renumerar.")
            raise _Recomecar()  # desfaz a transação; o chamador renumera e repete
        final[idx:j] = slots
        idx = j

    # --- aplicar
    lote = uuid.uuid4()
    agora = timezone.now()
    ed_nova = edicao.derivada  # nova ou atualizada: copia -> adaptado, bloco criado -> novo
    res = ResultadoSalvar(lote=lote)
    revisoes = []
    reconstruir = False
    vol_id = getattr(volume, "pk", volume)
    a_atualizar = []
    ordem_dos_modificados = []

    def rev(acao, bloco, antes, depois, vol, pag):
        revisoes.append(Revisao(
            bloco=bloco, edicao=edicao, autor=autor, acao=acao, xml_antes=antes, xml_depois=depois,
            comentario=comentario, lote=lote, volume_id=vol, pagina=pag))

    resultado = []
    for (n, b), ordem in zip(pares, final):
        tipo = esquema.tipo_do_fragmento(n["xml"])
        if b is None:
            ref = resultado[-1] if resultado else viz  # herda do bloco imediatamente anterior
            novo = Bloco(
                edicao=edicao, ordem=ordem, tipo=tipo, xml=n["xml"],
                volume_id=vol_id if vol_id is not None else (ref.volume_id if ref else None),
                pagina=pagina if pagina is not None else (ref.pagina if ref else None),
                procedencia=Bloco.NOVO if ed_nova else Bloco.COPIA, versao=1,
                criado_por=autor, atualizado_por=autor,
            )
            novo.save()
            rev(Revisao.CRIAR, novo, "", n["xml"], novo.volume_id, novo.pagina)
            res.criados += 1
            reconstruir |= tipo in (Bloco.MARCO, Bloco.TITULO) or _logo_apos_titulo(edicao, ordem)
            resultado.append(novo)
            ordem_dos_modificados.append(ordem)
            continue
        mudou_xml = b.xml != n["xml"]
        mudou_ordem = b.ordem != ordem
        if mudou_xml:
            rev(Revisao.EDITAR, b, b.xml, n["xml"], b.volume_id, b.pagina)
            reconstruir |= (tipo in (Bloco.MARCO, Bloco.TITULO) or b.tipo in (Bloco.MARCO, Bloco.TITULO)
                            or _logo_apos_titulo(edicao, ordem))
            b.xml, b.tipo = n["xml"], tipo
            b.versao += 1
            b.atualizado_por, b.atualizado_em = autor, agora
            if ed_nova and b.procedencia == Bloco.COPIA:
                b.procedencia = Bloco.ADAPTADO
                if b.origem_id:  # adaptado contra esta versão da origem (ver servicos_nova.adaptados_pendentes)
                    b.origem_versao_vista = (Bloco.objects.filter(pk=b.origem_id)
                                             .values_list("versao", flat=True).first())
            res.editados += 1
        if mudou_ordem:
            if not mudou_xml:
                rev(Revisao.MOVER, b, b.xml, b.xml, b.volume_id, b.pagina)
            b.ordem = ordem
            res.movidos += 1
            reconstruir |= b.tipo in (Bloco.MARCO, Bloco.TITULO)
        if mudou_xml or mudou_ordem:
            a_atualizar.append(b)
        resultado.append(b)
    if a_atualizar:
        Bloco.objects.bulk_update(
            a_atualizar, ["xml", "tipo", "ordem", "versao", "atualizado_por", "atualizado_em", "procedencia",
                        "origem_versao_vista"])
    for b in removidos:
        rev(Revisao.REMOVER, b, b.xml, "", b.volume_id, b.pagina)
        reconstruir |= b.tipo in (Bloco.MARCO, Bloco.TITULO) or _logo_apos_titulo(edicao, b.ordem)
        res.removidos += 1
    Revisao.objects.bulk_create(revisoes)  # ainda com bloco=<existente>; SET_NULL cuida da remoção
    if removidos:
        Bloco.objects.filter(pk__in=[b.pk for b in removidos]).delete()
    if reconstruir:
        arvore.reconstruir(edicao)
        res.arvore_reconstruida = True
    res.blocos = resultado
    return res


def _logo_apos_titulo(edicao, ordem):
    """O bloco em `ordem` vem imediatamente após marco/título? (então o título da tese pode mudar)."""
    prev = (Bloco.objects.filter(edicao=edicao, ordem__lt=ordem).exclude(tipo=Bloco.CABECALHO)
            .order_by("-ordem").values_list("tipo", flat=True).first())
    return prev in (Bloco.MARCO, Bloco.TITULO)


# ---------------------------------------------------------------- mover nó
@transaction.atomic
def mover_no(no, antes_de=None, depois_de=None, para_pai=None, autor=None, comentario=""):
    """Move a faixa contígua de blocos de `no` (e descendentes) para outra posição.

    * `antes_de=<No>` / `depois_de=<No>`: vira irmão (mesmo nível) do alvo, antes/depois dele;
    * `para_pai=<No>` sozinho: último filho de `para_pai`; combinado com antes_de/depois_de,
      o alvo deve ser filho de `para_pai`.
    Só na edição `nova` (a única que reorganiza a estrutura). Registra uma `Revisao(acao="mover")` e reconstrói a árvore."""
    edicao = no.edicao
    if not edicao.reorganiza:
        raise ErroOperacao("Só é permitido mover nós na edição nova.")
    alvos = [x for x in (antes_de, depois_de) if x is not None]
    if len(alvos) > 1:
        raise ErroOperacao("Informe só antes_de ou depois_de.")
    if not alvos and para_pai is None:
        raise ErroOperacao("Informe antes_de, depois_de ou para_pai.")
    no = No.objects.get(pk=no.pk)  # estado atual
    niveis = esquema.NIVEIS_ORDEM
    if alvos:
        alvo = No.objects.get(pk=alvos[0].pk)
        if alvo.edicao_id != edicao.pk:
            raise ErroOperacao("O alvo é de outra edição.")
        if alvo.nivel != no.nivel:
            raise ErroOperacao("O alvo deve ser do mesmo nível que o nó movido.")
        if para_pai is not None and alvo.pai_id != para_pai.pk:
            raise ErroOperacao("O alvo não é filho de para_pai.")
        pos = alvo.ordem_ini if antes_de is not None else alvo.ordem_fim
        if no.ordem_ini <= alvo.ordem_ini < no.ordem_fim:
            raise ErroOperacao("Não é possível mover um nó para dentro de si mesmo.")
    else:
        pai = No.objects.get(pk=para_pai.pk)
        if pai.edicao_id != edicao.pk:
            raise ErroOperacao("O pai é de outra edição.")
        if niveis.index(pai.nivel) >= niveis.index(no.nivel):
            raise ErroOperacao("O pai deve ser de nível superior ao do nó movido.")
        if no.ordem_ini <= pai.ordem_ini < no.ordem_fim:
            raise ErroOperacao("Não é possível mover um nó para dentro de si mesmo.")
        pos = pai.ordem_fim
    if no.ordem_ini <= pos <= no.ordem_fim:
        return no  # já está lá

    movidos = list(Bloco.objects.select_for_update()
                   .filter(edicao=edicao, ordem__gte=no.ordem_ini, ordem__lt=no.ordem_fim).order_by("ordem"))
    if not movidos:
        raise ErroOperacao("O nó não tem blocos.")
    ids = {b.pk for b in movidos}
    resto = Bloco.objects.filter(edicao=edicao).exclude(pk__in=ids)
    esq = resto.filter(ordem__lt=pos).aggregate(m=Max("ordem"))["m"] or 0
    dir_ = resto.filter(ordem__gte=pos).aggregate(m=Min("ordem"))["m"]
    slots = _alocar(esq, dir_, len(movidos))
    primeiro_xml = movidos[0].xml
    if slots is None:
        # renumera tudo: resto com folga, movidos encaixados na posição
        seq = list(resto.order_by("ordem", "pk").only("pk", "ordem"))
        corte = sum(1 for b in seq if b.ordem < pos)
        seq = seq[:corte] + movidos + seq[corte:]
        for i, b in enumerate(seq, 1):
            b.ordem = i * PASSO_ORDEM
        Bloco.objects.bulk_update(seq, ["ordem"], batch_size=500)
    else:
        for b, o in zip(movidos, slots):
            b.ordem = o
        Bloco.objects.bulk_update(movidos, ["ordem"], batch_size=500)
    Revisao.objects.create(
        bloco_id=movidos[0].pk, edicao=edicao, autor=autor, acao=Revisao.MOVER,
        xml_antes=primeiro_xml, xml_depois=primeiro_xml, lote=uuid.uuid4(),
        comentario=comentario or f"Movido {no.rotulo or no.xml_id} ({len(movidos)} blocos).",
        volume=no.volume, pagina=no.pagina_ini)
    arvore.reconstruir(edicao)
    return No.objects.get(edicao=edicao, xml_id=no.xml_id)


# ------------------------------------------------------------------ páginas
def marcar_pagina(pagina, estado, usuario):
    """Muda o estado de revisão de uma `Pagina`."""
    if estado not in dict(Pagina.ESTADOS):
        raise ErroValidacao([f"Estado inválido: {estado}."])
    pagina.estado = estado
    if estado == Pagina.NAO_REVISADA:
        pagina.revisada_por, pagina.revisada_em = None, None
    else:
        pagina.revisada_por, pagina.revisada_em = usuario, timezone.now()
    pagina.save(update_fields=["estado", "revisada_por", "revisada_em"])
    return pagina
