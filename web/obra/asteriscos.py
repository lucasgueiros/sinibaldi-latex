"""Componente semântico "asterisco": o ∗ de divisão de assunto do original, `<anchor type="asterisco"/>`.

Vale no corpo do parágrafo e dentro de nota. O OCR costuma perdê-lo (ou lê-lo como lixo); o editor o
insere pelo botão ∗ da barra, e o comando `aplicar_asteriscos` o aplica em lote, a partir de
(a) parágrafos que são só um `*` solto e (b) uma lista (volume, página impressa, trecho que o
antecede, nota opcional).

Este módulo só transforma fragmentos XML; quem grava é o comando."""
import re

from lxml import etree

from . import tei
from .esquema import nome_local

TIPO = "asterisco"
COMENTARIO = "Asterisco de divisão (componente) inserido."

_SOLTO = re.compile(r"^<p\b[^>]*>\s*[*∗]\s*</p>$")


def novo_elemento():
    el = etree.Element("anchor")
    el.set("type", TIPO)
    return el


def eh_solto(xml):
    """O bloco é um parágrafo cujo único conteúdo é um `*`."""
    return bool(_SOLTO.match(xml.strip()))


def converter_solto(xml):
    """`<p …>*</p>` -> `<p …><anchor type="asterisco"/></p>` (mantém os atributos); None se não for."""
    if not eh_solto(xml):
        return None
    raiz = etree.fromstring(xml)
    raiz.text = None
    raiz.append(novo_elemento())
    return tei.serializar_fragmento(raiz)


def _fatias(escopo, pular_notas):
    """[(elemento, 'text'|'tail', texto)] na ordem do documento, dentro de `escopo`."""
    saida = []

    def rec(e):
        if e.text:
            saida.append((e, "text", e.text))
        for c in e:
            if isinstance(c.tag, str) and nome_local(c.tag) in ("note", "fw") and pular_notas:
                pass                                 # nota/cabeçalho: fora do texto do corpo
            elif isinstance(c.tag, str):
                rec(c)
            if c.tail:
                saida.append((c, "tail", c.tail))

    rec(escopo)
    return saida


def _padrao(trecho):
    """Regex do trecho, tolerante a variação de espaço."""
    partes = [re.escape(t) for t in trecho.split()]
    return re.compile(r"\s+".join(partes)) if partes else None


def inserir_apos(xml, trecho, nota=None):
    """Insere o asterisco logo depois da ocorrência única de `trecho` no corpo do bloco (ou dentro da
    nota de número `nota`). Retorna (xml_novo, None) ou (None, motivo)."""
    rx = _padrao(trecho)
    if rx is None:
        return None, "trecho vazio"
    raiz = etree.fromstring(xml)
    if nota:
        escopos = [n for n in raiz.iter("note") if n.get("n") == str(nota)]
        if not escopos:
            return None, f"nota {nota} não existe neste bloco"
        escopo, pular = escopos[0], False
    else:
        escopo, pular = raiz, True
    fatias = _fatias(escopo, pular)
    texto = "".join(f[2] for f in fatias)
    achados = list(rx.finditer(texto))
    if not achados:
        return None, "trecho não encontrado"
    if len(achados) > 1:
        return None, f"trecho ambíguo ({len(achados)} ocorrências)"
    fim = achados[0].end()
    base = 0
    for el, onde, t in fatias:
        if fim <= base + len(t):
            k = fim - base
            antes, depois = t[:k], t[k:]
            asterisco = novo_elemento()
            asterisco.tail = depois or None
            if onde == "text":
                el.text = antes
                el.insert(0, asterisco)
            else:
                el.tail = antes
                pai = el.getparent()
                pai.insert(pai.index(el) + 1, asterisco)
            return tei.serializar_fragmento(raiz), None
        base += len(t)
    return None, "posição fora do texto"  # inalcançável
