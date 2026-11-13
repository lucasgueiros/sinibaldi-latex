"""Apoio à leitura pública: árvore em memória, HTML de leitura (notas, páginas, procedência),
texto plano e busca. Nada aqui escreve no banco."""
import html as _html
import re
import unicodedata
from bisect import bisect_right

import lxml.html
from lxml import etree

from . import tei
from .models import Bloco, Edicao, No, Pagina, Revisao, Volume

# --------------------------------------------------------------------- árvore


class Arvore:
    """Todos os nós de uma edição, montados em memória com UMA consulta."""

    def __init__(self, edicao):
        self.edicao = edicao
        self.nos = list(No.objects.filter(edicao=edicao).order_by("ordem_ini"))
        self.por_id = {n.xml_id: n for n in self.nos}
        self.por_pk = {n.pk: n for n in self.nos}
        self.raizes = []
        for n in self.nos:
            n.filhos_lista = []
        for n in self.nos:
            pai = self.por_pk.get(n.pai_id)
            n.pai_obj = pai
            (pai.filhos_lista if pai else self.raizes).append(n)
        for n in self.nos:
            n.teses_lista = [f for f in n.filhos_lista if f.nivel == "tese"]
            n.outros_lista = [f for f in n.filhos_lista if f.nivel != "tese"]
        self._ini = [n.ordem_ini for n in self.nos]
        por_nivel = {}
        for n in self.nos:
            por_nivel.setdefault(n.nivel, []).append(n)
        self._irmaos = por_nivel
        self._pos_nivel = {n.pk: i for lista in por_nivel.values() for i, n in enumerate(lista)}

    def cobrindo(self, ordem):
        """Nó mais profundo cuja faixa cobre `ordem`, ou None."""
        i = bisect_right(self._ini, ordem) - 1
        n = self.nos[i] if i >= 0 else None
        while n is not None and not (n.ordem_ini <= ordem < n.ordem_fim):
            n = n.pai_obj
        return n

    def caminho(self, no):
        out = [no]
        while out[-1].pai_obj is not None:
            out.append(out[-1].pai_obj)
        return out[::-1]

    def vizinho(self, no, delta):
        lista = self._irmaos[no.nivel]
        i = self._pos_nivel[no.pk] + delta
        return lista[i] if 0 <= i < len(lista) else None

    def rotular_paginas(self, impressas):
        for n in self.nos:
            n.pag = impressas.get((n.volume_id, n.pagina_ini), "") if n.pagina_ini is not None else ""

    def descendentes_por_nivel(self, no=None):
        from collections import Counter
        c = Counter()
        for n in (self.nos if no is None else [d for d in self.nos if no.ordem_ini <= d.ordem_ini < no.ordem_fim and d is not no]):
            c[n.nivel] += 1
        return c


def impressas():
    """{(volume_id, seq): página impressa} para todas as páginas."""
    return {(v, s): (i or str(s)) for v, s, i in Pagina.objects.values_list("volume_id", "seq", "impressa")}


def titulo_do_no(no):
    return " ".join(x for x in (no.rotulo, no.titulo) if x) or no.xml_id


def contribuintes(edicao, ordem_ini=None, ordem_fim=None):
    """Nomes distintos dos autores de `Revisao` (exceto importação) no intervalo de blocos."""
    qs = Revisao.objects.filter(edicao=edicao, autor__isnull=False).exclude(acao=Revisao.IMPORTAR)
    if ordem_ini is not None:
        qs = qs.filter(bloco__ordem__gte=ordem_ini, bloco__ordem__lt=ordem_fim)
    nomes = set()
    for p, u, s in qs.order_by().values_list("autor__first_name", "autor__last_name", "autor__username").distinct():
        nomes.add((f"{p} {u}".strip()) or s)
    return sorted(nomes, key=str.casefold)


# ------------------------------------------------------------------- renderização
_PROC = {Bloco.COPIA: "cópia", Bloco.ADAPTADO: "adaptado", Bloco.NOVO: "novo"}


def _remover(el):
    """Remove `el` preservando o `tail`."""
    pai = el.getparent()
    if pai is None:
        return
    if el.tail:
        ant = el.getprevious()
        if ant is not None:
            ant.tail = (ant.tail or "") + el.tail
        else:
            pai.text = (pai.text or "") + el.tail
    pai.remove(el)


def _interno(el):
    partes = [_html.escape(el.text or "", quote=False)]
    for c in el:
        partes.append(etree.tostring(c, method="html", encoding="unicode", with_tail=True))
    return "".join(partes)


_RE_CHAVE_CIT = re.compile(r'<(?:quote|bibl)\b[^>]*?\b(?:xml:id="([^"]+)"|corresp="#([^"]+)")')


class DadosCitacoes:
    """`Citacao` (com fonte e tradução) por xml_id, para a renderização; uma consulta por bloco
    que traga chaves ainda não vistas."""

    def __init__(self):
        self._c = {}

    def para(self, xml):
        chaves = {a or b for a, b in _RE_CHAVE_CIT.findall(xml)}
        faltam = chaves - set(self._c)
        if faltam:
            from .models import Citacao
            for c in Citacao.objects.filter(xml_id__in=faltam).select_related("fonte", "traducao"):
                self._c[c.xml_id] = c
            for k in faltam:
                self._c.setdefault(k, None)
        return {k: self._c[k] for k in chaves if self._c.get(k) is not None}


def _aplicar_citacoes(h, dados, nova):
    """Referências precisas no HTML de um bloco. Na nova edição, a referência de Sinibaldi
    (`cite[data-tei=bibl]`) dá lugar à precisa — a original fica no `title` —, ou ela é acrescentada
    depois do último segmento quando Sinibaldi não deu nenhuma. Na 1916, só o `title`."""
    from . import referencias
    if not dados:
        return
    segs, bibls = {}, {}
    for el in h.xpath('.//*[@data-tei="quote"]'):
        k = el.get("data-xmlid") or (el.get("data-corresp") or "").lstrip("#")
        segs.setdefault(k, []).append(el)
    for el in h.xpath('.//*[@data-tei="bibl"]'):
        bibls.setdefault((el.get("data-corresp") or "").lstrip("#"), []).append(el)
    for k, c in dados.items():
        partes = referencias.partes(c)
        if not partes:
            continue
        txt = referencias.texto(partes)
        for q in segs.get(k, []):
            q.set("title", txt)
        if not nova:
            for b in bibls.get(k, []):
                b.set("title", "Referência precisa: " + txt)
                b.set("class", "ref-original")
            continue
        novo = lxml.html.fragment_fromstring(f'<span class="ref-precisa">{referencias.html(partes)}</span>')
        if bibls.get(k):
            b = bibls[k][0]
            if b.text_content().strip():
                novo.set("title", "Sinibaldi: " + " ".join(b.text_content().split()))
            for filho in list(b):
                b.remove(filho)
            b.text = None
            b.append(novo)
            for extra in bibls[k][1:]:
                _remover(extra)
        elif segs.get(k):
            ultimo = segs[k][-1]
            novo.tail = ultimo.tail
            ultimo.tail = " "
            ultimo.addnext(novo)


def renderizar(blocos, *, impressas_, modo="web", url_facsimile=None, origens=None, prefixo_id="", volumes=None,
               citacoes=None, nova=False):
    """HTML de leitura de uma sequência de blocos.

    Retorna `(html, notas)`; `notas` é lista de (n, html). `modo`: 'web' (links, marcas de
    procedência, âncoras) ou 'offline' (autônomo: sem links). `url_facsimile(volume_id, seq)`
    devolve a URL do fac-símile. `origens`: {pk do bloco: (url do trecho na 1916)}.
    `volumes`: {id: numero}. `citacoes`: `DadosCitacoes` (referências precisas; `nova` = trocar as de
    Sinibaldi por elas)."""
    partes, notas = [], []
    atual = None
    web = modo == "web"

    def criar_pb(seq, vol):
        imp = impressas_.get((vol, seq), str(seq))
        if web and url_facsimile:
            a = etree.Element("a", href=url_facsimile(vol, seq), title="Ver o fac-símile desta página")
            a.set("id", f"{prefixo_id}pag-{seq}")
        else:
            a = etree.Element("span")
        a.set("data-tei", "pb")
        a.set("data-n", imp)
        return a

    for b in blocos:
        if b.tipo in (Bloco.CABECALHO,) or b.procedencia == Bloco.SUPRIMIDO:
            continue
        h = lxml.html.fragment_fromstring(tei.fragmento_para_html(b.xml))
        if citacoes is not None and ("<quote" in b.xml or "<bibl" in b.xml):
            _aplicar_citacoes(h, citacoes.para(b.xml), nova)
        for fw in h.xpath('.//*[@data-tei="fw"]'):
            _remover(fw)
        if h.get("data-tei") == "fw":
            continue
        for pb in h.xpath('.//*[@data-tei="pb"]'):
            novo = criar_pb(int(pb.get("data-n")), b.volume_id)
            novo.tail = pb.tail
            pb.getparent().replace(pb, novo)
        for nt in h.xpath('.//*[@data-tei="note"]'):
            i = len(notas) + 1
            corpo = "<br>".join(_interno(p) for p in nt.xpath('./*[@data-tei="note-p"]')) or _interno(nt)
            notas.append((i, corpo))
            sup = etree.Element("sup", {"class": "nref"})
            a = etree.SubElement(sup, "a", href=f"#{prefixo_id}nota-{i}", id=f"{prefixo_id}ref-{i}")
            a.text = str(i)
            sup.tail = nt.tail
            nt.getparent().replace(nt, sup)
        if b.tipo != Bloco.MARCO and b.pagina is not None and b.pagina != atual:
            partes.append(etree.tostring(criar_pb(b.pagina, b.volume_id), method="html", encoding="unicode"))
        if web:
            h.set("id", f"b{b.pk}")
            if volumes is not None and b.procedencia in _PROC and h.get("data-tei") != "milestone":
                proc = etree.Element("span", {"class": f"proc proc-{b.procedencia}"})
                url = (origens or {}).get(b.pk)
                if url:
                    a = etree.SubElement(proc, "a", href=url, title="Ver o trecho correspondente na edição de 1916/17")
                    a.text = _PROC[b.procedencia]
                else:
                    proc.text = _PROC[b.procedencia]
                h.insert(0, proc)
        partes.append(etree.tostring(h, method="html", encoding="unicode", with_tail=False))
        if b.pagina is not None and b.tipo != Bloco.MARCO:
            atual = b.pagina
        # a última marca <pb n> do bloco (seq) define a página corrente
        raiz = etree.fromstring(b.xml.encode("utf-8"))
        u = tei.ultima_pagina(raiz)
        if u is not None:
            atual = u
    return "\n".join(partes), notas


# ------------------------------------------------------------------------ texto plano / busca
_TAGS = re.compile(r"<[^>]+>")
_FW = re.compile(r"<fw\b[^>]*>.*?</fw>", re.S)
_NOTA = re.compile(r"<note\b.*?</note>", re.S)
_ESP = re.compile(r"\s+")
_memo = {}


def texto_plano(xml, notas=True):
    s = _FW.sub("", xml)
    if not notas:
        s = _NOTA.sub("", s)
    s = _TAGS.sub(" ", s.replace("</p>", " ").replace("<pb", " <pb"))
    return _ESP.sub(" ", _html.unescape(s)).strip()


def _nc(ch):
    r = _memo.get(ch)
    if r is None:
        d = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)).lower()
        r = d[0] if d else ch.lower()
        _memo[ch] = r
    return r


def normalizar(s):
    """Minúsculas sem acentos, com o MESMO comprimento da entrada (para realçar trechos)."""
    return "".join(map(_nc, s))


_cache_busca = {}


def corpus_busca(edicao):
    """[(bloco_pk, ordem, plain, norm)] da edição, em cache por processo (invalidado por alteração)."""
    from django.db.models import Count, Max
    ag = Bloco.objects.filter(edicao=edicao).aggregate(n=Count("id"), m=Max("atualizado_em"))
    chave = (ag["n"], ag["m"])
    hit = _cache_busca.get(edicao.pk)
    if hit and hit[0] == chave:
        return hit[1]
    dados = []
    qs = (Bloco.objects.filter(edicao=edicao).exclude(tipo__in=[Bloco.CABECALHO, Bloco.MARCO])
          .exclude(procedencia=Bloco.SUPRIMIDO).order_by("ordem").values_list("pk", "ordem", "xml"))
    for pk, ordem, xml in qs.iterator(chunk_size=2000):
        p = texto_plano(xml)
        if p:
            dados.append((pk, ordem, p, normalizar(p)))
    _cache_busca[edicao.pk] = (chave, dados)
    return dados


def buscar(edicao, q, limite=1000):
    """Blocos cujo texto contém todas as palavras de `q` (sem distinguir acentos/caixa).
    Retorna lista de (pk, ordem, trecho_html)."""
    termos = [t for t in normalizar(q).split() if t]
    if not termos:
        return []
    achados = []
    for pk, ordem, plain, norm in corpus_busca(edicao):
        if all(t in norm for t in termos):
            achados.append((pk, ordem, _trecho(plain, norm, termos)))
            if len(achados) >= limite:
                break
    return achados


def _trecho(plain, norm, termos, antes=90, depois=200):
    p = min(norm.find(t) for t in termos)
    ini = max(0, p - antes)
    fim = min(len(plain), p + depois)
    if ini:
        ini = plain.rfind(" ", 0, ini + 15) + 1 or ini
    marcas = []
    for t in termos:
        i = norm.find(t, ini)
        while i != -1 and i < fim:
            marcas.append((i, i + len(t)))
            i = norm.find(t, i + len(t))
    marcas.sort()
    out, pos = [], ini
    for a, z in marcas:
        if a < pos:
            continue
        out.append(_html.escape(plain[pos:a]))
        out.append("<mark>" + _html.escape(plain[a:z]) + "</mark>")
        pos = z
    out.append(_html.escape(plain[pos:fim]))
    return ("… " if ini else "") + "".join(out) + (" …" if fim < len(plain) else "")


def slug_arquivo(texto, limite=48):
    from django.utils.text import slugify
    return slugify(texto)[:limite].strip("-")
