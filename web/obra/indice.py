"""«Indice das materias» gerado a partir dos títulos da edição.

O índice impresso no fim de cada volume foi para o OCR em linhas picotadas, com os números de página
trocados por ruído. Em vez de revisá-lo à mão, ele é REFEITO da árvore de nós: cada parte, secção,
capítulo e artigo vira uma entrada `<p type="indice-<nivel>">rótulo — título<label>pág.</label></p>`,
na ordem do texto; a página é a impressa do primeiro bloco do nó. Como a fonte são os títulos, corrigir
um título e rodar `gerar_indice` de novo basta para o índice acompanhar.

Só mexe nos blocos do nó `anexo` `vN.indice` (depois do marco e do `<head>`); o resto da edição fica
como está. Aplicado pelo comando `gerar_indice`.
"""
import re

from lxml import etree

from . import leitura
from .models import Bloco, No

COMENTARIO = "Índice das matérias gerado a partir dos títulos (gerar_indice)."
NIVEIS_INDICE = ("parte", "seccao", "capitulo", "artigo")
TIPO_ENTRADA = {n: f"indice-{n}" for n in NIVEIS_INDICE}
_PAGINA_NO_TITULO = re.compile(r"\s*[—–-]\s*\d{1,3}\s*$")      # cabeçalho corrente grudado: «TITULO — 65»
_ESPACOS = re.compile(r"\s+")


_NUMERAL = re.compile(r"^(?P<ini>\S+\s+)(?P<num>[IVXLCDM|l1]{1,8})(?P<fim>\.?)$")
_ROMANO = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_PAGINA_SOLTA = re.compile(r"\s+\d{1,3}$")
_LIXO_INICIAL = re.compile(r"^\W*\d*\s*[|!]\s*")


def _limpa(s):
    """Tira do título o que o OCR grudou: cabeçalho corrente («— 65», « 588»), «1 |» inicial, e o que
    sobra sem nenhuma palavra de 3 letras (« y», « |»)."""
    s = _PAGINA_NO_TITULO.sub("", s or "")
    s = _PAGINA_SOLTA.sub("", _LIXO_INICIAL.sub("", s))
    s = _ESPACOS.sub(" ", s).strip()
    return s if re.search(r"[A-Za-zÀ-ÿ]{3,}", s) else ""


def _rotulo(s):
    """«Artigo 11.» / «Artigo |.» / «Artigo IL.» -> «Artigo II.» / «Artigo I.» (numeral romano mal lido)."""
    s = _limpa(s)
    m = _NUMERAL.match(s)
    if not m or not m.group("ini").strip():
        return s
    num = re.sub(r"[|l1]", "I", m.group("num")).replace("L", "I") if not _ROMANO.match(m.group("num")) else m.group("num")
    return m.group("ini") + num + m.group("fim") if _ROMANO.match(num) else s


def _chave(s):
    return re.sub(r"\W+", "", s.upper())


def entradas(nos, impressas):
    """[(nivel, texto, página impressa)] dos nós titulados de UM volume, na ordem do texto.

    Descarta o nó que só repete o anterior do mesmo nível — o título corrente que o OCR tomou por
    divisão («CAPITULO SEGUNDO» de novo, com ou sem o título) — para o índice não listar fantasmas."""
    saida, anterior = [], {}
    for n in sorted(nos, key=lambda x: x.ordem_ini):
        if n.nivel not in NIVEIS_INDICE:
            continue
        rot, tit = _rotulo(n.rotulo), _limpa(n.titulo)
        if not (rot or tit):
            continue
        ant = anterior.get(n.nivel)
        if ant and _chave(rot) == _chave(ant[0]) and (not tit or _chave(tit) == _chave(ant[1])):
            continue
        anterior[n.nivel] = (rot, tit)
        for outro in NIVEIS_INDICE[NIVEIS_INDICE.index(n.nivel) + 1:]:
            anterior.pop(outro, None)                    # «Artigo I.» volta a valer num capítulo novo
        pag = impressas.get((n.volume_id, n.pagina_ini), "") if n.pagina_ini is not None else ""
        saida.append((n.nivel, " — ".join(x for x in (rot, tit) if x), pag))
    return saida


def xml_da_entrada(nivel, texto, pagina):
    p = etree.Element("p")
    p.set("type", TIPO_ENTRADA[nivel])
    p.text = texto
    if pagina:
        etree.SubElement(p, "label").text = str(pagina)
    return etree.tostring(p, encoding="unicode")


def gerar(edicao, volume_numero, impressas=None):
    """XML das entradas do índice do volume, na ordem."""
    impressas = leitura.impressas() if impressas is None else impressas
    nos = [n for n in No.objects.filter(edicao=edicao, volume__numero=volume_numero)]
    return [xml_da_entrada(*e) for e in entradas(nos, impressas)]


def regiao(edicao, volume_numero):
    """Blocos do anexo `vN.indice` da edição (marco, `<head>` e o resto), ou [] se o nó não existe."""
    no = No.objects.filter(edicao=edicao, nivel="anexo", xml_id=f"v{volume_numero}.indice").first()
    if no is None:
        return []
    return list(Bloco.objects.filter(edicao=edicao, ordem__gte=no.ordem_ini, ordem__lt=no.ordem_fim)
                .exclude(procedencia=Bloco.SUPRIMIDO).order_by("ordem"))


def componente(blocos, xmls):
    """Lista `novos` para `servicos.salvar_blocos` (escopo = `blocos`): mantém marco e `<head>` e põe as
    entradas, reaproveitando os ids dos blocos antigos na ordem (o histórico acompanha)."""
    novos = [{"id": b.pk, "xml": b.xml} for b in blocos[:2]]
    antigos = [b.pk for b in blocos[2:]]
    for i, xml in enumerate(xmls):
        novos.append({"id": antigos[i] if i < len(antigos) else None, "xml": xml})
    return novos


def atual(blocos):
    """XML das entradas já gravadas (depois do marco e do `<head>`)."""
    return [b.xml for b in blocos[2:]]
