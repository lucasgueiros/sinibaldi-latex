"""Sumário de capítulo como componente: `<argument>` com um `<p>` por assunto.

O «Summario» que o autor põe no começo de cada capítulo chegou do OCR em mau estado: o rótulo
aparece como `SussAnt0`, `Suwxaxio`, `SuxwaR)0`…, às vezes grudado no título do capítulo, e o
texto vem picotado em vários `<p>` com as linhas da página. Só alguns viraram `<argument>`.

`detectar(edicao)` acha esses sumários nos blocos (independe da árvore de nós, porque o marco do
capítulo às vezes falta e o sumário cai dentro da secção ou de uma tese). `componente(achado)`
devolve os blocos que os substituem: o título grudado vira `<head>` e o sumário, `<argument>`
com um `<p>` por assunto (o rótulo «Summario» e os travessões são da apresentação). Aplicado pelo
comando `aplicar_componentes`.
"""
import re
from dataclasses import dataclass, field

from lxml import etree

from .leitura import texto_plano
from .models import Bloco

COMENTARIO = "Sumário do capítulo convertido no componente <argument> (aplicar_componentes)."

# rótulo «SUMMARIO:» com as leituras do OCR (SussAnt0, Suwxaxio, SuxwaR)0, "BUMMARIO, SummaAn10…),
# seguido de dois-pontos e do travessão que abre a lista de assuntos
_ROTULO = re.compile(r'(?:^|\s)["“\'^]?[SB][uU][^\s:;—–-]{3,8}\s*\w{0,2}\s*[:;]+\s*\S{0,2}?\s*[—–-]')
_MINUSCULA = re.compile(r"[a-zà-ÿ]")
# «ARTIGO I» mal lido: Amrigo ], ArTIGO |, AmnrrGO [.
_ARTIGO = re.compile(r"^\W*A\w{4,7}[\s\W\dIVXl]*$")
_TRAVESSAO = re.compile(r"^\W{0,2}[—–]")
_NUMERADO = re.compile(r"^\W{0,3}\d{1,3}\s*[.,]")
_ITALICO = re.compile(r'<hi rend="it">(.*?)</hi>', re.S)
_TAG = re.compile(r"<[^>]+>")

MAX_LINHAS = 6        # parágrafos de continuação (o sumário ocupa de 1 a 4 linhas impressas)
MAX_CONTINUACAO = 160  # um parágrafo maior que isto já é texto corrido


@dataclass
class Achado:
    blocos: list = field(default_factory=list)
    titulo_embutido: str = ""   # texto antes do rótulo (título do capítulo que o OCR grudou)


def inicio_de_sumario(texto):
    """Se `texto` começa um sumário, devolve o que vem antes do rótulo (pode ser ''); senão None."""
    m = _ROTULO.search(texto[:120])
    if not m:
        return None
    antes = texto[:m.start()].strip()
    if _MINUSCULA.search(antes) or len(antes) > 80:   # só um título em versal pode vir antes
        return None
    return antes.strip(" :;.-—")


def _fecha(texto):
    t = texto.rstrip(" \"”'»|")
    return t.endswith(".") and not t.endswith("..")


def _italico(xml):
    """O parágrafo é (quase) todo itálico: subtítulo de artigo, não sumário."""
    total = len(_TAG.sub("", xml).strip())
    it = sum(len(_TAG.sub("", m)) for m in _ITALICO.findall(xml))
    return total > 0 and it / total >= 0.6


def _continua(b, texto):
    if b.tipo != Bloco.PARAGRAFO or not texto:
        return False
    if len(texto) > MAX_CONTINUACAO or _NUMERADO.match(texto) or "<label>" in b.xml or _italico(b.xml):
        return False
    return not (len(texto) <= 20 and _ARTIGO.match(texto))


def detectar(edicao, blocos=None):
    """Sumários do autor nos blocos da edição (não suprimidos), em ordem. Lista de `Achado`."""
    if blocos is None:
        blocos = (Bloco.objects.filter(edicao=edicao).exclude(procedencia=Bloco.SUPRIMIDO)
                  .order_by("ordem").only("pk", "ordem", "tipo", "xml", "procedencia"))
    blocos = list(blocos)
    achados, i = [], 0
    while i < len(blocos):
        b = blocos[i]
        if b.tipo == Bloco.SUMARIO:
            achados.append(Achado([b]))
            i += 1
            continue
        antes = inicio_de_sumario(texto_plano(b.xml, notas=False)) if b.tipo == Bloco.PARAGRAFO else None
        if antes is None:
            i += 1
            continue
        a = Achado([b], antes)
        fechou = _fecha(texto_plano(b.xml, notas=False))
        j = i + 1
        while j < len(blocos) and len(a.blocos) <= MAX_LINHAS:
            c = blocos[j]
            if c.tipo == Bloco.CABECALHO:      # cabeçalho corrente no meio (quebra de página)
                j += 1
                continue
            t = texto_plano(c.xml, notas=False)
            # linha que fecha em ponto ainda pode ter continuação: a seguinte começa com travessão
            if (fechou and not _TRAVESSAO.match(t)) or not _continua(c, t):
                break
            a.blocos.append(c)
            fechou = _fecha(t)
            j += 1
        achados.append(a)
        i = j
    return achados


# --------------------------------------------------------------------- componente
_HIFEN_FIM = re.compile(r"(\w)-\s*$")
_HIFEN_MEIO = re.compile(r"(\w)-\s+(?=[a-zà-ÿ])")
_SEPARADOR = re.compile(r"\s*(?:[—–]+-*|-{2,})\s*")
_ESPACO_PONTUACAO = re.compile(r"\s+([.,;:])")
_LETRAS = re.compile(r"[A-Za-zÀ-ÿ]")
_PONTAS = " .,;:|\"“”'^-—–"


def _esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _interno(el):
    """Conteúdo inline de `el` como string XML, sem cabeçalhos correntes."""
    for fw in el.findall(".//fw"):
        pai, cauda = fw.getparent(), fw.tail or ""
        ant = fw.getprevious()
        if ant is not None:
            ant.tail = (ant.tail or "") + cauda
        else:
            pai.text = (pai.text or "") + cauda
        pai.remove(fw)
    return _esc(el.text or "") + "".join(etree.tostring(c, encoding="unicode", with_tail=True) for c in el)


def _linhas(achado):
    out = []
    for b in achado.blocos:
        el = etree.fromstring(b.xml.encode("utf-8"))
        out.extend(_interno(p) for p in (el.findall("p") if el.tag == "argument" else [el]))
    return out


def _juntar(linhas):
    """Junta as linhas impressas desfazendo a hifenização (`Pro-` + `cesso`)."""
    out = ""
    for t in linhas:
        t = t.strip()
        if out and _HIFEN_FIM.search(out):
            out = _HIFEN_FIM.sub(r"\1", out) + t
        else:
            out = f"{out} {t}" if out else t
    return _HIFEN_MEIO.sub(r"\1", out)


def _item(xml):
    """Um assunto: pontas limpas, terminado em ponto; `<hi>` preservado se ficou equilibrado."""
    xml = _ESPACO_PONTUACAO.sub(r"\1", " ".join(xml.split())).strip(_PONTAS)
    try:
        el = etree.fromstring(f"<p>{xml}</p>".encode("utf-8"))
    except etree.XMLSyntaxError:                       # <hi> cortado pelo travessão: fica o texto
        xml = _esc(_TAG.sub("", xml)).strip(_PONTAS)
        el = etree.fromstring(f"<p>{xml}</p>".encode("utf-8"))
    texto = "".join(el.itertext()).strip()
    if len(_LETRAS.findall(texto)) < 3:
        return None
    return xml if texto.endswith(".") else xml + "."


def assuntos(achado):
    """Os assuntos do sumário (XML inline), um por item, cada um terminado em ponto."""
    if achado.blocos[0].tipo == Bloco.SUMARIO:         # <argument>: cada <p> já é um assunto (ou vários)
        pedacos = [x for p in _linhas(achado) for x in _SEPARADOR.split(p)]
    else:                                              # linhas impressas: junta e tira «TÍTULO SUMMARIO: —»
        xml = _juntar(_linhas(achado))
        m = _SEPARADOR.search(xml)
        pedacos = _SEPARADOR.split(xml[m.end():] if m else xml)
    return [i for i in map(_item, pedacos) if i]


def componente(achado):
    """XML dos blocos que substituem o achado: [`<head>` do título grudado,] `<argument>`."""
    out = []
    titulo = " ".join(achado.titulo_embutido.split())
    if len(_LETRAS.findall(titulo)) >= 6:
        out.append(f"<head>{_esc(titulo)}</head>")
    itens = assuntos(achado)
    if itens:
        out.append("<argument>" + "".join(f"<p>{i}</p>" for i in itens) + "</argument>")
    return out
