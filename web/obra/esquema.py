"""Dialeto de fragmento: o vocabulário FECHADO do XML guardado em cada `Bloco`.

Cada bloco é UM elemento, sem prefixo nem declaração de namespace:

  blocos   <milestone unit n xml:id/>  (marco)     <head [type=rotulo]>  (titulo)
           <p [type] [xml:id]>         (paragrafo) <argument><p/>…</argument> (sumario)
           <fw type="header">          (cabecalho)
           <figure xml:id><graphic url width/>[<head>legenda</head>][<p>detalhes</p>]</figure>  (gravura)
  inline   <hi rend>, <label>, <foreign xml:lang>, <pb n facs/>, <note place n xml:id>,
           <anchor type="asterisco"/> (componente semântico: o ∗ de divisão de assunto, no corpo ou em nota),
           <fw type="header"> (cabeçalho corrente que o OCR deixou no meio de um parágrafo),
           <quote type xml:id corresp> (citação; ver abaixo), <bibl corresp> (referência do autor)

Citação (`<quote>`): o texto vai SEM aspas — quem as desenha é quem renderiza (`«»` nas diretas,
nada nas indiretas). O 1º segmento leva `xml:id` (a chave de `Citacao`, onde ficam os dados
estruturados); um segmento que continua a mesma citação depois de texto do autor («algo é
assim», porém, «e assado») leva `corresp="#<id do 1º>"` e nenhum `xml:id`. `<bibl corresp>` marca
a referência que o próprio Sinibaldi deu, «(Post. anal., l. I)», e liga-a à citação. Sem citação
dentro de citação nem `<bibl>` dentro de `<bibl>`. `type="mencao"` (termo entre aspas, sem fonte)
dispensa o `xml:id`.

`<note>` contém só `<p>` (sem nota dentro de nota). Gravura (componente semântico): o recorte de uma
ilustração do fac-símile. `graphic/@url` = `paginas/NNNN.png#xywh=x,y,l,a` (imagem da página, relativa
ao diretório do volume, + fragmento de mídia W3C com a caixa em pixels do PNG original); `@width`
opcional em % da largura do texto; `<head>` opcional = legenda principal ("FIGURA VIII. — Côrte…"); `<p>`
opcional = detalhes impressos abaixo dela, em corpo menor ("A, hemispherio…; — B, …"). Ambos só com
itálico/versalete/negrito/latim/rótulo.
O `xml:id` (`vN.gravura-…`) é obrigatório: o prefixo do volume localiza a imagem. Tudo é definido aqui; as telas
montam barras de ferramentas a partir de `NIVEIS`, `TIPOS_PARAGRAFO`, `REND`.
"""
import re

from lxml import etree

NS_XML = "http://www.w3.org/XML/1998/namespace"

# --- rótulos legíveis (ordem = ordem hierárquica / de menu) -----------------
NIVEIS = {  # do mais alto ao mais baixo
    "anexo": "Anexo",   # aparato do fim do volume (Synopse, Indice das materias): fecha tudo e não tem filhos
    "parte": "Parte",
    "seccao": "Secção",
    "capitulo": "Capítulo",
    "artigo": "Artigo",
    "tese": "Tese",
    # Peça pré-textual (folha de rosto, imprimatur, carta de aprovação, prefácio…). Não pertence à hierarquia
    # da obra: fica por último só para que o marco não feche nem abra nenhum outro nó — a seguinte peça, ou a
    # primeira parte, fecha a anterior, e nunca tem filhos.
    "pretextual": "Pretextual",
}
NIVEIS_ORDEM = tuple(NIVEIS)

# Tipos de peça pré-textual (sufixo do xml:id `vN.pre-<tipo>[-n]` do marco). Só os que têm texto impresso no
# scan viram nó; capa e contracapa existem como componente, mas os scans não trazem capa impressa.
PRETEXTUAIS = {
    "capa": "Capa",
    "contracapa": "Contracapa",
    "rosto": "Folha de rosto",
    "imprimatur": "Imprimatur",
    "aprovacao": "Aprovação (approbatio)",
    "dedicatoria": "Dedicatória",
    "prefacio": "Prefácio",
    "carta": "Carta de aprovação",
    "outro": "Outra peça pré-textual",
}

TIPOS_PARAGRAFO = {
    "definicao": "Definição",
    "divisao": "Divisão",
    "enunciado": "Tese",
    "argumento": "Argumento",
    "objecao": "Objeção",
    "resposta": "Resposta",
    "escolio": "Escólio",
    "corolario": "Corolário",
    "observacao": "Observação",
    "anexo-titulo": "Título no anexo",   # divisão citada na Synopse/Índice (não é estrutura)
    "indice": "Entrada do índice",
    # entradas do índice GERADO dos títulos (obra/indice.py), uma por nível; a página vai em <label>
    "indice-parte": "Índice: parte",
    "indice-seccao": "Índice: secção",
    "indice-capitulo": "Índice: capítulo",
    "indice-artigo": "Índice: artigo",
    # pré-textuais: o tipo diz a função tipográfica da linha (como o `type` de `anexo-titulo`)
    "titulo-obra": "Título da obra",              # «ELEMENTOS DE PHILOSOPHIA» na folha de rosto
    "centro": "Linha centrada",                   # autor, volume, edição, imprenta, dedicatória
    "enderecamento": "Endereçamento da carta",    # «AO VENERAVEL IRMÃO / MANUEL BISPO DE COIMBRA»
    "saudacao": "Saudação",                       # «Veneravel Irmão,» «Saude e Benção Apostolica.»
    "data-local": "Data e lugar",                 # «Dado em Roma, junto de S. Pedro, …»
    "fecho": "Fecho (assinatura)",                # «LEÃO XIII, PAPA» — à direita
}

REND = {"it": "Itálico", "bold": "Negrito", "sc": "Versalete"}

TIPOS_CITACAO = {
    "direta": "Citação direta",        # entre aspas; dados em Citacao
    "indireta": "Citação indireta",    # paráfrase, sem aspas; dados em Citacao
    "mencao": "Menção (termo entre aspas)",  # «racional», «arte das artes»: aspas sem fonte, sem dados
}
TIPOS_COM_DADOS = ("direta", "indireta")

TIPOS_BLOCO = {
    "marco": "Marco de divisão",
    "titulo": "Título",
    "paragrafo": "Parágrafo",
    "sumario": "Sumário",
    "cabecalho": "Cabeçalho corrente",
    "gravura": "Gravura",
}

TIPO_DA_RAIZ = {  # elemento raiz -> Bloco.tipo
    "milestone": "marco",
    "head": "titulo",
    "p": "paragrafo",
    "argument": "sumario",
    "fw": "cabecalho",
    "figure": "gravura",
}

# Atributos permitidos por elemento, NA ORDEM CANÔNICA de serialização.
ATRIBUTOS = {
    "milestone": ("unit", "n", "xml:id"),
    "head": ("type",),
    "p": ("type", "xml:id"),
    "argument": (),
    "fw": ("type",),
    "hi": ("rend",),
    "label": (),
    "foreign": ("xml:lang",),
    "pb": ("n", "facs"),
    "anchor": ("type",),
    "note": ("place", "n", "xml:id"),
    "quote": ("type", "xml:id", "corresp"),
    "bibl": ("corresp",),
    "figure": ("xml:id",),
    "graphic": ("url", "width"),
}

# Valores fechados de alguns atributos. None = qualquer valor não vazio.
VALORES = {
    ("milestone", "unit"): set(NIVEIS),
    ("head", "type"): {"rotulo"},
    ("p", "type"): set(TIPOS_PARAGRAFO),
    ("fw", "type"): {"header"},
    ("hi", "rend"): set(REND),
    ("note", "place"): {"foot"},
    ("anchor", "type"): {"asterisco"},
    ("quote", "type"): set(TIPOS_CITACAO),
}

INLINE = ("hi", "label", "foreign", "pb", "anchor", "note", "fw", "quote", "bibl")
INLINE_EM_NOTA = ("hi", "label", "foreign", "pb", "anchor", "fw", "quote", "bibl")  # sem nota dentro de nota
INLINE_EM_LEGENDA = ("hi", "label", "foreign")  # <head> de <figure>
SEM_AUTOANINHAR = ("quote", "bibl")  # nem citação dentro de citação, nem bibl dentro de bibl
VAZIOS = ("milestone", "pb", "anchor", "graphic")  # elementos sem conteúdo

# graphic/@url de uma gravura: imagem da página + caixa (x, y, largura, altura) em pixels do PNG original.
RE_URL_GRAVURA = re.compile(r"^paginas/(?P<arquivo>[A-Za-z0-9_-]+)\.png#xywh=(?P<x>\d+),(?P<y>\d+),(?P<l>\d+),(?P<a>\d+)$")
RE_LARGURA_GRAVURA = re.compile(r"^(100|[1-9][0-9]?)%$")
RE_VOLUME_ID = re.compile(r"^v(\d+)\.")


def caixa_da_gravura(url):
    """`paginas/0034.png#xywh=1,2,3,4` -> ('0034', (1, 2, 3, 4)) ou None."""
    m = RE_URL_GRAVURA.match(url or "")
    if not m:
        return None
    return m.group("arquivo"), tuple(int(m.group(k)) for k in "xyla")


def nome_atributo(qname):
    """`{ns}id` -> `xml:id`."""
    if qname.startswith("{" + NS_XML + "}"):
        return "xml:" + qname.split("}", 1)[1]
    return qname


def qname_atributo(nome):
    return "{%s}%s" % (NS_XML, nome[4:]) if nome.startswith("xml:") else nome


def nome_local(tag):
    return tag.split("}", 1)[1] if isinstance(tag, str) and tag.startswith("{") else tag


def permitidos_em(nome, contexto):
    """Filhos de elemento permitidos em cada contexto de conteúdo."""
    if contexto == "inline":
        return INLINE
    if contexto == "inline_nota":
        return INLINE_EM_NOTA
    if contexto == "inline_legenda":
        return INLINE_EM_LEGENDA
    return ()


def contexto_dos_filhos(nome, contexto):
    """Contexto de conteúdo dos filhos de `nome`, dado o contexto em que ele aparece."""
    if nome in ("p", "head", "fw", "hi", "label", "foreign", "quote", "bibl"):
        if contexto in ("inline_nota", "inline_legenda", "figura"):
            return "inline_nota" if contexto == "inline_nota" else "inline_legenda"
        return "inline"
    return None


def tipo_do_fragmento(xml):
    """Bloco.tipo de um fragmento ('' se a raiz não for válida)."""
    try:
        raiz = etree.fromstring(xml)
    except etree.XMLSyntaxError:
        return ""
    return TIPO_DA_RAIZ.get(nome_local(raiz.tag), "")


def _texto_curto(el):
    return "<%s>" % nome_local(el.tag) if isinstance(el.tag, str) else "comentário/instrução"


def _validar_atributos(el, nome, erros):
    permitidos = ATRIBUTOS[nome]
    for chave, valor in el.attrib.items():
        a = nome_atributo(chave)
        if a not in permitidos:
            erros.append(f"Atributo '{a}' não é permitido em <{nome}>.")
            continue
        validos = VALORES.get((nome, a))
        if validos is not None and valor not in validos:
            erros.append(f"Valor '{valor}' inválido para {a} em <{nome}> (aceitos: {', '.join(sorted(validos))}).")
        elif validos is None and not valor.strip():
            erros.append(f"Atributo '{a}' vazio em <{nome}>.")
    if nome == "fw" and el.get(qname_atributo("type")) != "header":
        erros.append('<fw> exige type="header".')
    if nome == "milestone":
        if not el.get("unit"):
            erros.append('<milestone> exige o atributo "unit".')
    if nome == "note" and el.get("place") is None:
        erros.append('<note> exige place="foot".')
    if nome == "anchor" and not el.get("type"):
        erros.append('<anchor> exige type="asterisco".')
    if nome == "pb" and el.get("n") is None:
        erros.append('<pb> exige o atributo "n".')
    if nome == "figure" and not el.get(qname_atributo("xml:id")):
        erros.append('<figure> exige xml:id (vN.gravura-…).')
    if nome == "graphic":
        url = el.get("url")
        cx = caixa_da_gravura(url)
        if cx is None:
            erros.append(f"<graphic> exige url=\"paginas/NNNN.png#xywh=x,y,largura,altura\" (recebido: {url!r}).")
        elif cx[1][2] <= 0 or cx[1][3] <= 0:
            erros.append("<graphic>: a caixa da gravura tem largura ou altura zero.")
        w = el.get("width")
        if w is not None and not RE_LARGURA_GRAVURA.match(w):
            erros.append(f"<graphic>: width deve ser uma porcentagem de 1% a 100% (recebido: {w!r}).")
    if nome == "quote":
        if el.get("type") is None:
            erros.append('<quote> exige type="direta" ou "indireta".')
        ident, corresp = el.get(qname_atributo("xml:id")), el.get("corresp")
        if ident and corresp:
            erros.append("<quote> tem xml:id (1º segmento) OU corresp (continuação), não os dois.")
        elif not ident and not corresp and el.get("type") in TIPOS_COM_DADOS:
            erros.append("<quote> sem xml:id nem corresp: toda citação precisa de identificador.")
    if nome in ("quote", "bibl"):
        corresp = el.get("corresp")
        if corresp is not None and not re.fullmatch(r"#[A-Za-z_][\w.\-]*", corresp):
            erros.append(f"corresp inválido em <{nome}>: {corresp!r} (esperado '#<xml:id da citação>').")


def _dentro_de(el, nome):
    """`el` tem um ancestral `nome` antes de qualquer <note> (a nota é outro texto)?"""
    for a in el.iterancestors():
        n = nome_local(a.tag)
        if n == "note":
            return False
        if n == nome:
            return True
    return False


def _validar_elemento(el, contexto, erros):
    """`contexto`: None (raiz), 'inline', 'inline_nota', 'nota', 'argumento'."""
    if not isinstance(el.tag, str):
        erros.append("Comentários e instruções de processamento não são permitidos.")
        return
    if el.tag.startswith("{"):
        erros.append(f"Elemento com namespace não é permitido: {el.tag}.")
        return
    nome = el.tag
    if nome not in ATRIBUTOS:
        erros.append(f"Elemento <{nome}> fora do vocabulário.")
        return
    if contexto is None:
        if nome not in TIPO_DA_RAIZ:
            erros.append(f"<{nome}> não pode ser um bloco (blocos: {', '.join(TIPO_DA_RAIZ)}).")
            return
    elif contexto == "argumento":
        if nome != "p":
            erros.append(f"<argument> só pode conter <p>, não <{nome}>.")
            return
    elif contexto == "nota":
        if nome != "p":
            erros.append(f"<note> só pode conter <p>, não <{nome}>.")
            return
    elif nome in SEM_AUTOANINHAR and _dentro_de(el, nome):
        erros.append("Citação dentro de citação não é permitida." if nome == "quote"
                     else "<bibl> dentro de <bibl> não é permitido.")
        return
    elif contexto == "figura":
        if nome not in ("graphic", "head", "p"):
            erros.append(f"<figure> só pode conter <graphic>, <head> e <p>, não <{nome}>.")
            return
    elif nome not in permitidos_em(nome, contexto):
        if nome == "note" and contexto == "inline_nota":
            erros.append("Nota dentro de nota não é permitida.")
        else:
            erros.append(f"<{nome}> não é permitido neste ponto.")
        return
    _validar_atributos(el, nome, erros)

    if nome in VAZIOS:
        if len(el) or (el.text and el.text.strip()):
            erros.append(f"<{nome}> deve ser vazio.")
        return
    if nome == "figure":
        if (el.text and el.text.strip()) or any(f.tail and f.tail.strip() for f in el):
            erros.append("<figure> não aceita texto solto; a legenda vai em <head>.")
        nomes = [f.tag for f in el if isinstance(f.tag, str)]
        if nomes[:1] != ["graphic"] or nomes.count("graphic") != 1:
            erros.append("<figure> exige um único <graphic>, como primeiro filho.")
        if nomes.count("head") > 1:
            erros.append("<figure> aceita no máximo um <head> (legenda).")
        if nomes.count("p") > 1:
            erros.append("<figure> aceita no máximo um <p> (detalhes da legenda).")
        if [n for n in nomes if n in ("head", "p")] == ["p", "head"]:
            erros.append("<figure>: a legenda (<head>) vem antes dos detalhes (<p>).")
        for filho in el:
            _validar_elemento(filho, "figura", erros)
        return
    if nome in ("argument", "note"):
        if el.text and el.text.strip():
            erros.append(f"<{nome}> não aceita texto solto; use <p>.")
        for filho in el:
            if filho.tail and filho.tail.strip():
                erros.append(f"<{nome}> não aceita texto solto; use <p>.")
            _validar_elemento(filho, "argumento" if nome == "argument" else "nota", erros)
        if nome == "note" and not len(el):
            erros.append("<note> sem parágrafo.")
        return
    # conteúdo misto
    if contexto in ("nota",):
        ctx = "inline_nota"
    elif contexto == "argumento":
        ctx = "inline"
    else:
        ctx = contexto_dos_filhos(nome, contexto)
    for filho in el:
        _validar_elemento(filho, ctx, erros)


def validar_fragmento(xml):
    """Valida UM fragmento. Retorna lista de erros em português (vazia = ok)."""
    if not isinstance(xml, str) or not xml.strip():
        return ["Fragmento vazio."]
    try:
        raiz = etree.fromstring(xml.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        return [f"XML malformado: {e}"]
    erros = []
    _validar_elemento(raiz, None, erros)
    # duplicatas de xml:id dentro do fragmento
    ids = [e.get(qname_atributo("xml:id")) for e in raiz.iter() if isinstance(e.tag, str)]
    vistos = set()
    for i in ids:
        if i is None:
            continue
        if i in vistos:
            erros.append(f"xml:id repetido no fragmento: {i}.")
        vistos.add(i)
    return erros


def ids_do_fragmento(xml):
    try:
        raiz = etree.fromstring(xml.encode("utf-8"))
    except etree.XMLSyntaxError:
        return []
    return [i for i in (e.get(qname_atributo("xml:id")) for e in raiz.iter() if isinstance(e.tag, str)) if i]


def validar_blocos(blocos):
    """Valida uma sequência de blocos (strings XML, dicts com 'xml' ou objetos com `.xml`).

    Retorna lista de erros; cada um prefixado por 'Bloco N: '. Também detecta
    `xml:id` repetido entre blocos distintos."""
    erros = []
    vistos = {}
    for i, b in enumerate(blocos, 1):
        xml = b if isinstance(b, str) else (b.get("xml") if isinstance(b, dict) else b.xml)
        for e in validar_fragmento(xml):
            erros.append(f"Bloco {i}: {e}")
        for ident in ids_do_fragmento(xml or ""):
            if ident in vistos and vistos[ident] != i:
                erros.append(f"Bloco {i}: xml:id '{ident}' já usado no bloco {vistos[ident]}.")
            vistos.setdefault(ident, i)
    return erros
