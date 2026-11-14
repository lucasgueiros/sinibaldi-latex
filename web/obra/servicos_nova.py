"""Operações de escrita das edições DERIVADAS da 1916 (atualizada e nova): restaurar o texto de 1916 e
sincronizar com a 1916 (`exige_derivada`); reordenar partes, reunir anexos e suprimir só na nova, a
única que reorganiza a estrutura (`exige_nova`). ErroOperacao se a edição não serve; todas gravam
`Revisao` com o autor. A regra de procedência ao gravar (copia -> adaptado, bloco criado -> novo)
está em `servicos.salvar_blocos`."""
import uuid
from bisect import bisect_left

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from . import arvore, partes
from .models import PASSO_ORDEM, Bloco, Edicao, No, Revisao
from .servicos import ErroOperacao


def exige_nova(edicao):
    if not edicao.reorganiza:
        raise ErroOperacao("Operação permitida só na edição nova.")


def exige_derivada(edicao):
    if not edicao.derivada:
        raise ErroOperacao("Operação permitida só nas edições derivadas da 1916 (atualizada e nova).")


def _rev(edicao, bloco, autor, lote, comentario, antes, depois):
    return Revisao(bloco=bloco, edicao=edicao, autor=autor, acao=Revisao.EDITAR, xml_antes=antes,
                   xml_depois=depois, comentario=comentario, lote=lote, volume_id=bloco.volume_id,
                   pagina=bloco.pagina)


# ------------------------------------------------------------- reordenar partes
def reordenar_blocos(edicao, pks_na_ordem):
    """Reatribui `ordem` (com folga) a TODOS os blocos da edição na sequência dada."""
    total = Bloco.objects.filter(edicao=edicao).count()
    if len(pks_na_ordem) != total or len(set(pks_na_ordem)) != total:
        raise ErroOperacao("A sequência não cobre exatamente os blocos da edição.")
    objs = [Bloco(pk=pk, ordem=i * PASSO_ORDEM) for i, pk in enumerate(pks_na_ordem, 1)]
    Bloco.objects.bulk_update(objs, ["ordem"], batch_size=500)


@transaction.atomic
def reunir_anexos(edicao, regioes_1916, autor=None):
    """Junta no fim da edição nova, na ordem da 1916, os blocos copiados de cada região de aparato
    da 1916 (`regioes_1916`: listas de blocos da 1916, uma por anexo). Serve para a nova em que a
    reordenação de partes espalhou o índice junto com as partes fantasmas. Retorna quantos blocos
    foram reunidos."""
    exige_nova(edicao)
    linhas = list(Bloco.objects.select_for_update().filter(edicao=edicao).order_by("ordem")
                  .values_list("pk", "origem_id"))
    grupos, usados = [], set()
    for regiao in regioes_1916:
        pos = {b.pk: i for i, b in enumerate(regiao)}
        g = sorted((pk for pk, o in linhas if o in pos), key=lambda pk, o=dict(linhas): pos[o[pk]])
        grupos.append(g)
        usados.update(g)
    if not usados:
        return 0
    sequencia = [pk for pk, _ in linhas if pk not in usados] + [pk for g in grupos for pk in g]
    if sequencia != [pk for pk, _ in linhas]:
        reordenar_blocos(edicao, sequencia)
        Revisao.objects.create(bloco_id=grupos[0][0] if grupos[0] else None, edicao=edicao, autor=autor,
                               acao=Revisao.MOVER, lote=uuid.uuid4(),
                               comentario="Aparato do fim dos volumes reunido no fim da edição (aplicar_componentes).")
        arvore.reconstruir(edicao)
    return len(usados)


@transaction.atomic
def aplicar_ordem_partes(edicao, autor=None, comentario=""):
    """Reordena as PARTES segundo `partes.ORDEM_PARTES`. Cada parte (com descendentes) é uma faixa;
    partes não identificadas seguem a anterior; dentro do mesmo tipo vale a ordem original; trechos
    fora de qualquer parte vão para o início, na ordem original, exceto os anexos (aparato do fim
    dos volumes), que vão para o fim. Exige as seis partes.
    Retorna os nós de parte na ordem final."""
    exige_nova(edicao)
    plano = partes.plano_partes(edicao)
    if plano["faltam"]:
        raise ErroOperacao("Faltam partes: " + ", ".join(partes.ORDEM_PARTES[r] for r in plano["faltam"]) + ".")
    if plano["na_ordem"]:
        return plano["alvo"]
    linhas = list(Bloco.objects.select_for_update().filter(edicao=edicao).order_by("ordem")
                  .values_list("pk", "ordem"))
    ordens = [o for _, o in linhas]
    atuais = sorted(plano["partes"], key=lambda p: p.ordem_ini)
    cortes = {p.pk: (bisect_left(ordens, p.ordem_ini), bisect_left(ordens, p.ordem_fim)) for p in atuais}
    dentro = [False] * len(linhas)
    for i0, i1 in cortes.values():
        for i in range(i0, i1):
            dentro[i] = True
    no_anexo = [False] * len(linhas)
    for a in No.objects.filter(edicao=edicao, nivel="anexo"):
        for i in range(bisect_left(ordens, a.ordem_ini), bisect_left(ordens, a.ordem_fim)):
            no_anexo[i] = not dentro[i]
    sequencia = [pk for (pk, _), d, x in zip(linhas, dentro, no_anexo) if not d and not x]
    for p in plano["alvo"]:
        i0, i1 = cortes[p.pk]
        sequencia.extend(pk for pk, _ in linhas[i0:i1])
    sequencia.extend(pk for (pk, _), x in zip(linhas, no_anexo) if x)
    reordenar_blocos(edicao, sequencia)
    Revisao.objects.create(
        bloco_id=linhas[0][0] if linhas else None, edicao=edicao, autor=autor, acao=Revisao.MOVER,
        lote=uuid.uuid4(), comentario=comentario or "Partes reordenadas: " + " > ".join(partes.ORDEM_PARTES) + ".")
    arvore.reconstruir(edicao)
    return list(No.objects.filter(edicao=edicao, nivel="parte").order_by("ordem_ini"))


# ------------------------------------------------------------------ procedência
def procedencia_natural(bloco):
    """novo (sem origem) / copia (xml igual ao da origem) / adaptado."""
    if bloco.origem_id is None:
        return Bloco.NOVO
    return Bloco.COPIA if bloco.origem.xml == bloco.xml else Bloco.ADAPTADO


@transaction.atomic
def definir_supressao(edicao, ordem_ini, ordem_fim, suprimir, autor=None, comentario=""):
    """Marca `suprimido` (ou restaura a procedência natural) os blocos com
    `ordem_ini <= ordem < ordem_fim`. Nada é apagado. Retorna quantos blocos mudaram."""
    exige_nova(edicao)
    blocos = list(Bloco.objects.select_for_update(of=("self",)).select_related("origem")
                  .filter(edicao=edicao, ordem__gte=ordem_ini, ordem__lt=ordem_fim).order_by("ordem"))
    lote = uuid.uuid4()
    texto = comentario or ("Suprimido." if suprimir else "Restaurado (deixou de estar suprimido).")
    alterados, revs = [], []
    for b in blocos:
        if suprimir and b.procedencia != Bloco.SUPRIMIDO:
            b.procedencia = Bloco.SUPRIMIDO
        elif not suprimir and b.procedencia == Bloco.SUPRIMIDO:
            b.procedencia = procedencia_natural(b)
        else:
            continue
        b.atualizado_por = autor
        alterados.append(b)
        revs.append(_rev(edicao, b, autor, lote, texto, b.xml, b.xml))
    if alterados:
        Bloco.objects.bulk_update(alterados, ["procedencia", "atualizado_por"], batch_size=500)
        Revisao.objects.bulk_create(revs, batch_size=500)
    return len(alterados)


def _estrutural(tipos):
    return any(t in (Bloco.MARCO, Bloco.TITULO) for t in tipos)


@transaction.atomic
def restaurar_texto_1916(edicao, ids, autor=None, comentario=""):
    """Volta xml e tipo dos blocos aos da `origem` atual e a procedência a `copia` (isso também tira
    a supressão). Ignora blocos sem origem. Retorna os blocos alterados."""
    exige_derivada(edicao)
    blocos = list(Bloco.objects.select_for_update(of=("self",)).select_related("origem")
                  .filter(edicao=edicao, pk__in=list(ids), origem__isnull=False).order_by("ordem"))
    lote = uuid.uuid4()
    agora = timezone.now()
    revs, tipos, feitos = [], set(), []
    for b in blocos:
        o = b.origem
        if b.xml == o.xml and b.procedencia == Bloco.COPIA:
            continue
        if b.xml != o.xml:
            revs.append(_rev(edicao, b, autor, lote, comentario or "Texto de 1916 restaurado.", b.xml, o.xml))
            tipos.update((b.tipo, o.tipo))
            b.xml, b.tipo = o.xml, o.tipo
            b.versao += 1
        b.procedencia = Bloco.COPIA
        b.origem_versao_vista = o.versao
        b.atualizado_por, b.atualizado_em = autor, agora
        feitos.append(b)
    if feitos:
        Bloco.objects.bulk_update(
            feitos, ["xml", "tipo", "versao", "procedencia", "origem_versao_vista", "atualizado_por", "atualizado_em"],
            batch_size=500)
        Revisao.objects.bulk_create(revs, batch_size=500)
        if _estrutural(tipos):
            arvore.reconstruir(edicao)
    return feitos


# ----------------------------------------------------------------- sincronização
def copias_desatualizadas(edicao):
    """Blocos `copia` cujo xml difere do da origem (a 1916 foi revisada depois)."""
    return (Bloco.objects.filter(edicao=edicao, procedencia=Bloco.COPIA, origem__isnull=False)
            .exclude(xml=F("origem__xml")).order_by("ordem"))


@transaction.atomic
def atualizar_copias(edicao, ids=None, autor=None):
    """Copia o xml atual da origem para os blocos `copia` desatualizados (todos, ou só `ids`).
    Retorna quantos foram atualizados."""
    exige_derivada(edicao)
    qs = copias_desatualizadas(edicao).select_related("origem")
    if ids is not None:
        qs = qs.filter(pk__in=list(ids))
    blocos = list(qs.select_for_update())
    lote = uuid.uuid4()
    agora = timezone.now()
    revs, estrutural = [], False
    for b in blocos:
        o = b.origem
        revs.append(_rev(edicao, b, autor, lote, "Cópia atualizada a partir da edição de 1916.", b.xml, o.xml))
        estrutural |= _estrutural((b.tipo, o.tipo))
        b.xml, b.tipo = o.xml, o.tipo
        b.versao += 1
        b.origem_versao_vista = o.versao
        b.atualizado_por, b.atualizado_em = autor, agora
    if blocos:
        Bloco.objects.bulk_update(
            blocos, ["xml", "tipo", "versao", "origem_versao_vista", "atualizado_por", "atualizado_em"], batch_size=500)
        Revisao.objects.bulk_create(revs, batch_size=500)
        # a mudança de um parágrafo logo após marco/título pode alterar o título da tese
        if estrutural or any(b.tipo == Bloco.PARAGRAFO for b in blocos):
            arvore.reconstruir(edicao)
    return len(blocos)


def adaptados_pendentes(edicao):
    """Blocos `adaptado` cuja origem mudou depois da adaptação (ou do último "marcar como visto").
    Sem `origem_versao_vista` (legado), compara `atualizado_em` da origem com o do bloco."""
    mudou = (Q(origem_versao_vista__isnull=False) & ~Q(origem__versao=F("origem_versao_vista"))) | (
        Q(origem_versao_vista__isnull=True) & Q(origem__atualizado_em__gt=F("atualizado_em")))
    return (Bloco.objects.filter(edicao=edicao, procedencia=Bloco.ADAPTADO, origem__isnull=False)
            .filter(mudou).select_related("origem").order_by("ordem"))


@transaction.atomic
def marcar_origem_vista(edicao, ids, autor=None):
    """Registra a versão atual da origem como já conferida. Retorna quantos blocos."""
    exige_derivada(edicao)
    blocos = list(Bloco.objects.select_for_update(of=("self",)).select_related("origem")
                  .filter(edicao=edicao, pk__in=list(ids), origem__isnull=False))
    for b in blocos:
        b.origem_versao_vista = b.origem.versao
    Bloco.objects.bulk_update(blocos, ["origem_versao_vista"], batch_size=500)
    return len(blocos)


def sem_correspondente(nova):
    """Blocos da 1916 (exceto cabeçalhos correntes) sem nenhum bloco correspondente na edição
    derivada `nova` (um bloco suprimido conta como correspondente)."""
    cobertos = Bloco.objects.filter(edicao=nova, origem__isnull=False).values("origem_id")
    return (Bloco.objects.filter(edicao__slug="1916").exclude(tipo=Bloco.CABECALHO)
            .exclude(pk__in=cobertos).order_by("volume__numero", "ordem"))
