"""Aplicação automática de uma sugestão de leitor ao texto de um bloco."""
import re

from django.db import transaction
from django.utils import timezone
from lxml import etree

from . import servicos
from .models import Bloco, Sugestao


class ErroAplicacao(Exception):
    """A sugestão não pode ser aplicada automaticamente (a mensagem diz por quê; nada foi alterado)."""


def _padrao(trecho):
    """Regex que casa `trecho` tolerando qualquer sequência de espaços/quebras onde ele tiver espaço."""
    partes = trecho.split()
    if not partes:
        raise ErroAplicacao("O trecho está vazio.")
    return re.compile(r"\s+".join(re.escape(p) for p in partes))


def _nos_de_texto(raiz):
    """(elemento, 'text'|'tail') de todo nó de texto do fragmento (a cauda da raiz não conta)."""
    for el in raiz.iter():
        if not isinstance(el.tag, str):  # comentário / instrução de processamento
            continue
        yield el, "text"
        if el is not raiz:
            yield el, "tail"


def substituir_no_xml(xml, trecho, novo):
    """`xml` com a ÚNICA ocorrência de `trecho` trocada por `novo`. Levanta `ErroAplicacao` se houver 0 ou
    várias ocorrências, ou se a única atravessar elementos (negrito, nota, marca de página…)."""
    padrao = _padrao(trecho)
    raiz = etree.fromstring(xml.encode("utf-8"))
    total = len(padrao.findall("".join(raiz.itertext())))
    achados = []  # (elemento, atributo, match)
    for el, attr in _nos_de_texto(raiz):
        texto = getattr(el, attr)
        if texto:
            achados.extend((el, attr, m) for m in padrao.finditer(texto))
    if total == 0:
        raise ErroAplicacao("O trecho não foi encontrado no bloco (o texto pode ter mudado depois do envio).")
    if total > 1:
        raise ErroAplicacao(f"O trecho aparece {total} vezes no bloco; não dá para saber qual corrigir.")
    if not achados:
        raise ErroAplicacao("O trecho atravessa elementos do texto (itálico, negrito, nota ou marca de página); "
                            "corrija-o à mão no editor.")
    el, attr, m = achados[0]
    texto = getattr(el, attr)
    setattr(el, attr, texto[:m.start()] + novo + texto[m.end():])
    return etree.tostring(raiz, encoding="unicode")


def pode_aplicar(sugestao):
    """Em princípio (o texto pode ainda não casar): pendente, com bloco, trecho e sugestão não vazios."""
    return (sugestao.estado == Sugestao.PENDENTE and sugestao.bloco_id is not None
            and bool(sugestao.trecho.strip()) and bool(sugestao.sugestao.strip()))


def aplicar(sugestao, autor, resposta=""):
    """Troca `trecho` por `sugestao` no bloco, via `servicos.salvar_blocos` (grava `Revisao` do `autor`), e marca a
    sugestão como aceita. Levanta `ErroAplicacao`, `servicos.ErroValidacao` ou `servicos.Conflito`; nesses casos
    nada muda."""
    with transaction.atomic():
        s = Sugestao.objects.select_for_update().select_related("edicao").get(pk=sugestao.pk)
        if not pode_aplicar(s):
            raise ErroAplicacao("Esta sugestão não pode ser aplicada automaticamente.")
        bloco = Bloco.objects.get(pk=s.bloco_id)
        novo_xml = substituir_no_xml(bloco.xml, s.trecho, s.sugestao.strip())
        quem = s.nome or "anônimo"
        servicos.salvar_blocos(
            s.edicao, [bloco.pk], [{"id": bloco.pk, "versao": bloco.versao, "xml": novo_xml}], autor,
            comentario=f"Sugestão #{s.pk} de leitor ({quem})")
        s.estado = Sugestao.ACEITA
        s.resolvida_por, s.resolvida_em, s.resposta = autor, timezone.now(), resposta
        s.save(update_fields=["estado", "resolvida_por", "resolvida_em", "resposta"])
    sugestao.refresh_from_db()
    return sugestao
