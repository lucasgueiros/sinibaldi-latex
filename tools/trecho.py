#!/usr/bin/env python3
"""Trabalha com qualquer trecho da obra por um SELETOR, sem saber paginas nem caminhos.

    python3 tools/trecho.py --lista vol2                       # arvore de divisoes (id, rotulo, paginas)
    python3 tools/trecho.py --lista vol2 --teses
    python3 tools/trecho.py vol2:existencia-de-deus            # texto do capitulo (stdout)
    python3 tools/trecho.py vol2:t6..t12 -F tex -F pdf         # teses 6 a 12 -> build/trechos/*.tex/.pdf
    python3 tools/trecho.py vol2:421-442 -F tei -o x.xml       # faixa de paginas impressas
    python3 tools/trecho.py vol2:/alma humana/ -F scan         # busca por titulo; so um no pode casar
    python3 tools/trecho.py --onde 'ente necessario' vol1      # em que no e pagina esta o texto

Seletor:  [volN:]  id-do-no | trecho-do-id | /titulo/ | ESCOPO/tN..tM | PP-QQ | pPP
          (a numeracao das teses recomeca em cada parte: use o escopo, p. ex. vol2:theodicea/t5..t8)
          (volN: e opcional quando so um volume casa; faixa de paginas exige o volume)
Formatos (-F, repetivel; padrao txt): txt | tei | tex | pdf | scan | slides
Fonte: volN/estrutura.tsv (revisado) ou, se nao existe, volN/estrutura.proposta.tsv (tools/titulos.py);
conteudo: volN/volN.corrigido.xml.  O recorte e POR TITULO: comeca no bloco do titulo do no (casado
pela ancora do TSV) e termina antes do titulo seguinte, mesmo no meio de uma pagina.  So a faixa
PP-QQ e o formato scan (imagens) cortam por pagina.

Legado: --marcador FONTE.tex ID extrai o trecho %%>>> ID / %%<<< ID de um .tex (livro e slides manuais).
"""
import argparse
import copy
import difflib
import re
import subprocess
import sys
from pathlib import Path

from lxml import etree

RAIZ = Path(__file__).resolve().parent.parent
TEI = "{http://www.tei-c.org/ns/1.0}"
RANK = {"parte": 1, "seccao": 2, "capitulo": 3, "artigo": 4, "tese": 5}
VOLS = ("vol1", "vol2")


def norm(s):
    s = re.sub(r"[ÁÀÂÃ]", "A", s.upper())
    s = re.sub(r"[ÉÈÊ]", "E", s)
    s = re.sub(r"[ÍÌÎ]", "I", s)
    s = re.sub(r"[ÓÒÔÕ]", "O", s)
    s = re.sub(r"[ÚÙÛ]", "U", s).replace("Ç", "C")
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


# ------------------------------------------------------------------ estrutura
class No:
    def __init__(self, vol, pag, ancora, nivel, rotulo, titulo, ident, fonte):
        self.vol, self.pag, self.ancora, self.nivel = vol, int(pag), ancora, nivel
        self.rotulo, self.titulo, self.id, self.fonte = rotulo, titulo, ident, fonte
        self.fim = self.pag
        self.prox = None           # primeiro titulo DEPOIS deste no (fronteira do recorte)
        self.numero = int(rotulo) if nivel == "tese" and rotulo.isdigit() else None

    def __str__(self):
        return f"{self.vol}:{self.id}"


def ultima_pagina(vol):
    ids = []
    with open(RAIZ / vol / "paginas" / "manifesto.tsv", encoding="utf-8") as f:
        next(f)
        ids = [int(l.split("\t")[1]) for l in f if l.strip()]
    return max(ids)


def le_estrutura(vol):
    """lista de No em ordem do livro, com `fim` derivado (ultima pagina do no, inclusive)."""
    arq = RAIZ / vol / "estrutura.tsv"
    if not arq.exists() or not any(len(l.split("\t")) >= 7 for l in arq.read_text(encoding="utf-8").splitlines()
                                   if l.strip() and not l.startswith("#")):
        arq = RAIZ / vol / "estrutura.proposta.tsv"
    if not arq.exists():
        sys.exit(f"{vol}: sem estrutura.tsv nem estrutura.proposta.tsv (rode tools/titulos.py {vol})")
    nos = []
    for l in arq.read_text(encoding="utf-8").splitlines():
        c = l.rstrip("\n").split("\t")
        if l.startswith("#") or len(c) < 7:
            continue
        nos.append(No(vol, *c[:7]))
    ult = ultima_pagina(vol)
    for i, n in enumerate(nos):
        seg = next((m for m in nos[i + 1:] if RANK[m.nivel] <= RANK[n.nivel]), None)
        n.fim = max(n.pag, seg.pag if seg else ult)
        n.prox = seg
    return nos


# ------------------------------------------------------------------ seletor
def resolve(sel, estruturas):
    """(vol, pag_ini, pag_fim, nome) para o seletor."""
    vol = None
    m = re.match(r"^(vol\d+):(.*)$", sel)
    if m:
        vol, sel = m.group(1), m.group(2)
    cand = [vol] if vol else [v for v in VOLS if (RAIZ / v).is_dir()]

    m = re.fullmatch(r"p?(\d+)(?:\s*[-–]\s*(\d+))?", sel)
    if m:
        if len(cand) != 1:
            sys.exit(f"faixa de páginas exige o volume: vol1:{sel} ou vol2:{sel}")
        a = int(m.group(1))
        b = int(m.group(2) or a)
        return cand[0], a, b, f"{cand[0]}-p{a}" + (f"-{b}" if b != a else ""), None, None

    escopo = None
    if "/" in sel and not sel.startswith("/") and re.search(r"/t\d+(\.\.t?\d+)?$", sel):
        esc, sel = sel.rsplit("/", 1)
        pv, pi, pf, *_ = resolve((vol + ":" if vol else "") + esc, estruturas)
        cand, escopo = [pv], (pi, pf)
    m = re.fullmatch(r"t(\d+)(?:\.\.t?(\d+))?", sel)
    if m:
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        pares = []              # a numeracao das teses recomeca em cada PARTE: pode haver varios t6..t8
        for v in cand:
            nos = [n for n in estruturas(v) if not escopo or escopo[0] <= n.pag <= escopo[1]]
            for k, ini in enumerate(nos):
                if ini.numero == a:
                    fim = next((n for n in nos[k:] if n.numero == b), None)
                    if fim:
                        pares.append((v, ini, fim))
        if len(pares) != 1:
            if not pares:
                sys.exit(f"tese {a}..{b}: não encontrada")
            print(f"tese {a}..{b}: {len(pares)} ocorrências (a numeração recomeça em cada parte); "
                  f"use ESCOPO/t{a}..t{b}, p. ex. vol2:<id-da-parte>/t{a}:", file=sys.stderr)
            for v, i, f in pares:
                dono = [n for n in estruturas(v) if n.nivel == "parte" and n.pag <= i.pag]
                print(f"  {v} p. {i.pag}  parte {dono[-1].id if dono else '?'}", file=sys.stderr)
            sys.exit(2)
        v, i, f = pares[0]
        lst = estruturas(v)
        k = lst.index(f)
        prox = lst[k + 1] if k + 1 < len(lst) else None
        return v, i.pag, f.fim, f"{v}-t{a}" + (f"-t{b}" if b != a else ""), i, prox

    alvo = norm(sel.strip("/"))
    casos = []
    for v in cand:
        for n in estruturas(v):
            if n.nivel == "tese":
                continue
            alvos = [n.id, n.titulo, n.rotulo]
            if sel.startswith("/"):
                ok = any(alvo and alvo in norm(x) for x in alvos)
            else:
                ok = n.id == sel or n.id.endswith("." + sel) or n.id.startswith(sel) \
                    or (alvo and alvo == norm(n.titulo))
            if ok:
                casos.append(n)
    exatos = [n for n in casos if n.id == sel]
    if exatos:
        casos = exatos
    if len(casos) != 1:
        if not casos:
            sys.exit(f"seletor “{sel}”: nada casa (veja --lista)")
        print(f"seletor “{sel}”: {len(casos)} nós casam; seja mais específico:", file=sys.stderr)
        for n in casos[:15]:
            print(f"  {n}  — {n.rotulo} {n.titulo}  (pp. {n.pag}–{n.fim})", file=sys.stderr)
        sys.exit(2)
    n = casos[0]
    return n.vol, n.pag, n.fim, f"{n.vol}-{n.id}", n, n.prox


# ------------------------------------------------------------------ conteudo (TEI)
def carrega(vol):
    arq = RAIZ / vol / f"{vol}.corrigido.xml"
    if not arq.exists():
        sys.exit(f"{arq}: não existe (rode tools/gera_volume.sh {vol})")
    return etree.parse(str(arq), etree.XMLParser(huge_tree=True))


def tira(e):
    """remove `e` da arvore SEM perder o seu tail (o texto que vem depois dele): o lxml apaga o tail
    junto.  Depois de <fw> e <pb> esta a 1a linha da pagina, que assim sumia do recorte."""
    pai = e.getparent()
    if pai is None:
        return
    if e.tail:
        ant = e.getprevious()
        if ant is not None:
            ant.tail = (ant.tail or "") + e.tail
        else:
            pai.text = (pai.text or "") + e.tail
    pai.remove(e)


def marca_blocos(raiz, p0, p1, remove=False):
    """percorre o corpo em ordem, rastreando a pagina por <pb>; devolve os blocos (el, pag_ini, pag_fim)
    que tocam [p0, p1].  Com remove=True, apaga do arvore o que nao toca (e as <div> que ficarem vazias)."""
    pag = [0]
    blocos = []
    BLOCO = {"p", "head", "argument", "label", "quote", "cit", "list", "table", "ab"}

    def pbs(el):
        for e in el.iter(TEI + "pb"):
            yield e

    def anda(el):
        for c in list(el):
            if not isinstance(c.tag, str):
                continue
            ln = c.tag.replace(TEI, "")
            if ln == "pb":
                pag[0] = int(c.get("n"))
            elif ln == "fw":
                continue
            elif ln == "div":
                anda(c)
                if remove and not any(isinstance(x.tag, str) and x.tag.replace(TEI, "") in BLOCO | {"div"} for x in c):
                    c.getparent().remove(c)
            else:
                ini = pag[0]
                for e in c.iter(TEI + "pb"):
                    if e.getparent() is not None and not any(a.tag == TEI + "note" for a in e.iterancestors()):
                        pag[0] = int(e.get("n"))
                fim = pag[0]
                if ini <= p1 and fim >= p0:
                    blocos.append((c, ini, fim))
                elif remove:
                    c.getparent().remove(c)

    corpo = raiz.find(f".//{TEI}body")
    anda(corpo)
    if remove:                      # <pb> fora da faixa
        for e in list(corpo.iter(TEI + "pb")):
            if not (p0 <= int(e.get("n")) <= p1) and e.getparent() is not None:
                tira(e)
    return blocos


def inline(el, notas, pg):
    """texto do elemento com [N] nas viradas de pagina e (k) nas notas; italico entre *...*."""
    s = el.text or ""
    for c in el:
        if not isinstance(c.tag, str):
            s += c.tail or ""
            continue
        ln = c.tag.replace(TEI, "")
        if ln == "pb":
            if pg:
                s += f" [{c.get('n')}] "
        elif ln == "note":
            notas.append(c)
            s += f"({len(notas)})"
        elif ln == "fw":
            pass
        elif ln == "hi" and c.get("rend") == "it":
            s += "*" + inline(c, notas, pg) + "*"
        else:
            s += inline(c, notas, pg)
        s += c.tail or ""
    return s


def texto_bloco(el):
    return re.sub(r"\s+", " ", inline(el, [], False)).strip()


def acha(todos, no, desde, janela=1):
    """indice do bloco que e o TITULO `no`, entre os blocos das paginas pag-janela .. pag+janela, a
    partir de `desde`.  Tenta a ancora (inicio da linha do titulo no OCR) e, se o TEI nao tem aquela
    linha (rotulo perdido pela deteccao antiga), o texto do titulo."""
    chaves = [norm(no.ancora)]
    if no.titulo and no.titulo != "-":
        chaves.append(norm(no.titulo))
    melhor, ib = 0.0, None
    for alvo in filter(None, chaves):
        for k in range(desde, len(todos)):
            el, ini, fim = todos[k]
            if ini > no.pag + janela:
                break
            if fim < no.pag - janela:
                continue
            t = norm(texto_bloco(el))[:len(alvo) + 2]
            r = difflib.SequenceMatcher(None, alvo, t).ratio()
            if r >= 0.85:
                return k                      # o primeiro que casa bem, em ordem do livro
            if r > melhor:
                melhor, ib = r, k
    return ib if melhor >= 0.6 else None


def seleciona(raiz, p0, p1, ini, prox):
    """(todos, escolhidos): blocos do trecho.  Com `ini`, o recorte e POR TITULO: do bloco que e o
    titulo de `ini` ate antes do titulo `prox`.  Sem `ini` (faixa de paginas), por pagina."""
    todos = marca_blocos(raiz, -10 ** 6, 10 ** 6)   # preliminares tem <pb n> negativo
    if ini is None:
        return todos, [b for b in todos if b[1] <= p1 and b[2] >= p0]
    i0 = acha(todos, ini, 0)
    if i0 is None:
        sys.exit(f"título não localizado no TEI: p. {ini.pag} “{ini.ancora}” ({ini.id}); "
                 f"corrija a âncora no estrutura.tsv")
    i1 = acha(todos, prox, i0 + 1) if prox else len(todos)
    if i1 is None:
        print(f"aviso: o título seguinte (p. {prox.pag} “{prox.ancora}”) não foi localizado; "
              f"recorte vai até o fim da p. {p1}", file=sys.stderr)
        i1 = next((k for k in range(i0 + 1, len(todos)) if todos[k][1] > p1), len(todos))
    return todos, todos[i0:i1]


def formata_txt(arv, p0, p1, ini=None, prox=None):
    saida = []
    for el, _, _ in seleciona(arv.getroot(), p0, p1, ini, prox)[1]:
        notas = []
        t = re.sub(r"[ \t]+", " ", inline(el, notas, True)).strip()
        if not t:
            continue
        if el.tag.replace(TEI, "") == "head":
            t = "\n## " + t
        saida.append(t)
        for k, n in enumerate(notas, 1):
            nt = re.sub(r"\s+", " ", inline(n, [], False)).strip()
            saida.append(f"    ({k}) {nt}")
    return "\n\n".join(saida).replace("\n\n    (", "\n    (") + "\n"


def formata_tei(arv, p0, p1, nome, ini=None, prox=None):
    novo = copy.deepcopy(arv.getroot())
    todos, ficam = seleciona(novo, p0, p1, ini, prox)
    manter = {id(b[0]) for b in ficam}
    for el, _, _ in todos:
        if id(el) not in manter and el.getparent() is not None:
            el.getparent().remove(el)
    pa, pb_ = (ficam[0][1], ficam[-1][2]) if ficam else (p0, p1)
    for e in list(novo.iter(TEI + "fw")):
        tira(e)
    for e in list(novo.iter(TEI + "pb")):
        if not (pa <= int(e.get("n")) <= pb_) and e.getparent() is not None:
            tira(e)
    for d in reversed(list(novo.iter(TEI + "div"))):
        if d.getparent() is not None and not any(isinstance(x.tag, str) and x.tag != TEI + "pb" for x in d):
            pai, i = d.getparent(), d.getparent().index(d)
            for e in [x for x in d if x.tag == TEI + "pb"]:   # a quebra do inicio do trecho fica
                pai.insert(i, e)                               # na div anterior, que sai vazia
                i += 1
            pai.remove(d)
    t = novo.find(f".//{TEI}teiHeader//{TEI}title")
    if t is not None:
        t.text = f"{t.text or ''} — trecho {nome} (pp. {pa}–{pb_})"
    return etree.tostring(novo, encoding="UTF-8", xml_declaration=True, pretty_print=False)


# ------------------------------------------------------------------ saidas derivadas
def sh(cmd, **kw):
    r = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, **kw)
    if r.returncode:
        sys.exit(f"falhou: {' '.join(map(str, cmd))}\n{r.stderr[-1500:]}")
    return r


def faz_tex(vol, p0, p1, destino, grafia, nome="", ini=None, prox=None):
    """LaTeX do trecho: do TEI ja recortado por titulo (ou, em faixa de paginas, por -f/-l)."""
    if ini is None:
        sh([sys.executable, "tools/tei2latex.py", f"{vol}/{vol}.corrigido.xml", "--puro", "-f", str(p0),
            "-l", str(p1), "--grafia", grafia, "-o", str(destino)])
        return
    xml = Path(str(destino)[:-4] + ".xml")
    xml.write_bytes(formata_tei(carrega(vol), p0, p1, nome, ini, prox))
    sh([sys.executable, "tools/tei2latex.py", str(xml), "--puro", "--grafia", grafia, "-o", str(destino)])


def faz_pdf(destino_tex):
    stem = destino_tex.parent / destino_tex.name[:-4]      # o id tem pontos: nada de with_suffix
    rel = stem.relative_to(RAIZ).as_posix() if stem.is_absolute() else stem.as_posix()
    r = subprocess.run(["latexmk", "-lualatex", "-interaction=nonstopmode", "-halt-on-error",
                        f"-outdir={stem.parent}", f"-jobname={stem.name}",
                        f"-usepretex=\\def\\fragmento{{{rel}}}", "tex/_preview.tex"],
                       cwd=RAIZ, capture_output=True, text=True)
    if r.returncode:
        sys.exit("latexmk falhou:\n" + (r.stdout or r.stderr)[-1500:])
    return stem.parent / (stem.name + ".pdf")


def faz_scan(vol, p0, p1, destino):
    ids = {}
    with open(RAIZ / vol / "paginas" / "manifesto.tsv", encoding="utf-8") as f:
        next(f)
        for l in f:
            c = l.rstrip("\n").split("\t")
            if len(c) > 1:
                ids[int(c[1])] = c[0]
    pngs = [RAIZ / vol / "paginas" / f"{ids[p]}.png" for p in range(p0, p1 + 1) if p in ids]
    falta = [p for p in pngs if not p.exists()]
    if falta:
        sys.exit(f"faltam imagens ({len(falta)}), p. ex. {falta[0]}; elas são git-ignored: "
                 f"rode tools/extrai_paginas.py ou use gera_volume.sh --imagens")
    sh(["mutool", "convert", "-o", str(destino)] + [str(p) for p in pngs])


def faz_slides(tex, nome):
    marcado = tex.parent / (tex.name[:-4] + ".marcado.tex")
    marcado.write_text(f"%%>>> {nome}\n{tex.read_text(encoding='utf-8')}\n%%<<< {nome}\n", encoding="utf-8")
    saida = tex.parent / (tex.name[:-4] + ".slides.base.md")
    sh([sys.executable, "tools/gera_slides_base.py", str(marcado), "-o", str(saida)])
    marcado.unlink()
    return saida


# ------------------------------------------------------------------ lista e busca
def lista(vol, teses, filtro=None):
    for n in le_estrutura(vol):
        if n.nivel == "tese" and not teses:
            continue
        if filtro and not (filtro[0] <= n.pag <= filtro[1]):
            continue
        r = RANK[n.nivel]
        marca = "" if n.fonte == "revisado" else " ~"
        print(f"{'  ' * (r - 1)}{n.rotulo:<22s} {n.titulo[:60]:<60s} pp. {n.pag}–{n.fim}  {n.id}{marca}")


def onde(texto, vols):
    alvo = norm(texto)
    achou = 0
    for v in vols:
        nos = le_estrutura(v)
        arv = carrega(v)
        for el, ini, fim in marca_blocos(arv.getroot(), 0, 10 ** 6):
            t = re.sub(r"\s+", " ", "".join(x for x in el.itertext()))
            i = norm(t).find(alvo)
            if i < 0:
                continue
            dono = [n for n in nos if n.nivel != "tese" and n.pag <= ini]
            caminho = dono[-1].id if dono else "?"
            tese = [n for n in nos if n.nivel == "tese" and n.pag <= ini]
            tv = f" · t{tese[-1].numero}" if tese and tese[-1].numero else ""
            print(f"{v} p. {ini}{tv} · {caminho}\n    …{t[max(0, i - 40):i + len(texto) + 60]}…")
            achou += 1
            if achou >= 25:
                print("(25 primeiras ocorrências)")
                return
    if not achou:
        print("nenhuma ocorrência", file=sys.stderr)


# ------------------------------------------------------------------ legado %%>>>
def extrair_marcador(src, tid):
    texto = open(src, encoding="utf-8").read()
    tag = re.escape(tid)
    m = re.search(rf"^%%>>> *{tag} *$\n(.*?)^%%<<< *{tag} *$", texto, re.M | re.S)
    if not m:
        raise KeyError(f"trecho '{tid}' nao encontrado em {src}")
    return m.group(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seletor", nargs="?")
    ap.add_argument("outro", nargs="?", help="(--marcador: o id; --lista/--onde: o volume)")
    ap.add_argument("-F", "--formato", action="append", choices=["txt", "tei", "tex", "pdf", "scan", "slides"])
    ap.add_argument("-o", "--saida", help="arquivo de saída (com um só formato)")
    ap.add_argument("--grafia", choices=["original", "atual"], default="original")
    ap.add_argument("--lista", action="store_true", help="árvore de divisões do volume (seletor = vol1|vol2)")
    ap.add_argument("--teses", action="store_true", help="com --lista: inclui as teses")
    ap.add_argument("--onde", metavar="TEXTO", help="em que nó e página está o texto")
    ap.add_argument("--marcador", action="store_true", help="legado: SELETOR=arquivo.tex, OUTRO=id do %%>>>")
    a = ap.parse_args()

    if a.marcador:
        try:
            sys.stdout.write(extrair_marcador(a.seletor, a.outro))
        except KeyError as e:
            sys.exit(str(e))
        return
    cache = {}
    estruturas = lambda v: cache.setdefault(v, le_estrutura(v))
    if a.lista:
        for v in ([a.seletor] if a.seletor in VOLS else VOLS):
            print(f"== {v}  (~ = proposta ainda não revisada)")
            lista(v, a.teses)
        return
    if a.onde:
        onde(a.onde, [x for x in (a.seletor, a.outro) if x in VOLS] or list(VOLS))
        return
    if not a.seletor:
        ap.error("informe um seletor (ou --lista, --onde)")

    vol, p0, p1, nome, ini, prox = resolve(a.seletor, estruturas)
    formatos = a.formato or ["txt"]
    if a.saida and len(formatos) > 1:
        ap.error("-o só com um formato")
    pasta = RAIZ / "build" / "trechos"
    pasta.mkdir(parents=True, exist_ok=True)
    print(f"{vol} pp. {p0}–{p1}  ({nome})", file=sys.stderr)

    tex = None
    for fm in formatos:
        destino = Path(a.saida) if a.saida else pasta / f"{nome}.{ {'txt': 'txt', 'tei': 'xml', 'tex': 'tex', 'pdf': 'pdf', 'scan': 'scan.pdf', 'slides': 'md'}[fm] }"
        if fm == "txt":
            txt = formata_txt(carrega(vol), p0, p1, ini, prox)
            if a.saida or len(formatos) > 1:
                destino.write_text(txt, encoding="utf-8")
                print(destino)
            else:
                sys.stdout.write(txt)
        elif fm == "tei":
            dados = formata_tei(carrega(vol), p0, p1, nome, ini, prox)
            if a.saida or len(formatos) > 1:
                destino.write_bytes(dados)
                print(destino)
            else:
                sys.stdout.buffer.write(dados)
        elif fm in ("tex", "pdf", "slides"):
            tex = pasta / f"{nome}.tex"
            if not tex.exists() or fm != "pdf":
                faz_tex(vol, p0, p1, tex, a.grafia, nome, ini, prox)
            if fm == "tex":
                if a.saida:
                    Path(a.saida).write_text(tex.read_text(encoding="utf-8"), encoding="utf-8")
                print(a.saida or tex)
            elif fm == "pdf":
                pdf = faz_pdf(tex)
                if a.saida:
                    Path(a.saida).write_bytes(pdf.read_bytes())
                print(a.saida or pdf)
            else:
                print(faz_slides(tex, nome))
        elif fm == "scan":
            faz_scan(vol, p0, p1, destino)
            print(destino)


if __name__ == "__main__":
    main()
