"""Aparato do fim de cada volume como componente: a «Synopse dos tratados contidos neste volume» e o
«Indice das materias».

No OCR, as linhas desse aparato que citam divisões («CAPITULO SEGUNDO», «PARTE SEGUNDA», «SECÇÃO I»)
viraram marcos e títulos, e a árvore ganhou capítulos, partes e secções fantasmas no fim de cada
volume. Aqui cada peça vira um nó `anexo` (marco + `<head>`), os marcos de dentro dela somem e as
linhas viram parágrafos tipados: `anexo-titulo` (a divisão citada) e, no índice, `indice` (entrada).
O texto não muda. Aplicado pelo comando `aplicar_componentes`.
"""
import re
from dataclasses import dataclass, field

from lxml import etree

from . import esquema
from .leitura import texto_plano
from .models import Bloco

COMENTARIO = "Aparato do fim do volume convertido em anexo (aplicar_componentes)."

SYNOPSE, INDICE = "synopse", "indice"
TITULOS = {SYNOPSE: "SYNOPSE DOS TRATADOS CONTIDOS NESTE VOLUME", INDICE: "INDICE DAS MATERIAS"}
_INICIO = {SYNOPSE: re.compile(r"TRATADOS\s+CONTIDOS"), INDICE: re.compile(r"INDICE\s+DAS\s+MATERIAS", re.I)}
_DIVISAO = re.compile(r"^\W*(?:CAP[IÍ]T|CAPITOLO|PARTE\b|SEC[CÇ]|SECÇ|SYNOPSE|PRO[LE]O|PROEMIO)", re.I)
_MAIUSC = re.compile(r"[A-ZÀ-Ý]")
_MINUSC = re.compile(r"[a-zà-ÿ]")
XML_ID = esquema.qname_atributo("xml:id")


@dataclass
class Anexo:
    tipo: str               # SYNOPSE | INDICE
    volume_numero: int
    blocos: list = field(default_factory=list)   # do bloco de abertura até o fim da peça


def _e_divisao(texto):
    """Linha que cita uma divisão (título dentro do anexo): rótulo conhecido ou linha curta em versal."""
    t = texto.strip()
    if not t or len(t) > 70:
        return False
    if _DIVISAO.match(t):
        return True
    mai, mi = len(_MAIUSC.findall(t)), len(_MINUSC.findall(t))
    return mai >= 4 and mai >= 3 * mi


def detectar(edicao):
    """Anexos de cada volume (só os que ainda não foram convertidos), na ordem do texto."""
    from .models import Volume
    numeros = dict(Volume.objects.values_list("pk", "numero"))
    blocos = list(Bloco.objects.filter(edicao=edicao).order_by("ordem")
                  .only("pk", "ordem", "tipo", "xml", "volume_id", "pagina", "procedencia", "origem_id"))
    ja = {(b.volume_id) for b in blocos if b.tipo == Bloco.MARCO and 'unit="anexo"' in b.xml}
    achados, atual = [], None
    for b in blocos:
        if atual is not None and b.volume_id != atual_vol:
            atual = None
        if b.tipo == Bloco.PARAGRAFO and b.volume_id not in ja:
            t = texto_plano(b.xml, notas=False)
            for tipo, rx in _INICIO.items():
                if len(t) < 60 and rx.search(t):
                    atual, atual_vol = Anexo(tipo, numeros.get(b.volume_id, 0)), b.volume_id
                    achados.append(atual)
                    break
        if atual is not None:
            atual.blocos.append(b)
    return achados


def _p_tipado(el, tipo):
    """`<p type=tipo>` com o conteúdo inline de `el` (um <p> ou <head>), preservando xml:id."""
    p = etree.Element("p")
    p.set("type", tipo)
    if el.tag == "p" and el.get(XML_ID):
        p.set(XML_ID, el.get(XML_ID))
    p.text = el.text
    for c in el:
        p.append(c)
    return etree.tostring(p, encoding="unicode")


def componente(anexo):
    """Lista `novos` para `servicos.salvar_blocos` (escopo = `anexo.blocos`): marco `anexo` novo, o
    bloco de abertura como `<head>`, marcos removidos, títulos e linhas tipados."""
    abre = anexo.blocos[0]
    novos = [{"id": None, "xml": f'<milestone unit="anexo" xml:id="v{anexo.volume_numero}.{anexo.tipo}"/>'},
             {"id": abre.pk, "xml": f"<head>{TITULOS[anexo.tipo]}</head>"}]
    for b in anexo.blocos[1:]:
        if b.tipo == Bloco.MARCO:
            continue                                    # capítulo/parte fantasma
        el = etree.fromstring(b.xml.encode("utf-8"))
        if b.tipo == Bloco.TITULO:
            xml = _p_tipado(el, "anexo-titulo")
        elif b.tipo == Bloco.PARAGRAFO and el.get("type") is None:
            t = texto_plano(b.xml, notas=False)
            if _e_divisao(t):
                xml = _p_tipado(el, "anexo-titulo")
            elif anexo.tipo == INDICE:
                xml = _p_tipado(el, "indice")
            else:
                xml = b.xml
        else:
            xml = b.xml
        novos.append({"id": b.pk, "xml": xml})
    return novos
