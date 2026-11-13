#!/usr/bin/env python3
"""Revisão final de um TEI por LLM, uma chamada `claude -p` por página (sem ferramentas, 1 turno).

    python3 tools/revisa_paginas.py ENTRADA.xml --vol vol2 --saida DIR [--paralelo 3]
    python3 tools/revisa_paginas.py ENTRADA.xml --vol vol2 --saida DIR --so 421,422 --refaz
    python3 tools/revisa_paginas.py ENTRADA.xml --vol vol2 --saida DIR --seco      # só mostra os pedaços

ENTRADA.xml sai de `tools/trecho.py SELETOR -F tei` (ou é o volN.corrigido.xml inteiro).  Modelo padrão:
Haiku.  Ver docs/09-revisao-llm.md.

  * o XML é cortado nos <pb n> do CORPO (os de dentro de <note> marcam onde a nota continua); cada
    pedaço vai com as imagens das páginas que cobre.  Páginas ligadas por uma nota que continua ficam
    no mesmo pedaço (até --max-car): é aí que a fronteira corpo/nota costuma errar, e o conserto
    mexe nas duas páginas.  Páginas só de nota juntam-se ao pedaço anterior;
  * cada página vai em duas metades (superior/inferior, com sobreposição), cinza, ≤ 1568 px;
  * os alertas do estruturador (volN/volN.estruturado.alertas.tsv) dessas páginas vão como pistas;
  * o modelo devolve o fragmento em <xml>…</xml>.  Ele PODE corrigir a fronteira entre nota e corpo
    (fechar/abrir nota noutro ponto, passar texto entre os dois, criar nota que ficou no corpo, levar a
    nota ao ponto da chamada).  O validador recusa: XML mal formado no documento inteiro, <pb> do corpo
    mudados, elementos novos, xml:id repetido, texto total que cresce/encolhe demais (duplicado ou
    perdido) e passagem corpo↔nota acima de --troca-max.  Recusado, há nova chamada com o motivo;
  * cada pedaço é gravado em DIR/paginas/ ao terminar: rodar de novo retoma (--refaz para refazer).

Saída em DIR: revisado.xml, entrada.tex/revisado.tex (tei2latex --puro, para ler e para
revisao-modelos/), relatorio.md (notas do modelo e mudanças de fronteira por pedaço), resultado.json
(custo, chamadas, tokens, falhas, fronteira) e wer.txt (tools/mede_wer.py --xml antes/depois).
"""
import argparse
import base64
import collections
import concurrent.futures as cf
import csv
import difflib
import html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from lxml import etree
from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
PROMPT = RAIZ / "tools/prompts/revisao_pagina.md"
TEI = "{http://www.tei-c.org/ns/1.0}"
LADO_MAX = 1568          # a API reduz qualquer imagem cujo lado maior passe disto
SOBREPOE = 0.06          # fração da altura repetida nas duas metades
MINIMO = 300             # pedaço com menos texto que isto vai junto com o anterior
MAX_CAR = 16000          # teto (texto) de um pedaço que junta páginas ligadas por nota (9000 deixava a
                         # fronteira da p. 46 do vol. 1 entre dois pedaços, sem conserto possível)
TROCA_MAX = 2500         # passagem corpo→nota (caracteres) acima disto é recusada…
TROCA_PAG = 1800         # …ou acima disto vezes as páginas de corpo do pedaço: um rodapé inteiro que
                         # ficou no corpo tem até ~2800 car. por página (vol. 1 p. 22)
NOTA_CORPO_MAX = 800     # idem nota→corpo: ~8 linhas; o erro típico do modelo é esvaziar no corpo
                         # os parágrafos finais de uma nota longa (vol. 2 p. 441, 1567 car.)
NGRAMA = 10              # sequência de palavras usada para achar texto duplicado/copiado
DUP_MAX = 30             # n-gramas a mais que a entrada (~40 palavras): duplicação de verdade é um
                         # parágrafo; uma frase que o livro repete e o OCR perdeu (vol. 2 p. 425) não
COPIA_MAX = 12           # n-gramas vindos do pedaço seguinte ou de fora do trecho (~20 palavras)
RE_TAG = re.compile(r"<(/?)([A-Za-z][\w:.-]*)((?:\s+[^>]*?)?)\s*(/?)>|<!--.*?-->|<\?.*?\?>", re.S)
RE_N = re.compile(r'\bn="([^"]*)"')
RE_ID = re.compile(r'\bxml:id="([^"]*)"')
REND = {"it", "bold", "sc"}
ALERTAS = {"chamadas-x-notas", "nota-sem-chamada", "vao-nas-notas", "nota-recuperada", "continuacao-duvidosa",
           "corte-incerto", "corte-por-chamada", "numero-diverge"}


# ---------------------------------------------------------------- análise de um fragmento

def analisa(frag):
    """Percorre as tags de um fragmento (que pode começar/terminar no meio de elementos, mas começa
    fora de nota).  Devolve corpo/notas (caracteres de texto), os <pb> do corpo e de nota, nº de notas,
    os ids, os nomes de elementos e erros de forma."""
    r = {"corpo": 0, "notas": 0, "pb_corpo": [], "pb_nota": [], "notas_n": 0, "ids": [], "elems": set(),
         "rend": set(), "erros": [], "pos_pb": []}
    nota, i = 0, 0

    def texto(s):
        n = len(re.sub(r"\s+", " ", html.unescape(s)).strip()) if s.strip() else 0
        r["notas" if nota else "corpo"] += n

    for m in RE_TAG.finditer(frag):
        texto(frag[i:m.start()])
        i = m.end()
        if not m[2]:                     # comentário / instrução
            continue
        fecha, nome, attrs, vazio = m[1], m[2], m[3] or "", m[4]
        r["elems"].add(nome)
        if not fecha:
            r["ids"] += RE_ID.findall(attrs)
            r["rend"] |= set(re.findall(r'\brend="([^"]*)"', attrs))
        if nome == "pb":
            n = (RE_N.findall(attrs) or ["?"])[0]
            (r["pb_nota"] if nota else r["pb_corpo"]).append(n)
            if not nota:
                r["pos_pb"].append((m.start(), n))
        elif nome == "note":
            if fecha:
                nota -= 1
            elif not vazio:
                nota += 1
                r["notas_n"] += 1
                if 'place="foot"' not in attrs:
                    r["erros"].append("<note> sem place=\"foot\"")
            if nota < 0:
                r["erros"].append("</note> sem <note> aberto")
                nota = 0
    texto(frag[i:])
    if nota:
        r["erros"].append("<note> não fechado dentro do pedaço")
    return r


def palavras(frag, caixa=False):
    s = html.unescape(RE_TAG.sub(" ", frag))
    return re.findall(r"\w+", s if caixa else s.lower())


def ngramas(frag, k=NGRAMA):
    p = palavras(frag)
    return collections.Counter(tuple(p[i:i + k]) for i in range(len(p) - k + 1))


def chars_texto(frag):
    a = analisa(frag)
    return a["corpo"] + a["notas"]


# ---------------------------------------------------------------- pedaços

def corta(xml, max_car, junta=()):
    """(prefixo, [(pagina, texto, paginas_das_imagens)], sufixo).  Só os pedaços são revisados."""
    ini_body = xml.find("<body")
    fim_body = xml.rfind("</body>")
    if ini_body < 0 or fim_body < 0:
        sys.exit("a entrada não tem <body>…</body>")
    ini_body = xml.index(">", ini_body) + 1
    corpo = xml[ini_body:fim_body]
    pbs = analisa(corpo)["pos_pb"]
    if not pbs:
        sys.exit("o TEI não tem <pb n> no corpo")
    inicios, nums = [], []
    for pos, n in pbs:
        n = int(n)
        if not nums or n != nums[-1]:       # <pb> repetidos em seguida ficam no mesmo pedaço
            inicios.append(pos)
            nums.append(n)
    inicios.append(len(corpo))
    seg = lambda i: corpo[inicios[i]:inicios[i + 1]]
    # junta ao anterior: (a) página quase sem texto de corpo (só continuação de nota, que está no
    # pedaço anterior); (b) página para onde uma nota do pedaço anterior continua, até max_car
    i = 1
    while i < len(nums):
        anterior = corpo[inicios[i - 1]:inicios[i]]
        a = analisa(anterior)
        curto = chars_texto(seg(i)) < MINIMO
        liga = str(nums[i]) in a["pb_nota"] and chars_texto(anterior) + chars_texto(seg(i)) <= max_car
        forca = any(a < nums[i] <= b and nums[i - 1] >= a for a, b in junta)
        if curto or liga or forca:
            del inicios[i], nums[i]
        else:
            i += 1
    pedacos = []
    for i, n in enumerate(nums):
        texto = seg(i)
        prox = nums[i + 1] if i + 1 < len(nums) else n + 1
        pags = set(range(n, prox)) if prox > n else {n}
        pags |= {int(p) for p in analisa(texto)["pb_nota"] if p.isdigit()}
        pedacos.append((n, texto, sorted(pags)))
    return xml[:ini_body + inicios[0]], pedacos, xml[ini_body + inicios[-1]:]


# ---------------------------------------------------------------- validação

class Contexto:
    """O documento inteiro, para checar cada pedaço no lugar dele."""

    def __init__(self, prefixo, pedacos, sufixo):
        self.prefixo, self.sufixo = prefixo, sufixo
        self.textos = [t for _, t, _ in pedacos]
        self.idx = {n: k for k, (n, _, _) in enumerate(pedacos)}
        doc = prefixo + "".join(self.textos) + sufixo
        self.elems = analisa(doc)["elems"]
        self.ids = collections.Counter(RE_ID.findall(doc))
        self.fora, self.limites = {}, {}

    def com_volume(self, volume, pedacos):
        """A entrada é um trecho recortado de `volume` (texto do volN.corrigido.xml): o começo e o fim
        podem cair no meio de uma página, e o modelo vê a página inteira.  Guarda, por pedaço, os
        n-gramas das suas páginas que estão fora do trecho (para recusar cópia) e, no primeiro e no
        último, as palavras que ficam do lado de fora (para avisar o modelo)."""
        i0, i1 = volume.find("<body"), volume.rfind("</body>")
        corpo = volume[volume.index(">", i0) + 1:i1]
        if "<fw" not in "".join(self.textos):          # trecho.py tira os cabeçalhos correntes
            corpo = re.sub(r"<fw\b[^>]*>.*?</fw>", "", corpo, flags=re.S)
        pos = analisa(corpo)["pos_pb"] + [(len(corpo), None)]
        segs = {}
        for (p, n), (q, _) in zip(pos, pos[1:]):
            if n and n.isdigit():
                segs[int(n)] = segs.get(int(n), "") + corpo[p:q]
        trecho = set(ngramas("".join(self.textos)))
        for k, (n, texto, _) in enumerate(pedacos):
            pags = sorted({int(p) for p in analisa(texto)["pb_corpo"] if p.isdigit()})
            vol = "".join(segs.get(p, "") for p in pags)
            fora = set(ngramas(vol)) - trecho
            if fora:
                self.fora[n] = fora
            vw, cw = palavras(vol, caixa=True), palavras(texto, caixa=True)
            achar = lambda ws, alvo: next((i for i in range(len(ws) - len(alvo) + 1) if ws[i:i + len(alvo)] == alvo), -1)
            avisos = []
            if k == 0 and len(cw) >= 6 and (i := achar(vw, cw[:6])) > 0:
                avisos.append(f"O trecho começa em “{' '.join(cw[:8])}…”, no meio da página {pags[0]}: o texto acima "
                              f"disso na página (termina em “…{' '.join(vw[max(0, i - 12):i])}”), com as notas dele, é "
                              "de outro trecho e NÃO deve ser transcrito.")
            if k == len(pedacos) - 1 and len(cw) >= 6 and (i := achar(vw, cw[-6:])) >= 0 and i + 6 < len(vw):
                avisos.append(f"O trecho termina em “…{' '.join(cw[-8:])}”, no meio da página {pags[-1]}: o texto "
                              f"depois disso (começa em “{' '.join(vw[i + 6:i + 18])}…”), com as notas dele, é de "
                              "outro trecho e NÃO deve ser transcrito.")
            if avisos:
                self.limites[n] = " ".join(avisos)

    def ids_fora(self, n):
        """xml:id usados no documento fora do pedaço n."""
        return +(self.ids - collections.Counter(RE_ID.findall(self.textos[self.idx[n]])))

    def seguinte(self, n):
        k = self.idx[n]
        return self.textos[k + 1] if k + 1 < len(self.textos) else ""

    def documento(self, n, novo):
        k = self.idx[n]
        return self.prefixo + "".join(self.textos[:k]) + novo + "".join(self.textos[k + 1:]) + self.sufixo


def bem_formado(doc):
    try:
        etree.fromstring(doc.encode("utf-8"), etree.XMLParser(resolve_entities=False, huge_tree=True))
        return None
    except etree.XMLSyntaxError as e:
        return str(e)


def valida(n, texto, novo, pags, ctx, troca_max, nota_corpo_max=NOTA_CORPO_MAX):
    """(motivo da recusa ou None, mudança de fronteira ou None)."""
    a, b = analisa(texto), analisa(novo)
    if b["erros"]:
        return "; ".join(sorted(set(b["erros"]))), None
    if b["pb_corpo"] != a["pb_corpo"]:
        return f"os <pb> do corpo mudaram: {a['pb_corpo']} → {b['pb_corpo']}", None
    fora = [p for p in b["pb_nota"] if not p.isdigit() or int(p) not in pags]
    if fora or len(set(b["pb_nota"])) != len(b["pb_nota"]):
        return f"<pb> dentro de nota inválidos: {b['pb_nota']} (páginas do trecho: {pags})", None
    novos = b["elems"] - ctx.elems
    if novos:
        return f"elementos que o TEI não usa: {sorted(novos)}", None
    if b["rend"] - REND - a["rend"]:
        return f"rend desconhecido: {sorted(b['rend'] - REND - a['rend'])}", None
    rep = [x for x in b["ids"] if b["ids"].count(x) > 1 or x in ctx.ids_fora(n)]
    if rep:
        return f"xml:id repetido: {sorted(set(rep))}", None
    erro = bem_formado(ctx.documento(n, novo))
    if erro:
        return f"o XML ficou mal formado: {erro}", None
    # texto repetido: sequências de NGRAMA palavras que aparecem mais vezes que na entrada, ou que não
    # estavam no pedaço mas estão no seguinte (nota/corpo de uma página extra copiado)
    ga, gb, gs = ngramas(texto), ngramas(novo), ngramas(ctx.seguinte(n))
    dup = sum(1 for g, c in gb.items() if c > ga.get(g, 0) and ga.get(g, 0) > 0)
    copia = sum(1 for g in gb if g not in ga and g in gs)
    if dup > DUP_MAX:
        return f"texto duplicado dentro do trecho (~{dup + NGRAMA - 1} palavras repetidas)", None
    if copia > COPIA_MAX:
        return (f"copiou ~{copia + NGRAMA - 1} palavras que pertencem ao trecho seguinte (corpo ou nota que começa "
                "numa página extra)"), None
    fora = ctx.fora.get(n)
    if fora:
        alheio = sum(1 for g in gb if g not in ga and g in fora)
        if alheio > COPIA_MAX:
            return (f"copiou ~{alheio + NGRAMA - 1} palavras da página que ficam FORA do trecho (antes do começo "
                    "ou depois do fim dele)"), None
    # tamanho: uma linha impressa tem ~90 caracteres; o corpo pode ganhar ~1 linha por página (a 1ª,
    # que o OCR perde); um parágrafo duplicado de outra página tem 500+ caracteres
    paginas = max(1, len(set(a["pb_corpo"])))
    ta, tb = a["corpo"] + a["notas"], b["corpo"] + b["notas"]
    if abs(tb - ta) > max(0.04 * ta, 200) + 180 * paginas:
        pista = ""
        if tb < ta:
            pa, pn = palavras(texto, caixa=True), palavras(novo, caixa=True)
            sm = difflib.SequenceMatcher(None, pa, pn, autojunk=False)
            perdas = [(i2 - i1, i1) for op, i1, i2, _, _ in sm.get_opcodes() if op in ("delete", "replace") and i2 - i1 >= 15]
            if perdas:
                k, i1 = max(perdas)
                pista = (f" Foi omitido o trecho de ~{k} palavras que começa em “{' '.join(pa[i1:i1 + 10])}…”: se ele é a "
                         "continuação de uma nota que começou numa página anterior, envolva-o em "
                         "<note place=\"foot\" type=\"continuacao\">…</note> no lugar em que está, em vez de apagá-lo.")
        return f"o texto mudou demais: de {ta} para {tb} caracteres (texto duplicado ou perdido?){pista}", None
    dc, dn = b["corpo"] - a["corpo"], b["notas"] - a["notas"]
    fronteira = None
    troca = min(abs(dc), abs(dn)) if dc * dn < 0 else 0
    if troca > 60 or b["notas_n"] != a["notas_n"]:
        fronteira = {"corpo": [a["corpo"], b["corpo"]], "notas": [a["notas"], b["notas"]],
                     "num_notas": [a["notas_n"], b["notas_n"]], "troca": troca}
    if RE_CONT.search(novo):
        doc = ctx.documento(n, novo)
        if "</note>" not in doc[:doc.find(novo) + RE_CONT.search(novo).start()]:
            return "type=\"continuacao\" sem nenhuma nota antes dela no documento", fronteira
    if dn < 0 and troca > nota_corpo_max:
        return (f"tirou texto demais das notas para o corpo (~{troca} caracteres; notas {a['notas']} → {b['notas']}, "
                f"corpo {a['corpo']} → {b['corpo']}; máximo {nota_corpo_max}). Notas longas têm vários parágrafos em "
                "letra pequena no pé da página: eles são nota, mesmo que no corpo venha depois um novo parágrafo"), fronteira
    troca_max = max(troca_max, TROCA_PAG * paginas) if troca_max else 0
    if troca > troca_max:
        return (f"passou texto demais do corpo para as notas (~{troca} caracteres; corpo {a['corpo']} → {b['corpo']}, "
                f"notas {a['notas']} → {b['notas']}): o máximo é {troca_max}"), fronteira
    return None, fronteira


# ---------------------------------------------------------------- montagem

RE_CONT = re.compile(r'<note\b[^>]*\btype="continuacao"[^>]*>')
RE_NUM_NOTA = re.compile(r'(<note\b[^>]*>\s*(?:<p\b[^>]*>\s*)?(?:<hi\b[^>]*>)?)\(\s*\d{1,2}\s*\)\s*')


def liga_continuacoes(doc):
    """Junta cada <note type="continuacao"> (continuação, no alto do rodapé, de uma nota que começou
    noutro pedaço) à nota anterior do documento, com <pb n="P"/> dentro dela, se essa nota é da página
    P-1 (pelo xml:id nP-K ou pelo último <pb> de dentro dela).  Devolve (doc, avisos)."""
    avisos = []
    inicio = 0
    while m := RE_CONT.search(doc, inicio):
        fim = doc.index("</note>", m.end())
        cont = doc[m.end():fim]
        # página corrente do corpo e a última nota fechada antes da continuação
        pag, ult, ult_ant = None, None, None
        nivel, abre = 0, None
        for t in RE_TAG.finditer(doc, 0, m.start()):
            if t[2] == "pb" and not nivel:
                novo_pag = (RE_N.findall(t[3] or "") or [None])[0]
                if novo_pag != pag:          # nota da página anterior: a última fechada antes deste <pb>
                    pag, ult_ant = novo_pag, ult
            elif t[2] == "note" and not t[4]:
                if t[1]:
                    nivel -= 1
                    if not nivel:
                        ult = (abre, t.start())
                else:
                    if not nivel:
                        abre = t
                    nivel += 1
        alvo = None
        if ult_ant and pag and pag.isdigit():
            a, f = ult_ant
            ps = [int(x) for x in re.findall(r'<pb\b[^>]*\bn="(\d+)"', doc[a.end():f])]
            pid = re.search(r'xml:id="n(\d+)-', a[0])
            pn = max(ps) if ps else int(pid[1]) if pid else None
            if pn == int(pag) - 1:
                alvo = f
        if alvo is None:
            avisos.append(f"p. {pag}: continuação de nota sem nota da p. anterior para ligar; ficou como nota à parte")
            inicio = fim
            continue
        pb = f'<pb n="{pag}" facs="paginas/{int(pag):04d}.png"/>'
        antes = doc[:alvo]
        txt_ant = palavras_brutas(antes[-400:])
        txt_cont = palavras_brutas(cont)
        emenda = not re.search(r'[.!?»"]\s*$', txt_ant) or (txt_cont[:1].islower())
        c = cont.strip()
        if emenda and antes.rstrip().endswith("</p>"):
            k = antes.rstrip().rfind("</p>")
            if not txt_ant.endswith("-"):
                pb = " " + pb
            if c.startswith("<p"):
                c = c[c.index(">") + 1:]
                novo = antes[:k] + pb + c
            elif "<p" not in c:
                novo = antes[:k] + pb + c + "</p>"
            else:
                novo = antes + pb + c
        else:
            novo = antes + pb + (c if c.startswith("<p") or "<p" in c or not antes.rstrip().endswith("</p>")
                                 else f"<p>{c}</p>")
        resto = doc[alvo:m.start()] + doc[fim + len("</note>"):]
        avisos.append(f"p. {pag}: continuação de nota ligada à nota anterior ({len(txt_cont)} car.)")
        inicio = len(novo)
        doc = novo + resto
    doc, k = RE_NUM_NOTA.subn(r"\1", doc)
    if k:
        avisos.append(f"{k} nota(s) começavam com o número da chamada \"(n)\": tirado")
    return doc, avisos


def palavras_brutas(frag):
    return re.sub(r"\s+", " ", html.unescape(RE_TAG.sub("", frag))).strip()


# ---------------------------------------------------------------- imagens e alertas

_cache_img = {}


def metades(png):
    if png in _cache_img:
        return _cache_img[png]
    im = Image.open(png).convert("L")
    w, h = im.size
    meio, s = h // 2, int(h * SOBREPOE / 2)
    out = []
    for caixa in ((0, 0, w, meio + s), (0, meio - s, w, h)):
        c = im.crop(caixa)
        f = LADO_MAX / max(c.size)
        if f < 1:
            c = c.resize((round(c.width * f), round(c.height * f)), Image.LANCZOS)
        b = io.BytesIO()
        c.save(b, "PNG", optimize=True)
        out.append(base64.b64encode(b.getvalue()).decode())
    _cache_img[png] = out
    return out


def le_alertas(caminho):
    al = {}
    if caminho and Path(caminho).exists():
        with open(caminho, encoding="utf-8") as f:
            for l in csv.DictReader(f, delimiter="\t"):
                if l["tipo"] in ALERTAS and l["pagina"].lstrip("-").isdigit():
                    al.setdefault(int(l["pagina"]), []).append(f"{l['tipo']}: {l['mensagem']}")
    return al


def mensagem(n, texto, pags, args, ctx, aviso=""):
    conteudo = []
    for p in pags:
        png = args.imagens / f"{p:04d}.png"
        if not png.exists():
            continue
        for nome, dados in zip(("metade superior", "metade inferior"), metades(png)):
            conteudo.append({"type": "text", "text": f"Página {p} — {nome}:"})
            conteudo.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": dados}})
    corpo_pags = sorted({int(p) for p in analisa(texto)["pb_corpo"]})
    extra = ""
    alem = [p for p in pags if p > corpo_pags[-1]]
    if len(corpo_pags) > 1:
        extra += f" O trecho cobre o corpo das páginas {', '.join(map(str, corpo_pags))}."
    if alem:
        extra += (f" As páginas {', '.join(map(str, alem))} vêm só porque uma nota do trecho continua nelas. Delas "
                  "use apenas a continuação dessa nota: o corpo e as notas que COMEÇAM nessas páginas são do "
                  "trecho seguinte e não devem ser copiados.")
    if n in ctx.limites:
        extra += " " + ctx.limites[n]
    alertas = [f"  p. {p}: {m}" for p in pags for m in args.alertas.get(p, [])]
    if alertas:
        extra += ("\n\nAlertas do pipeline para estas páginas (pistas de onde a fronteira corpo/nota pode estar "
                  "errada; confira na imagem, podem ser falsos):\n" + "\n".join(alertas))
    conteudo.append({"type": "text", "text":
                     f"{args.descricao}. Trecho que começa na página {n}.{extra}\n\nRevise este fragmento TEI contra "
                     f"as imagens e devolva-o corrigido no formato pedido.{chr(10) * 2 + aviso if aviso else ''}"
                     f"\n\n<entrada>\n{texto}\n</entrada>"})
    return {"type": "user", "message": {"role": "user", "content": conteudo}}


# ---------------------------------------------------------------- chamada

def chama(msg, modelo, sistema, effort, cwd):
    cmd = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--model", modelo, "--tools", "", "--system-prompt", sistema,
           "--no-session-persistence", "--strict-mcp-config"]
    if effort:
        cmd += ["--effort", effort]
    # cada mensagem é única: gravar o prompt em cache (cobrado acima da entrada normal) não se paga
    env = dict(os.environ, DISABLE_PROMPT_CACHING="1")
    r = subprocess.run(cmd, input=json.dumps(msg) + "\n", capture_output=True, text=True, cwd=cwd, timeout=900,
                       env=env)
    res = None
    for linha in r.stdout.splitlines():
        try:
            d = json.loads(linha)
        except ValueError:
            continue
        if d.get("type") == "result":
            res = d
    if res is None:
        res = {"is_error": True, "result": (r.stderr or r.stdout)[-2000:]}
    return res


def desembrulha(novo):
    novo = re.sub(r"^\s*<entrada>\n?", "", novo)
    return re.sub(r"\n?</entrada>\s*$", "", novo)


def extrai(resp, texto):
    m = re.search(r"<xml>\n?(.*?)\n?</xml>", resp, re.S) or re.search(r"<xml>\n?(.*?)\n?<notas>", resp, re.S)
    if not m:
        return None
    novo = m[1]
    # o Haiku às vezes devolve o fragmento ainda embrulhado no <entrada>…</entrada> da mensagem
    # (8 de 19 pedaços na rodada de 2026-11-12 sobre a Theodicea): tira o invólucro
    novo = desembrulha(novo)
    # preserva o espaço em volta do fragmento (as fronteiras entre pedaços)
    novo = texto[:len(texto) - len(texto.lstrip())] + novo.strip() + texto[len(texto.rstrip()):]
    return novo


RE_COMECO = re.compile(r"^\s*(?:<[^>]+>\s*)*")
RE_FIM = re.compile(r"(?:\s*<[^>]+>)*\s*$")


def repara(texto, novo):
    """O modelo às vezes larga as tags soltas do começo/fim do fragmento (o `</div>` que fecha a secção
    anterior, o `<p>` que segue no pedaço seguinte).  Repõe as do original nessas duas pontas."""
    novo = RE_COMECO.match(texto)[0] + novo[RE_COMECO.match(novo).end():]
    a, b = RE_FIM.search(texto), RE_FIM.search(novo)
    novo = novo[:b.start()] + a[0]
    # entre duas aberturas de <div> (únicas pelo xml:id), o mesmo número de </div> que no original:
    # ao apagar lixo antes de um título ("<p>EI</p></div>") o modelo leva junto o </div>
    ant_a = ant_b = 0
    for m in re.finditer(r'<div\b[^>]*xml:id="[^"]+"[^>]*>', texto):
        j = novo.find(m[0], ant_b)
        if j < 0:
            break
        falta = texto.count("</div>", ant_a, m.start()) - novo.count("</div>", ant_b, j)
        if falta > 0:
            novo = novo[:j] + "</div>" * falta + novo[j:]
            j += 6 * falta
        ant_a, ant_b = m.end(), j + len(m[0])
    return novo


def tira_continuacoes_novas(texto, novo):
    """Uma <note type="continuacao"> só embrulha texto que JÁ estava no pedaço.  Se o texto dela não estava
    (o modelo o transcreveu da imagem, mas ele já está na nota do pedaço anterior: vol. 1 p. 16), sai."""
    ga = ngramas(texto, 5)
    def troca(m):
        g = ngramas(m[0], 5)
        tot = sum(g.values())
        return m[0] if tot and sum(c for k, c in g.items() if k in ga) / tot >= 0.5 else ""
    return re.sub(r'<note\b[^>]*\btype="continuacao"[^>]*>.*?</note>', troca, novo, flags=re.S)


def confere(n, texto, novo, pags, ctx, args):
    """valida(); se o XML vier mal formado, tenta repara() e valida de novo.  (falha, fronteira, novo, reparou)"""
    novo = tira_continuacoes_novas(texto, novo)
    falha, fronteira = valida(n, texto, novo, pags, ctx, args.troca_max, args.nota_corpo_max)
    if falha and ("mal formado" in falha or "não fechado" in falha or "sem <note> aberto" in falha):
        r = repara(texto, novo)
        if r != novo:
            f2, fr2 = valida(n, texto, r, pags, ctx, args.troca_max, args.nota_corpo_max)
            if f2 is None:
                return None, fr2, r, True
    return falha, fronteira, novo, False


def processa(ped, args, sistema, cwd, dirp, ctx):
    n, texto, pags = ped
    base = dirp / f"{n:04d}"
    js = base.with_suffix(".json")
    ent = base.with_suffix(".entrada.xml")
    mudou = ent.exists() and ent.read_text(encoding="utf-8") != texto    # pedaço remontado (outro --max-car)
    if js.exists() and not args.refaz and not mudou:
        reg = json.loads(js.read_text())
        rej = base.with_suffix(".rejeitado.xml")
        if args.revalida and reg["falha"] and rej.exists():   # critério novo sobre a resposta já paga
            novo = desembrulha(rej.read_text(encoding="utf-8"))
            reg["falha"], reg["fronteira"], novo, reparou = confere(n, texto, novo, pags, ctx, args)
            reg["reparo"] = reg.get("reparo") or reparou
            if reg["falha"] is None:
                base.with_suffix(".revisado.xml").write_text(novo, encoding="utf-8")
                rej.unlink()
            js.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  p. {n}: revalidado → {reg['falha'] or 'ok'}", file=sys.stderr)
        return reg
    base.with_suffix(".entrada.xml").write_text(texto, encoding="utf-8")
    for f in (".revisado.xml", ".rejeitado.xml"):
        base.with_suffix(f).unlink(missing_ok=True)
    reg = {"pagina": n, "paginas": pags, "falha": None, "fronteira": None, "notas": "", "tentativas": [],
           "total_cost_usd": 0.0, "duration_ms": 0, "num_turns": 0, "usage": {}}
    aviso = ""
    for tentativa in range(args.tentativas):
        t0 = time.time()
        res = chama(mensagem(n, texto, pags, args, ctx, aviso), args.modelo, sistema, args.effort, cwd)
        resp = res.get("result") or ""
        novo = extrai(resp, texto)
        notas = re.search(r"<notas>\s*(.*?)\s*</notas>", resp, re.S)
        fronteira, reparou = None, False
        if res.get("is_error"):
            falha = "erro do claude: " + resp[:300]
        elif novo is None:
            falha = "resposta sem <xml>…</xml>"
        else:
            falha, fronteira, novo, reparou = confere(n, texto, novo, pags, ctx, args)
        reg["reparo"] = reparou
        reg["total_cost_usd"] += res.get("total_cost_usd", 0) or 0
        reg["duration_ms"] += res.get("duration_ms") or int((time.time() - t0) * 1000)
        reg["num_turns"] += res.get("num_turns", 0) or 0
        for k, v in (res.get("usage") or {}).items():
            if isinstance(v, int):
                reg["usage"][k] = reg["usage"].get(k, 0) + v
        reg["tentativas"].append({"falha": falha, "fronteira": fronteira, "notas": notas[1] if notas else "",
                                  "resposta": resp if (falha or not notas) else ""})
        reg["falha"], reg["fronteira"], reg["notas"] = falha, fronteira, notas[1] if notas else ""
        if falha is None:
            base.with_suffix(".revisado.xml").write_text(novo, encoding="utf-8")
            base.with_suffix(".rejeitado.xml").unlink(missing_ok=True)
            break
        if novo is not None:
            base.with_suffix(".rejeitado.xml").write_text(novo, encoding="utf-8")
        if res.get("is_error") and "limit" in resp.lower():
            break                                 # limite de uso: não adianta repetir
        aviso = (f"ATENÇÃO: uma revisão anterior deste trecho foi recusada porque {falha}. Respeite as regras: "
                 "XML bem formado, as mesmas tags soltas no começo e no fim, os mesmos <pb> do corpo, nenhum texto "
                 "duplicado de outra página nem omitido; só passe texto entre corpo e nota quando a imagem mostrar "
                 "que o limite está errado.")
    js.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    u = reg["usage"]
    fr = reg["fronteira"]
    fr = f"  fronteira: troca {fr['troca']} car., notas {fr['num_notas']}" if fr and not reg["falha"] else ""
    print(f"  p. {n} ({len(pags)} pp.): {'FALHOU: ' + reg['falha'] if reg['falha'] else 'ok'}"
          f"{' (2ª tentativa)' if len(reg['tentativas']) > 1 and not reg['falha'] else ''}{fr}"
          f"  US$ {reg['total_cost_usd']:.3f}  {reg['duration_ms'] / 1000:.0f}s  "
          f"ent {u.get('input_tokens', 0) + u.get('cache_creation_input_tokens', 0) + u.get('cache_read_input_tokens', 0)}"
          f" saí {u.get('output_tokens', 0)}", file=sys.stderr, flush=True)
    return reg


# ---------------------------------------------------------------- principal

def para_tex(xml, tex):
    r = subprocess.run([sys.executable, "tools/tei2latex.py", str(xml), "--puro", "-o", str(tex)], cwd=RAIZ,
                       capture_output=True, text=True)
    if r.returncode:
        print(f"!! tei2latex falhou em {xml}: {r.stderr[-500:]}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", type=Path, help="TEI (tools/trecho.py SELETOR -F tei, ou volN.corrigido.xml)")
    ap.add_argument("--vol", required=True, choices=["vol1", "vol2"])
    ap.add_argument("--modelo", default="haiku")
    ap.add_argument("--saida", type=Path, required=True)
    ap.add_argument("--imagens", type=Path, help="padrão: VOL/paginas do checkout principal")
    ap.add_argument("--alertas", help="padrão: VOL/VOL.estruturado.alertas.tsv ('' para nenhum)")
    ap.add_argument("--so", help="só estes pedaços (páginas iniciais), p. ex. 421,422 ou 421-425")
    ap.add_argument("--paralelo", type=int, default=1)
    ap.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--max-car", type=int, default=MAX_CAR,
                    help=f"teto de texto de um pedaço que junta páginas ligadas por nota (padrão {MAX_CAR})")
    ap.add_argument("--troca-max", type=int, default=TROCA_MAX,
                    help=f"caracteres que podem passar do corpo para as notas num pedaço (padrão {TROCA_MAX}; 0 congela)")
    ap.add_argument("--nota-corpo-max", type=int, default=NOTA_CORPO_MAX,
                    help=f"idem, das notas para o corpo (padrão {NOTA_CORPO_MAX}; 0 congela)")
    ap.add_argument("--volume", help="TEI do volume de onde o trecho saiu, para avisar o modelo do que fica fora "
                    "dele (padrão: VOL/VOL.corrigido.xml; '' para nenhum)")
    ap.add_argument("--junta", help="força num pedaço só as páginas A-B (p. ex. 104-109; vírgulas para várias "
                    "faixas): fica gravado em SAIDA/junta.txt e vale nas rodadas seguintes")
    ap.add_argument("--refaz", action="store_true", help="refaz pedaços já gravados")
    ap.add_argument("--tentativas", type=int, default=2, help="chamadas por pedaço se a revisão for recusada")
    ap.add_argument("--revalida", action="store_true",
                    help="reaplica o validador às respostas recusadas já gravadas (sem chamar o modelo)")
    ap.add_argument("--seco", action="store_true", help="só lista os pedaços, sem chamar o modelo")
    ap.add_argument("--descricao", default="Elementos de Philosophia")
    args = ap.parse_args()

    comum = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=RAIZ,
                           capture_output=True, text=True).stdout.strip()
    principal = Path(comum).parent if comum else RAIZ
    if args.imagens is None:   # PNGs são git-ignorados: num worktree, os do checkout principal
        cands = [RAIZ / args.vol / "paginas", principal / args.vol / "paginas"]
        args.imagens = next((c for c in cands if any(c.glob("0*.png"))), cands[0])
    if args.alertas is None:
        args.alertas = RAIZ / args.vol / f"{args.vol}.estruturado.alertas.tsv"
    args.alertas = le_alertas(args.alertas)
    args.descricao = f"{args.descricao}, {args.vol}"

    xml = args.entrada.read_text(encoding="utf-8")
    erro = bem_formado(xml)
    if erro:
        sys.exit(f"a entrada não é XML bem formado: {erro}")
    arq_junta = args.saida / "junta.txt"
    faixas = set(arq_junta.read_text().split()) if arq_junta.exists() else set()
    if args.junta:
        faixas |= set(args.junta.split(","))
        if not args.seco:
            args.saida.mkdir(parents=True, exist_ok=True)
            arq_junta.write_text("\n".join(sorted(faixas, key=lambda f: int(f.split("-")[0]))) + "\n")
    junta = [tuple(int(x) for x in f.split("-")) for f in faixas]
    prefixo, pedacos, sufixo = corta(xml, args.max_car, junta)
    assert prefixo + "".join(t for _, t, _ in pedacos) + sufixo == xml
    ctx = Contexto(prefixo, pedacos, sufixo)
    if args.volume is None:
        args.volume = next((c for c in (RAIZ / args.vol / f"{args.vol}.corrigido.xml",
                                        principal / args.vol / f"{args.vol}.corrigido.xml") if c.exists()), "")
    if args.volume and Path(args.volume).resolve() != args.entrada.resolve():
        ctx.com_volume(Path(args.volume).read_text(encoding="utf-8"), pedacos)
    escolha = pedacos
    if args.so:
        quero = set()
        for parte in args.so.split(","):
            a, _, b = parte.partition("-")
            quero |= set(range(int(a), int(b or a) + 1))
        escolha = [p for p in pedacos if p[0] in quero]
    if args.seco:
        for n, t, pags in escolha:
            a = analisa(t)
            print(f"{n}: {len(t)} car. ({a['corpo']} corpo, {a['notas']} notas, {a['notas_n']} nota(s)), "
                  f"imagens {pags}{'  alertas: ' + str(sum(len(args.alertas.get(p, [])) for p in pags)) if any(p in args.alertas for p in pags) else ''}"
                  f"{'  fora do trecho: ' + str(len(ctx.fora[n])) + ' n-gramas' if n in ctx.fora else ''}")
            if n in ctx.limites:
                print("   " + ctx.limites[n])
        return

    args.saida.mkdir(parents=True, exist_ok=True)
    dirp = args.saida / "paginas"
    dirp.mkdir(exist_ok=True)
    (args.saida / "entrada.xml").write_text(xml, encoding="utf-8")
    sistema = PROMPT.read_text(encoding="utf-8")
    print(f">> {args.modelo}: {len(escolha)} pedaço(s) de {args.entrada} (imagens em {args.imagens})", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="revisa_paginas.") as cwd:   # fora do repo: sem CLAUDE.md do projeto
        with cf.ThreadPoolExecutor(args.paralelo) as ex:
            list(ex.map(lambda p: processa(p, args, sistema, cwd, dirp, ctx), escolha))

    # junta: revisado onde houver, original no resto
    partes, todos = [], []
    for n, t, _ in pedacos:
        r = dirp / f"{n:04d}.revisado.xml"
        e = dirp / f"{n:04d}.entrada.xml"
        vale = e.exists() and e.read_text(encoding="utf-8") == t
        partes.append(r.read_text(encoding="utf-8") if vale and r.exists() else t)
        j = dirp / f"{n:04d}.json"
        if vale and j.exists():
            todos.append(json.loads(j.read_text()))
    final, avisos_mont = liga_continuacoes(prefixo + "".join(partes) + sufixo)
    for x in avisos_mont:
        print(f"   montagem: {x}", file=sys.stderr)
    erro = bem_formado(final)
    if erro:   # cada pedaço foi checado sozinho no documento; juntos não deveria falhar
        print(f"!! revisado.xml mal formado ao juntar os pedaços: {erro}", file=sys.stderr)
    (args.saida / "revisado.xml").write_text(final, encoding="utf-8")
    for f in ("entrada", "revisado"):
        para_tex(args.saida / f"{f}.xml", args.saida / f"{f}.tex")

    soma = lambda k: sum((r["usage"].get(k) or 0) for r in todos)
    resumo = {"modelo": args.modelo, "formato": "tei", "pedacos": len(pedacos), "feitos": len(todos),
              "falhas": {r["pagina"]: r["falha"] for r in todos if r["falha"]},
              "fronteira": {r["pagina"]: r["fronteira"] for r in todos if r.get("fronteira") and not r["falha"]},
              "total_cost_usd": round(sum(r["total_cost_usd"] for r in todos), 4),
              "num_turns": sum(r["num_turns"] or 0 for r in todos),
              "duration_ms": sum(r["duration_ms"] for r in todos),
              "usage": {k: soma(k) for k in ("input_tokens", "cache_creation_input_tokens",
                                             "cache_read_input_tokens", "output_tokens")},
              "is_error": len(todos) < len(pedacos) or bool(erro)}
    (args.saida / "resultado.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")

    def linha(r):
        fr = r.get("fronteira")
        s = f"- p. {r['pagina']}"
        if r["falha"]:
            s += f" **FALHOU: {r['falha']}**"
        elif fr:
            s += (f" **fronteira**: corpo {fr['corpo'][0]}→{fr['corpo'][1]}, notas {fr['notas'][0]}→{fr['notas'][1]} "
                  f"car., {fr['num_notas'][0]}→{fr['num_notas'][1]} nota(s)")
        return s + f": {r['notas']}"
    (args.saida / "relatorio.md").write_text(
        "\n".join(linha(r) for r in sorted(todos, key=lambda r: r["pagina"])) + "\n"
        + ("\n## Montagem\n\n" + "\n".join(f"- {x}" for x in avisos_mont) + "\n" if avisos_mont else ""),
        encoding="utf-8")

    p0, p1 = pedacos[0][0], max(max(p[2]) for p in pedacos)
    wer = []
    for f in ("entrada", "revisado"):
        r = subprocess.run([sys.executable, "tools/mede_wer.py", "--vol", args.vol, "--xml",
                            str((args.saida / f"{f}.xml").resolve()), "-f", str(p0), "-l", str(p1)],
                           cwd=RAIZ, capture_output=True, text=True)
        wer.append(f"== {f}\n{r.stdout}{r.stderr}")
    (args.saida / "wer.txt").write_text("".join(wer), encoding="utf-8")
    print(f">> {resumo['feitos']}/{resumo['pedacos']} pedaços, {len(resumo['falhas'])} falha(s), "
          f"{len(resumo['fronteira'])} com fronteira mudada, US$ {resumo['total_cost_usd']:.2f}, "
          f"{resumo['duration_ms'] / 6e4:.1f} min de chamadas; tokens {resumo['usage']}", file=sys.stderr)
    print(f">> {args.saida}/revisado.xml  (revisado.tex, wer.txt, relatorio.md, resultado.json)", file=sys.stderr)


if __name__ == "__main__":
    main()
