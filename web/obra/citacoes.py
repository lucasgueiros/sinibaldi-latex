"""Citações no texto: reconhecimento automático pelas aspas e leitura dos segmentos.

O dialeto (`esquema.py`) marca a citação com `<quote type xml:id>` — texto SEM aspas, que o
renderizador desenha — e a referência que o próprio Sinibaldi deu com `<bibl corresp>`. Uma citação
interrompida por texto do autor tem vários segmentos: o 1º com `xml:id`, os outros com
`corresp="#id"`. Os dados estruturados (fonte, páginas, tradução) ficam em `models.Citacao`.

`marcar(raiz, novo_id)` percorre um fragmento já parseado e, no texto de cada parágrafo (inclusive
de notas e sumários), troca cada par de aspas por `<quote>`:

* `«…»`, `“…”`, `„…”` e `"…"` (a reta alterna: abre se não há reta aberta, senão fecha);
  `‘’` e `'` ficam de fora (apóstrofos: d'elle). O OCR mistura as famílias (`“…»`): uma
  aspa de fechamento sem par da mesma família fecha a aberta mais próxima;
* aspas internas a uma citação viram `“ ”` (aspas padronizadas: «externas», “internas”);
* `(…)` logo depois do fechamento (admite `.`/traço no meio: «…». (Sum. Th.)), com cara de
  referência (dígito, romano, `l.`, `c.`, `pag.`… ou um título em itálico), vira `<bibl corresp>`;
* duas citações separadas por um trecho curto que começa por vírgula/travessão e não fecha a frase
  («A», diz Vogt, «B») são uma só: a segunda ganha `corresp`;
* aspas curtas (até `PALAVRAS_MENCAO` palavras) sem referência e sem continuação são `mencao`.

Só pareia aspas no mesmo nível de elemento: uma citação que abre dentro de um itálico e fecha
fora dele fica de fora e é contada em `Relatorio.sem_par`. Texto já marcado não é tocado
(idempotente).
"""
import re
import secrets
import string
from dataclasses import dataclass, field

from lxml import etree

from .esquema import NS_XML, nome_local

XML_ID = "{%s}id" % NS_XML
OBJ = "￼"            # um elemento filho na linha de texto
PALAVRAS_MENCAO = 4
MAX_CITACAO = 6000        # caracteres; além disso é quase certo um par errado
MAX_INTERRUPCAO = 90
MAX_BIBL = 220

ABRE = {"«": "«", "“": "“", "„": "“"}      # -> família
FECHA = {"»": "«", "”": "“"}
RETA = '"'
INTERNAS = ("“", "”")

RE_REF = re.compile(
    r"\d|\b[IVXLC]{1,6}\b|\b(?:l|lib|liv|c|cap|q|qu|a|art|p|pp|pag|pág|t|tom|n|num|lect|lec|dist|d|s|sect|"
    r"ed|op|cit|ib|ibid|ibidem|id|loc|v|vol|fol|f|sess|prop|cor|schol|resp|ad|sol|obj|dub|cf)\.",
    re.I)
RE_FIM_FRASE = re.compile(r"[.!?:(]")


@dataclass
class Relatorio:
    diretas: int = 0
    mencoes: int = 0
    continuacoes: int = 0
    bibls: int = 0
    sem_par: int = 0
    ids: list = field(default_factory=list)

    def __iadd__(self, o):
        self.diretas += o.diretas
        self.mencoes += o.mencoes
        self.continuacoes += o.continuacoes
        self.bibls += o.bibls
        self.sem_par += o.sem_par
        self.ids += o.ids
        return self

    @property
    def total(self):
        return self.diretas + self.mencoes

    def __str__(self):
        return (f"{self.diretas} citação(ões) direta(s), {self.continuacoes} continuação(ões), "
                f"{self.bibls} referência(s) do autor, {self.mencoes} menção(ões), {self.sem_par} aspa(s) sem par")


def gerador_de_ids(prefixo="", existentes=()):
    """Função que devolve `prefixo + "cit-" + 6 caracteres`, nunca repetida nem em `existentes`."""
    usados = set(existentes)
    alfabeto = string.ascii_lowercase + string.digits

    def novo():
        while True:
            i = f"{prefixo}cit-" + "".join(secrets.choice(alfabeto) for _ in range(6))
            if i not in usados:
                usados.add(i)
                return i
    return novo


# ------------------------------------------------------------------- linha de texto
def _itens(el):
    """Conteúdo misto de `el` como lista de caracteres e elementos filhos."""
    itens = list(el.text or "")
    for c in el:
        itens.append(c)
        itens.extend(c.tail or "")
    return itens


def _linha(itens):
    return "".join(i if isinstance(i, str) else OBJ for i in itens)


def _tipo_aspa(ch, reta_aberta, antes=" ", depois=" "):
    """('abre'|'fecha'|None, família). A reta não tem forma de abrir/fechar: alterna; entre duas
    letras/dígitos não é aspa (OCR de sobrescrito: Exc"e Rev"º)."""
    if ch in ABRE:
        return "abre", ABRE[ch]
    if ch in FECHA:
        return "fecha", FECHA[ch]
    if ch == RETA:
        if antes.isalnum() and depois.isalnum():
            return None, None
        return ("fecha" if reta_aberta else "abre"), RETA
    return None, None


def _pares(linha):
    """Pares (abre, fecha, profundidade) das aspas da linha; e quantas ficaram sem par."""
    pilha, pares, sem_par = [], [], 0
    for i, ch in enumerate(linha):
        tipo, fam = _tipo_aspa(ch, any(f == RETA for _, f in pilha),
                               linha[i - 1] if i else " ", linha[i + 1] if i + 1 < len(linha) else " ")
        if tipo is None:
            continue
        if tipo == "abre":
            pilha.append((i, fam))
            continue
        k = next((k for k in range(len(pilha) - 1, -1, -1) if pilha[k][1] == fam), None)
        if k is None and pilha:
            k = len(pilha) - 1          # OCR trocou a família: fecha a aberta mais próxima
        if k is None:
            sem_par += 1
            continue
        sem_par += len(pilha) - 1 - k   # abertas por cima ficam sem par
        ini, _ = pilha[k]
        del pilha[k:]
        pares.append((ini, i, len(pilha)))
    return pares, sem_par + len(pilha)


def _apara(linha, a, b):
    """Intervalo [a, b) sem espaços nas pontas."""
    while a < b and linha[a].isspace():
        a += 1
    while b > a and linha[b - 1].isspace():
        b -= 1
    return a, b


def _bibl_apos(linha, j):
    """Intervalo [a, b) de «(…)» de referência logo depois da posição j, ou None."""
    a = j
    while a < len(linha) and linha[a] in " \t\n.-—–":   # «…». (Sum. Th., …)  /  «…» -(C. Gent., …)
        a += 1
    if a >= len(linha) or linha[a] != "(":
        return None
    prof = 0
    for b in range(a, min(len(linha), a + MAX_BIBL)):
        if linha[b] == "(":
            prof += 1
        elif linha[b] == ")":
            prof -= 1
            if prof == 0:
                miolo = linha[a + 1:b]
                if any(c in miolo for c in "«»“”"):
                    return None
                if RE_REF.search(miolo) or (OBJ in miolo and len(miolo) <= 80):   # (<hi>Lettres</hi>)
                    return a, b + 1
                return None
    return None


def _e_interrupcao(trecho):
    t = trecho.strip()
    if not t or len(t) > MAX_INTERRUPCAO or OBJ in trecho or "\n\n" in trecho:
        return False
    return t[0] in ",;—–-" and not RE_FIM_FRASE.search(t)


# --------------------------------------------------------------------- marcação
def _reconstruir(el, itens, embrulhos, apagar, trocar):
    """Reescreve o conteúdo de `el` a partir de `itens`, criando os elementos de `embrulhos`
    ({ini: (fim, elemento)}, intervalos disjuntos), sem os índices de `apagar`, com `trocar`."""
    for c in list(el):
        c.tail = None
    el.text = None
    for c in list(el):
        el.remove(c)

    def anexar(dst, item):
        if isinstance(item, str):
            if len(dst):
                dst[-1].tail = (dst[-1].tail or "") + item
            else:
                dst.text = (dst.text or "") + item
        else:
            dst.append(item)

    i, n = 0, len(itens)
    while i < n:
        if i in embrulhos:
            fim, novo = embrulhos[i]
            for k in range(i, fim):
                if k not in apagar:
                    anexar(novo, trocar.get(k, itens[k]))
            anexar(el, novo)
            i = fim
            continue
        if i not in apagar:
            anexar(el, trocar.get(i, itens[i]))
        i += 1


def _marcar_nivel(el, novo_id, rel):
    itens = _itens(el)
    linha = _linha(itens)
    if not any(c in linha for c in "«»“”„\""):
        return
    pares, sem_par = _pares(linha)
    rel.sem_par += sem_par
    externos = sorted((a, b) for a, b, prof in pares if prof == 0)
    internos = [(a, b) for a, b, prof in pares if prof > 0]
    apagar, trocar, embrulhos = set(), {}, {}
    cits = []  # [{ini, fim, a, b, bibl}]
    for a, b in externos:
        ca, cb = _apara(linha, a + 1, b)
        if ca >= cb or cb - ca > MAX_CITACAO or not any(ch.isalnum() for ch in linha[ca:cb]):
            continue
        cits.append({"abre": a, "fecha": b, "a": ca, "b": cb, "bibl": _bibl_apos(linha, b + 1)})
    for a, b in internos:
        if any(c["a"] <= a and b < c["b"] for c in cits):
            trocar[a], trocar[b] = INTERNAS
    # agrupa as continuações: «A», diz Vogt, «B» (B continua A)
    grupos = []
    for c in cits:
        ant = grupos[-1][-1] if grupos else None
        if ant is not None and ant["bibl"] is None and _e_interrupcao(linha[ant["fecha"] + 1:c["abre"]]):
            grupos[-1].append(c)
        else:
            grupos.append([c])
    for g in grupos:
        palavras = sum(len(linha[c["a"]:c["b"]].split()) for c in g)
        bibl = g[-1]["bibl"]
        tipo = "direta" if (bibl or len(g) > 1 or palavras > PALAVRAS_MENCAO) else "mencao"
        ident = novo_id() if tipo == "direta" else None
        for k, c in enumerate(g):
            q = etree.Element("quote")
            q.set("type", tipo)
            if k == 0 and ident:
                q.set(XML_ID, ident)
            elif ident:
                q.set("corresp", "#" + ident)
            apagar.update(range(c["abre"], c["a"]))       # aspa de abertura + espaços
            apagar.update(range(c["b"], c["fecha"] + 1))  # espaços + aspa de fechamento
            embrulhos[c["a"]] = (c["b"], q)
        if bibl:
            b_el = etree.Element("bibl")
            b_el.set("corresp", "#" + ident)
            embrulhos[bibl[0]] = (bibl[1], b_el)
            rel.bibls += 1
        if tipo == "direta":
            rel.diretas += 1
            rel.continuacoes += len(g) - 1
            rel.ids.append(ident)
        else:
            rel.mencoes += 1
    if embrulhos:
        _reconstruir(el, itens, embrulhos, apagar, trocar)


_MISTOS = {"p", "head", "hi", "foreign", "label"}
_PULAR = {"quote", "bibl", "fw", "pb", "milestone"}


def _visitar(el, novo_id, rel):
    nome = nome_local(el.tag)
    if nome in _MISTOS:
        _marcar_nivel(el, novo_id, rel)
    for c in el:
        if not isinstance(c.tag, str):
            continue
        n = nome_local(c.tag)
        if n in ("quote", "bibl"):
            for nota in c.iter("note"):           # notas chamadas de dentro da citação
                _visitar(nota, novo_id, rel)
        elif n not in _PULAR:
            _visitar(c, novo_id, rel)


def marcar(raiz, novo_id):
    """Marca, no lugar, as citações por aspas no fragmento `raiz` (elemento lxml). -> Relatorio."""
    rel = Relatorio()
    if nome_local(raiz.tag) in ("milestone", "fw", "head"):
        return rel
    _visitar(raiz, novo_id, rel)
    return rel


def marcar_xml(xml, novo_id):
    """Fragmento (str) -> (fragmento marcado, Relatorio). Sem citação nova devolve o mesmo texto."""
    raiz = etree.fromstring(xml.encode("utf-8"))
    rel = marcar(raiz, novo_id)
    if not rel.total:
        return xml, rel
    return etree.tostring(raiz, encoding="unicode", with_tail=False), rel


# ------------------------------------------------------------- leitura dos segmentos
def texto(el, notas=False):
    """Texto de um segmento (sem cabeçalhos; notas só se pedido; <pb> vira espaço)."""
    partes = []

    def rec(e):
        partes.append(e.text or "")
        for c in e:
            if isinstance(c.tag, str):
                n = nome_local(c.tag)
                if n == "pb":
                    partes.append(" ")
                elif n == "note" and not notas or n == "fw":
                    pass
                else:
                    rec(c)
            partes.append(c.tail or "")

    rec(el)
    return re.sub(r"\s+", " ", "".join(partes)).strip()


def chave(el):
    """xml:id da citação a que um <quote>/<bibl> pertence (o próprio id ou o alvo de corresp)."""
    return el.get(XML_ID) or (el.get("corresp") or "").lstrip("#") or None


@dataclass
class Ocorrencia:
    """Uma citação num fragmento: seus segmentos (em ordem) e as referências do autor."""
    xml_id: str
    tipo: str
    segmentos: list = field(default_factory=list)   # elementos <quote>
    bibls: list = field(default_factory=list)       # elementos <bibl>

    @property
    def texto(self):
        return " […] ".join(texto(s) for s in self.segmentos)

    @property
    def referencia_autor(self):
        return " ".join(texto(b) for b in self.bibls)


def ocorrencias(raiz):
    """{xml_id: Ocorrencia} das citações (diretas/indiretas) do fragmento, na ordem do texto.
    Segmentos de continuação cujo 1º segmento está em outro bloco também entram (pela chave)."""
    out = {}
    for e in raiz.iter("quote", "bibl"):
        k = chave(e)
        if not k:
            continue
        oc = out.get(k)
        if e.tag == "quote":
            if oc is None:
                oc = out[k] = Ocorrencia(k, e.get("type"))
            if e.get(XML_ID):
                oc.tipo = e.get("type")
            oc.segmentos.append(e)
        else:
            if oc is None:
                oc = out[k] = Ocorrencia(k, "")
            oc.bibls.append(e)
    return out


def ocorrencias_xml(xml):
    try:
        return ocorrencias(etree.fromstring(xml.encode("utf-8")))
    except etree.XMLSyntaxError:
        return {}
