"""Citações no formato ABNT (NBR 10520 — citações; NBR 6023 — referências) para Word e LaTeX.

Puro: recebe dados, devolve texto. Nada aqui toca o banco nem o HTTP; ver `views_citacao.py`.

Saídas de `montar`:
- `chamada`: chamada autor-data, «(SINIBALDI, 1917, v. 1, p. 12)»;
- `citacao_*`: o trecho como citação direta — curta (até `LIMITE_CURTA` caracteres, entre aspas, no
  parágrafo) ou longa (recuo de 4 cm, corpo 10, sem aspas, chamada ao fim);
- `referencia`: a referência completa, em segmentos `(texto, negrito)`;
- `docx()`, `latex()`, `texto()`: os três formatos de exportação.
"""
import io
import re
import zipfile
from dataclasses import dataclass, field

AUTOR_SOBRENOME = "SINIBALDI"
AUTOR_NOME = "Thiago"
OBRA = "Elementos de philosophia"
LOCAL = "Roma"
EDITORA = "[s. n.]"
# edição impressa de cada volume (ver `importar_tei.VOLUMES` e a descrição da edição diplomática)
EDICAO_VOLUME = {1: "5. ed.", 2: "4. ed."}

LIMITE_CURTA = 300          # NBR 10520: até 3 linhas vão no parágrafo, entre aspas
LIMITE_TRECHO = 5000        # acima disto o pedido é recusado (nunca truncamos uma citação em silêncio)

MESES = ["jan.", "fev.", "mar.", "abr.", "maio", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez."]


def data_acesso(d):
    """`13 nov. 2026` (abreviação de mês da NBR 6023)."""
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


def limpar_trecho(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


_ASPAS_DUPLAS = re.compile(r'["“”«»„]')


def aspas_simples(texto):
    """Dentro de uma citação entre aspas, as aspas do original passam a simples (NBR 10520)."""
    return _ASPAS_DUPLAS.sub("'", texto)


def paginas(pi, pf):
    """`p. 12` ou `p. 12-13`; vazio se não houver página."""
    if not pi and not pf:
        return ""
    pi, pf = pi or pf, pf or pi
    return f"p. {pi}" if pi == pf else f"p. {pi}-{pf}"


@dataclass
class Citacao:
    ano: object = None
    volume: object = None          # número do volume ou None
    titulo_volume: str = ""
    edicao_txt: str = ""           # "5. ed."
    nota_edicao: str = ""          # "Edição digital adaptada" (nova edição)
    pi: str = ""
    pf: str = ""
    trecho: str = ""
    url: str = ""
    acesso: str = ""
    chave: str = "sinibaldi"
    extra: dict = field(default_factory=dict)

    # --------------------------------------------------------------- chamada
    @property
    def _miolo_chamada(self):
        partes = [AUTOR_SOBRENOME, str(self.ano) if self.ano else "s.d."]
        if self.volume:
            partes.append(f"v. {self.volume}")
        pg = paginas(self.pi, self.pf)
        if pg:
            partes.append(pg)
        return ", ".join(partes)

    @property
    def chamada(self):
        return f"({self._miolo_chamada})"

    @property
    def chamada_narrativa(self):
        """Autor no texto: `Sinibaldi (1917, v. 1, p. 12)`."""
        partes = [str(self.ano) if self.ano else "s.d."]
        if self.volume:
            partes.append(f"v. {self.volume}")
        pg = paginas(self.pi, self.pf)
        if pg:
            partes.append(pg)
        return f"{AUTOR_SOBRENOME.capitalize()} ({', '.join(partes)})"

    # --------------------------------------------------------------- citação
    @property
    def longa(self):
        return len(self.trecho) > LIMITE_CURTA

    @property
    def citacao_corpo(self):
        """O trecho como vai no documento (aspas simples internas, e aspas duplas se curta)."""
        if not self.trecho:
            return ""
        if self.longa:
            return self.trecho
        return f"“{aspas_simples(self.trecho)}”"

    @property
    def citacao_texto(self):
        if not self.trecho:
            return ""
        return f"{self.citacao_corpo} {self.chamada}" + ("" if self.longa else ".")

    # ------------------------------------------------------------- referência
    @property
    def referencia(self):
        """Referência NBR 6023 em segmentos `(texto, negrito)`."""
        seg = [(f"{AUTOR_SOBRENOME}, {AUTOR_NOME}. ", False), (OBRA, True)]
        sub = self.titulo_volume
        seg.append((f": {sub}. " if sub else ". ", False))
        resto = []
        if self.nota_edicao:
            resto.append(self.nota_edicao + ".")
        if self.edicao_txt:
            resto.append(self.edicao_txt)
        resto.append(f"{LOCAL}: {EDITORA}, {self.ano or '[s. d.]'}.")
        if self.volume:
            resto.append(f"v. {self.volume}" + (f", {paginas(self.pi, self.pf)}." if paginas(self.pi, self.pf) else "."))
        elif paginas(self.pi, self.pf):
            resto.append(paginas(self.pi, self.pf) + ".")
        if self.url:
            resto.append(f"Disponível em: <{self.url}>.")
            if self.acesso:
                resto.append(f"Acesso em: {self.acesso}.")
        seg.append((" ".join(resto), False))
        return seg

    @property
    def referencia_texto(self):
        return "".join(t for t, _ in self.referencia)

    # ---------------------------------------------------------------- texto
    def texto(self):
        out = []
        if self.trecho:
            out += ["CITAÇÃO" + (" (longa: recuo de 4 cm, corpo 10, sem aspas)" if self.longa else ""),
                    self.citacao_texto, ""]
            out += ["Autor no texto: " + self.chamada_narrativa, ""]
        out += ["REFERÊNCIA", self.referencia_texto, ""]
        return "\n".join(out)

    # ---------------------------------------------------------------- LaTeX
    def latex(self):
        """Fragmento para `abntex2` + `abntex2cite` (BibTeX), com a entrada `.bib` ao fim."""
        pg = paginas(self.pi, self.pf).replace(" ", "~", 1)
        opc = ", ".join(x for x in ([f"v.~{self.volume}"] if self.volume else []) + ([pg] if pg else []))
        cite = f"\\cite[{opc}]{{{self.chave}}}" if opc else f"\\cite{{{self.chave}}}"
        cite_n = f"\\citeonline[{opc}]{{{self.chave}}}" if opc else f"\\citeonline{{{self.chave}}}"
        L = ["% Preâmbulo: \\documentclass{abntex2}  e  \\usepackage[brazilian,alf]{abntex2cite}",
             "% Fim do documento: \\bibliography{referencias}  (o arquivo está no fim deste trecho)", ""]
        if self.trecho:
            corpo = escapar_tex(self.trecho if self.longa else aspas_simples(self.trecho))
            if self.longa:
                L += ["% Citação direta longa (mais de 3 linhas): recuo de 4 cm, corpo 10, sem aspas",
                      "\\begin{citacao}", corpo + " " + cite, "\\end{citacao}"]
            else:
                L += ["% Citação direta curta: no parágrafo, entre aspas", f"“{corpo}” {cite}."]
            L += ["", "% Autor no texto:", cite_n, ""]
        else:
            L += [f"% Chamada: {cite}", f"% Autor no texto: {cite_n}", ""]
        L += ["% ---- referencias.bib ----", self.bibtex()]
        return "\n".join(L) + "\n"

    def bibtex(self):
        campos = [("author", f"{AUTOR_SOBRENOME.capitalize()}, {AUTOR_NOME}"),
                  ("title", f"{OBRA}: {self.titulo_volume}" if self.titulo_volume else OBRA)]
        if self.nota_edicao:
            campos.append(("note", self.nota_edicao))
        if self.edicao_txt:
            campos.append(("edition", self.edicao_txt.split(".")[0]))
        campos += [("address", LOCAL), ("publisher", EDITORA), ("year", str(self.ano) if self.ano else "s.d.")]
        if self.volume:
            campos.append(("volume", str(self.volume)))
        if self.url:
            campos.append(("url", self.url))
            if self.acesso:
                campos.append(("urlaccessdate", self.acesso))
        corpo = ",\n".join(f"  {k} = {{{escapar_bib(v)}}}" for k, v in campos)
        return f"@book{{{self.chave},\n{corpo}\n}}"

    # ----------------------------------------------------------------- HTML
    def html_referencia(self):
        from django.utils.html import escape
        return "".join((f"<strong>{escape(t)}</strong>" if neg else escape(t)) for t, neg in self.referencia)

    # ----------------------------------------------------------------- docx
    def docx(self):
        """Documento Word (.docx) com a citação e a referência, nas margens e corpos da ABNT."""
        ps = []
        if self.trecho:
            if self.longa:
                ps.append(_p([(self.citacao_corpo + " " + self.chamada, False)], tam=20, esq=2268, espaco=240, jus=True))
            else:
                ps.append(_p([(self.citacao_texto, False)], tam=24, espaco=360, jus=True, recuo1=709))
            ps.append(_p([], tam=24))
        ps.append(_p([("REFERÊNCIAS", True)], tam=24, centro=True))
        ps.append(_p([], tam=24))
        ps.append(_p(self.referencia, tam=24, espaco=240, jus=False))
        return _empacotar_docx("".join(ps))


# --------------------------------------------------------------------------- escapes
_TEX = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
        "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def escapar_tex(s):
    return "".join(_TEX.get(c, c) for c in s)


def escapar_bib(s):
    """Dentro de `{…}` do BibTeX só `\\`, `&`, `%`, `$`, `#`, `_` e `~`/`^` pedem cuidado; chaves, se houver, são raras."""
    return "".join(_TEX.get(c, c) for c in s if c not in "{}")


# ----------------------------------------------------------------------------- docx
def _xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _p(segmentos, tam=24, esq=0, espaco=240, jus=False, centro=False, recuo1=0):
    ppr = f'<w:spacing w:line="{espaco}" w:lineRule="auto" w:after="0"/>'
    if esq or recuo1:
        ppr += f'<w:ind w:left="{esq}"' + (f' w:firstLine="{recuo1}"' if recuo1 else "") + "/>"
    ppr += '<w:jc w:val="center"/>' if centro else ('<w:jc w:val="both"/>' if jus else '<w:jc w:val="left"/>')
    runs = ""
    for texto, neg in segmentos:
        rpr = f'<w:sz w:val="{tam}"/><w:szCs w:val="{tam}"/>' + ("<w:b/>" if neg else "")
        runs += f'<w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{_xml(texto)}</w:t></w:r>'
    return f"<w:p><w:pPr>{ppr}</w:pPr>{runs}</w:p>"


_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _empacotar_docx(corpo):
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document {_NS}><w:body>{corpo}'
        # A4; margens ABNT: 3 cm esquerda/superior, 2 cm direita/inferior
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1701" w:right="1134" w:bottom="1134" w:left="1701" w:header="709" w:footer="709" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>")
    estilos = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles {_NS}><w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman"/>'
        '<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="pt-BR"/></w:rPr></w:rPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style></w:styles>')
    tipos = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>")
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>")
    rels_doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", tipos)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", documento)
        z.writestr("word/styles.xml", estilos)
        z.writestr("word/_rels/document.xml.rels", rels_doc)
    return buf.getvalue()
