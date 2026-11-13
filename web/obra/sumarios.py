"""Sumários de capítulo.

O «Summario» que o autor põe no começo de cada capítulo chegou do OCR em mau estado: o rótulo
aparece como `SussAnt0`, `Suwxaxio`, `SuxwaR)0`…, às vezes grudado no título do capítulo, e o
texto vem picotado em vários `<p>` com as linhas da página. Só alguns viraram `<argument>`.

`detectar(edicao)` acha esses sumários nos blocos (independe da árvore de nós, porque o marco do
capítulo às vezes falta e o sumário cai dentro da secção ou de uma tese); o comando
`ocultar_sumarios` os marca como suprimidos na edição nova. `gerar(no)` monta um sumário novo a
partir dos nós (artigos e teses) do capítulo, que a página do capítulo mostra no lugar do antigo.
"""
import re
from dataclasses import dataclass, field

from .leitura import texto_plano
from .models import Bloco

COMENTARIO = "Sumário do autor (OCR) ocultado: substituído pelo sumário gerado (ocultar_sumarios)."

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


# ------------------------------------------------------------------- sumário gerado
def _titulo(no, limite=90):
    t = (no.titulo or "").strip(" .;,")
    corte = re.split(r"\s+[—–]\s*", t, maxsplit=1)[0].strip(" .;,|")   # "Definição, — Definição é…"
    if len(re.sub(r"\W", "", corte)) >= 3:
        t = corte
    if len(re.sub(r"\W", "", t)) < 3:    # "y", "|": resto de OCR, não título
        return ""
    return t if len(t) <= limite else t[:limite].rsplit(" ", 1)[0] + "…"


def _numero(no):
    return no.rotulo.replace("Tese", "").strip(" .") if no.rotulo else ""


def gerar(no):
    """Sumário de um nó já montado por `leitura.Arvore` (usa `filhos_lista`).

    Lista de grupos `{"no": artigo|None, "titulo": str, "teses": [{"no", "numero", "titulo"}]}`:
    as teses soltas no capítulo (antes do primeiro artigo ou entre artigos) formam grupos sem
    cabeçalho. Vazio se o nó não tem filhos."""
    grupos = []
    for f in no.filhos_lista:
        if f.nivel == "tese":
            if not grupos or grupos[-1]["no"] is not None:
                grupos.append({"no": None, "titulo": "", "teses": []})
            grupos[-1]["teses"].append({"no": f, "numero": _numero(f), "titulo": _titulo(f)})
        else:
            teses = [d for d in _descendentes(f) if d.nivel == "tese"]
            grupos.append({"no": f, "titulo": _titulo(f, 120),
                           "teses": [{"no": t, "numero": _numero(t), "titulo": _titulo(t)} for t in teses]})
    return grupos


def _descendentes(no):
    for f in no.filhos_lista:
        yield f
        yield from _descendentes(f)
