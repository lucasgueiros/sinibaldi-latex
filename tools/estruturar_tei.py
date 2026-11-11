#!/usr/bin/env python3
"""Paginas (manifesto.tsv + <id>.tsv do tesseract) -> TEI ESTRUTURADO.

    python3 tools/estruturar_tei.py vol2/paginas -o vol2/vol2.estruturado.xml --ano 1916
    python3 tools/estruturar_tei.py vol2/paginas -o /tmp/t.xml -f 421 -l 442     # so um trecho

Substitui o TEI bruto de paginas2tei.py (fase F2 + F4 + F5 do plano).  Entrada: o .tsv de cada
pagina (linhas e palavras com caixas), nao o .txt: so o .tsv da a geometria.  Saida: o TEI que
tools/tei2latex.py converte:

  <div type="parte|seccao|capitulo|artigo|tese" xml:id n>, <head type="rotulo">, <head>,
  <argument> (Summario), <p>, <label>, <hi rend="bold"> (enunciado da tese), <fw type="header">,
  <pb n facs/> e <note place="foot" xml:id="n421-2"> NO PONTO DA CHAMADA, com <pb/> dentro
  quando a nota atravessa paginas.

Como separa o que o .txt misturava (ver .claude/plans/edicao-renovada/notas-de-rodape.md):
  1. cabecalho corrente = 1a linha da pagina se parecer cabecalho;
  2. fronteira corpo/notas: notas = corpo menor no pe da pagina, que comeca numa linha "(n)" ou,
     havendo area de notas na pagina anterior, numa linha NAO recuada apos um vao de filete
     (continuacao).  O livro usa corpo menor tambem fora das notas (escolios), entao a entrelinha
     nao basta: o tamanho da letra (largura por caractere em linhas justificadas, ~21,5 px no corpo
     e ~17,5 nas notas, limiar por k-means no volume) e que separa corpo de corpo menor.  Notas
     longas existem: no vol. 2 chegam a 18 paginas (nota 580-1), com 2 linhas de corpo por pagina;
  3. paragrafo novo = linha recuada (>= ~2,5% da largura alem da margem) ou vao grande;
  4. nota nova = linha com "(n)"; linha sem "(n)" no inicio da area de notas = continuacao da
     nota aberta da pagina anterior (a nota ganha um <pb/> interno);
  5. 1o paragrafo da pagina, sem recuo, quando o anterior nao acabou em pontuacao final =
     continuacao do paragrafo (o <pb/> fica dentro do <p>);
  6. cada nota e ligada a chamada "(n)" do corpo da mesma pagina (por ordem; o numero impresso
     so confirma).

Estrutura: titulos PARTE / SECÇÃO / CAPITULO / ARTIGO (OCR tolerante), Summario e teses
"N. Titulo. — texto" (numeracao conferida em sequencia).  Tudo o que a heuristica nao fecha vira
alerta em <saida>.alertas.tsv (pagina, tipo, mensagem) — e o que a revisao (F6) deve olhar.
O texto fica em grafia de 1916, sem correcao de OCR.
"""
import argparse
import csv
import os
import re
import statistics
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
CHAMADA = re.compile(r"\(\s*(\d{1,2}|[lI|])\s*\)")
NOTA = re.compile(r"^\(\s*(\d{1,2}|[lI|])\s*\)\s*")
FIM_FRASE = re.compile(r"[.!?:;»”]\s*$")
ORDINAIS = {"PRIMEIRO", "PRIMEIRA", "SEGUNDO", "SEGUNDA", "TERCEIRO", "TERCEIRA", "QUARTO",
            "QUARTA", "QUINTO", "QUINTA", "SEXTO", "SEXTA", "SETIMO", "SETIMA", "OITAVO",
            "OITAVA", "NONO", "NONA", "DECIMO", "DECIMA", "UNICO", "UNICA", "PRELIMINAR"}
ROMANO = re.compile(r"^[IVXLC1l|]{1,6}$")
NIVEL = {"parte": 1, "seccao": 2, "capitulo": 3, "artigo": 4}


def T(n):
    return f"{{{TEI}}}{n}"


# ------------------------------------------------------------------ leitura do .tsv
class Linha:
    __slots__ = ("x0", "y0", "x1", "y1", "texto", "h")

    def __init__(self, x0, y0, x1, y1, texto, h=None):
        self.x0, self.y0, self.x1, self.y1, self.texto, self.h = x0, y0, x1, y1, texto, h


def le_linhas(tsv):
    """linhas nao vazias de uma pagina, em ordem de leitura; (linhas, largura_da_pagina)."""
    linhas, largura = {}, 0
    with open(tsv, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            lv = int(r["level"])
            if lv == 1:
                largura = int(r["width"])
            k = (r["block_num"], r["par_num"], r["line_num"])
            if lv == 4:
                x, y, w, h = (int(r[c]) for c in ("left", "top", "width", "height"))
                linhas[k] = [x, y, x + w, y + h, [], []]
            elif lv == 5 and k in linhas:
                t = CTRL.sub("", r["text"]).strip()
                if t and float(r["conf"]) >= 0:
                    linhas[k][4].append(t)
                    if sum(c.isalpha() for c in t) >= 4:        # palavras longas: altura confiavel
                        linhas[k][5].append(int(r["height"]))
    out = [Linha(x0, y0, x1, y1, " ".join(ws)) for x0, y0, x1, y1, ws, hs in linhas.values() if ws]
    # tamanho da letra = largura por caractere, so em linhas "cheias" (justificadas): corpo ~21.5 px,
    # corpo menor/notas ~17.5 px a 300 ppi.  A altura da palavra foi descartada: oscila demais.
    if out:
        ws_ = sorted(l.x1 - l.x0 for l in out)
        coluna = ws_[int(len(ws_) * 0.9)]
        for l in out:
            if (l.x1 - l.x0) >= 0.93 * coluna and len(l.texto) > 25:
                l.h = (l.x1 - l.x0) / len(l.texto)
    out.sort(key=lambda l: (l.y0, l.x0))
    return out, largura


def calibra_entrelinhas(todas):
    """(corpo, nota): os dois picos do histograma de entrelinhas entre 30 e 70 px."""
    h = Counter()
    for linhas in todas:
        for a, b in zip(linhas, linhas[1:]):
            d = b.y0 - a.y0
            if 30 <= d <= 70:
                h[d // 2 * 2 + 1] += 1
    if not h:
        return None, None
    p1 = h.most_common(1)[0][0]
    outros = [(c, k) for k, c in h.items() if abs(k - p1) >= 6]
    if not outros:
        return p1, None
    p2 = max(outros)[1]
    return max(p1, p2), min(p1, p2)


# ------------------------------------------------------------------ pagina -> regioes
def eh_cabecalho(t):
    t = t.strip()
    if not t or len(t) > 95:
        return False
    if re.match(r"^\W*\d{1,4}\W", t) or re.search(r"\W\d{1,4}\W*$", t):
        return True
    letras = [c for c in t if c.isalpha()]
    return len(letras) >= 6 and sum(c.isupper() for c in letras) / len(letras) > 0.7


def calibra_tamanho(todas):
    """limiar de largura/caractere entre corpo grande e corpo menor (k-means 1D, 2 grupos).

    O livro usa corpo menor tambem FORA das notas (escolios, "Pergunta/Resposta", citacoes);
    so a entrelinha nao separa notas de corpo menor, mas o tamanho da letra separa corpo
    de corpo menor (largura/caractere ~21.5 contra ~17.5 px a 300 ppi)."""
    hs = sorted(l.h for linhas in todas for l in linhas if l.h)
    if len(hs) < 50:
        return None
    lo, hi = hs[len(hs) // 4], hs[3 * len(hs) // 4]
    for _ in range(20):
        meio = (lo + hi) / 2
        a = [h for h in hs if h < meio] or [lo]
        b = [h for h in hs if h >= meio] or [hi]
        lo, hi = statistics.mean(a), statistics.mean(b)
    return (lo + hi) / 2 if hi - lo >= 2 else None


def inicio_notas(linhas, corpo, limiar_h, aberta, margem=0, limiar_recuo=40):
    """indice da 1a linha da area de notas, ou len(linhas) se a pagina nao tem notas.

    Notas = o que fica em corpo menor DEPOIS da ultima linha em corpo grande.  Dentro dessa cauda:
      * se a pagina anterior tinha area de notas ("aberta") e ha um vao de ruler antes de uma
        cauda cuja 1a linha NAO e recuada, a cauda comeca por continuacao da nota (a pontuacao
        final nao serve: abreviacoes como "art. V)." a enganam);
      * senao a area comeca na 1a linha "(n)"; o que vier antes dela e corpo menor (escolio).
    Sem "(n)" e sem nota aberta, nao ha notas: a cauda e corpo menor."""
    if not limiar_h or len(linhas) < 2:
        return len(linhas)
    # tamanho por linha (largura/caractere) falta nas linhas curtas e oscila: mediana de janela 5
    hs, ult = [], limiar_h + 1
    for l in linhas:
        ult = l.h or ult                                   # sem medida: herda da linha anterior
        hs.append(ult)
    pequeno = [statistics.median(hs[max(0, i - 2):i + 3]) < limiar_h for i in range(len(hs))]
    n = len(linhas)
    pequena_ate_o_fim = [sum(pequeno[i:]) / (n - i) for i in range(n)]   # fracao de linhas pequenas de i ao pe
    f = next((i for i in range(1, n) if pequeno[i] and NOTA.match(linhas[i].texto)
              and pequena_ate_o_fim[i] >= 0.8), None)
    if aberta:                                             # resto de nota da pagina anterior, apos vao de ruler
        j = next((i for i in range(1, n) if linhas[i].y0 - linhas[i - 1].y0 >= 1.3 * corpo
                  and pequena_ate_o_fim[i] >= 0.85 and pequeno[i]
                  and linhas[i].x0 - margem < limiar_recuo and not NOTA.match(linhas[i].texto)), None)
        if j is not None and (f is None or j <= f):
            return j
    return f if f is not None else n


class Par:
    """paragrafo/nota em construcao: pecas = str | ('pb', n) | ('nota', Nota)."""

    def __init__(self, texto, pag, recuado):
        self.pecas, self.pag, self.recuado = [texto], pag, recuado

    def texto(self):
        return "".join(p for p in self.pecas if isinstance(p, str))

    def anexa(self, texto):
        """junta linha seguinte, desfazendo hifenizacao de fim de linha."""
        u = self.pecas[-1] if self.pecas and isinstance(self.pecas[-1], str) else None
        if u is not None and u.endswith("-") and texto[:1].islower():
            self.pecas[-1] = u[:-1] + texto
        elif u is not None:
            self.pecas[-1] = u + " " + texto
        else:
            self.pecas.append(texto)


def agrupa(linhas, passo, margem, limiar, vao):
    """linhas -> [Par]: recuo >= limiar ou vao > vao*passo abre paragrafo novo."""
    pars, ant = [], None
    for l in linhas:
        recuado = l.x0 - margem >= limiar
        novo = ant is None or recuado or (l.y0 - ant.y0) > vao * passo
        if novo:
            pars.append(Par(l.texto, None, recuado))
        else:
            pars[-1].anexa(l.texto)
        ant = l
    return pars


class Nota:
    vistos = {}

    def __init__(self, num, pag, pars):
        self.num, self.pag, self.pars = num, pag, pars   # pars: [Par]
        Nota.vistos[(pag, num)] = Nota.vistos.get((pag, num), 0) + 1
        k = Nota.vistos[(pag, num)]
        self.id = f"n{pag}-{num}" + ("" if k == 1 else f"-{k}")      # OCR repetiu o numero
        self.chamada = False


# ------------------------------------------------------------------ montagem do volume
def le_manifesto(pasta):
    with open(pasta / "manifesto.tsv", encoding="utf-8") as f:
        next(f)
        return [l.rstrip("\n").split("\t") for l in f]


class Alertas(list):
    def __call__(self, pag, tipo, msg):
        self.append((pag, tipo, msg))


def processa_paginas(pasta, de, ate, alerta):
    mani = [(pid, int(imp)) for pid, imp, *_ in le_manifesto(pasta)
            if (pasta / f"{pid}.tsv").exists()]
    dados = {pid: le_linhas(pasta / f"{pid}.tsv") for pid, _ in mani}
    corpo, nota = calibra_entrelinhas([d[0] for d in dados.values()])
    if not corpo:
        sys.exit("não consegui calibrar a entrelinha (tsv vazios?)")
    limiar_h = calibra_tamanho([d[0] for d in dados.values()])
    print(f"entrelinha calibrada: corpo ≈ {corpo} px, notas ≈ {nota} px; "
          f"limiar de largura por caractere: {limiar_h and round(limiar_h, 1)}", file=sys.stderr)

    fluxo = []                       # itens: ('pb', n, pid) | ('fw', texto) | ('p', Par)
    ultima_par = None                # ultimo Par de corpo emitido (para continuacao)
    nota_aberta = None               # ultima Nota (pode atravessar varias paginas)
    paginas = []
    pag_anterior_com_notas = False
    for pid, imp in mani:
        if (de and imp < de) or (ate and imp > ate):
            continue
        linhas, largura = dados[pid]
        paginas.append(imp)
        fluxo.append(("pb", imp, pid))
        if not linhas:
            continue
        limiar = max(30, int(0.025 * (largura or 1700)))
        x0s = sorted(l.x0 for l in linhas)
        margem = x0s[len(x0s) // 4]

        # 1. cabecalho
        if eh_cabecalho(linhas[0].texto) and (len(linhas) < 2 or linhas[1].y0 - linhas[0].y0 < 3 * corpo):
            fluxo.append(("fw", linhas[0].texto))
            linhas = linhas[1:]
            if not linhas:
                continue
        # 2. corpo x notas
        aberta = nota_aberta is not None and pag_anterior_com_notas
        k = inicio_notas(linhas, corpo, limiar_h, aberta, margem, limiar)
        l_corpo, l_notas = linhas[:k], linhas[k:]
        pars = agrupa(l_corpo, corpo, margem, limiar, 1.4)
        for p in pars:
            p.pag = imp

        # 3. notas da pagina (continuacao + novas)
        novas, cont = [], []
        if l_notas:
            if any(b.y0 - a.y0 >= 1.4 * corpo for a, b in zip(l_notas, l_notas[1:])):
                alerta(imp, "vao-nas-notas", "vão grande dentro da área de notas: corpo retomado depois de nota? (conferir na imagem)")
            npars = agrupa(l_notas, nota, margem, limiar, 1.5)
            # reagrupa: um Par que comeca por "(n)" abre nota; os demais, so se recuados, sao
            # paragrafos da nota corrente; sem recuo e sem "(n)" = continuacao.
            atual = None
            for p in npars:
                t = p.texto()
                m = NOTA.match(t)
                if m:
                    p.pecas[0] = t[m.end():]
                    num = m.group(1)
                    num = "1" if num in "lI|" else num
                    atual = Nota(num, imp, [p])
                    novas.append(atual)
                elif atual is None:
                    cont.append(p)             # antes da 1a "(n)": resto de nota anterior
                elif p.recuado:
                    atual.pars.append(p)
                else:
                    atual.pars[-1].anexa(t)
        if cont:
            if nota_aberta is None:
                alerta(imp, "continuacao-sem-nota", "área de notas começa sem “(n)” e não há nota aberta")
            else:
                if FIM_FRASE.search(nota_aberta.pars[-1].texto()):
                    alerta(imp, "continuacao-duvidosa", f"nota {nota_aberta.id} parecia terminada, mas continua")
                nota_aberta.pars[-1].pecas.append(("pb", imp))
                primeiro = cont[0]
                if primeiro.recuado:
                    nota_aberta.pars.append(primeiro)
                else:
                    nota_aberta.pars[-1].anexa(primeiro.texto())
                nota_aberta.pars.extend(cont[1:])
        if novas:
            nota_aberta = novas[-1]
        pag_anterior_com_notas = bool(novas or cont)

        # 4. continuacao de paragrafo do corpo
        if pars and ultima_par is not None and not pars[0].recuado and \
                not FIM_FRASE.search(ultima_par.texto()) and not re.match(r"^\d{1,3}\.\s", pars[0].texto()):
            cabeca = pars.pop(0)
            lig = [cabeca]
        else:
            lig = []
        # 5. liga notas as chamadas (por ordem; o numero confirma)
        corpo_pars = lig + pars
        liga_notas(corpo_pars, novas, imp, alerta)
        if lig:
            u = ultima_par
            c0 = lig[0].pecas
            if isinstance(u.pecas[-1], str) and u.pecas[-1].endswith("-") and c0[0][:1].islower():
                u.pecas[-1] = u.pecas[-1][:-1]               # hifen de fim de pagina
            elif isinstance(c0[0], str):
                c0[0] = " " + c0[0]
            u.pecas.append(("pb", imp))
            u.pecas.extend(c0)
            # o <pb> desta pagina passa a ficar DENTRO do paragrafo (nao no fluxo)
            fluxo.remove(("pb", imp, pid))
        for p in pars:
            fluxo.append(("p", p))
        if pars:
            ultima_par = pars[-1]
    return fluxo, paginas


def liga_notas(pars, novas, pag, alerta):
    """substitui "(n)" por ('nota', Nota) dentro das pecas dos paragrafos da pagina."""
    chamadas = []                    # (par, indice_da_peca, match)
    for p in pars:
        for i, pc in enumerate(p.pecas):
            if isinstance(pc, str):
                for m in CHAMADA.finditer(pc):
                    chamadas.append((p, i, m))
    if len(chamadas) != len(novas):
        alerta(pag, "chamadas-x-notas", f"{len(chamadas)} chamada(s) no corpo, {len(novas)} nota(s) iniciada(s)")
    pares = list(zip(chamadas, novas))
    if len(chamadas) != len(novas):                      # tenta por numero impresso
        por_num = {}
        for c in chamadas:
            n = c[2].group(1)
            por_num.setdefault("1" if n in "lI|" else n, c)
        pares = [(por_num[n.num], n) for n in novas if n.num in por_num]
    usados = set()
    # aplica de tras para frente em cada peca, para nao deslocar indices
    por_peca = {}
    for (p, i, m), nt in pares:
        n = m.group(1)
        if ("1" if n in "lI|" else n) != nt.num:
            alerta(pag, "numero-diverge", f"chamada ({n}) ligada à nota ({nt.num})")
        por_peca.setdefault((id(p), i), (p, i, []))[2].append((m, nt))
        usados.add(nt.id)
        nt.chamada = True
    for p, i, itens in por_peca.values():
        s = p.pecas[i]
        novo, pos = [], 0
        for m, nt in sorted(itens, key=lambda x: x[0].start()):
            novo.append(s[pos:m.start()])
            novo.append(("nota", nt))
            pos = m.end()
        novo.append(s[pos:])
        p.pecas[i:i + 1] = [x for x in novo if x != ""]
    # notas sem chamada: no fim do ultimo paragrafo, marcadas
    for nt in novas:
        if nt.id not in usados and pars:
            alerta(pag, "nota-sem-chamada", f"{nt.id} sem chamada; anexada ao fim do último parágrafo")
            pars[-1].pecas.append(("nota", nt))
            nt.chamada = True
    if novas and not pars:
        alerta(pag, "nota-sem-corpo", "página só com notas; chamadas estão na página anterior")


# ------------------------------------------------------------------ pecas -> XML
def poe_texto(el, s):
    if len(el):
        el[-1].tail = (el[-1].tail or "") + s
    else:
        el.text = (el.text or "") + s


def render_pecas(el, pecas, facs):
    for pc in pecas:
        if isinstance(pc, str):
            poe_texto(el, pc)
        elif pc[0] == "pb":
            etree.SubElement(el, T("pb"), n=str(pc[1]), facs=facs(pc[1]))
        elif pc[0] == "nota":
            render_nota(el, pc[1], facs)


def render_nota(pai, nt, facs):
    n = etree.SubElement(pai, T("note"), place="foot", n=nt.num)
    n.set(f"{{{XML}}}id", nt.id)
    if len(nt.pars) == 1:
        render_pecas(n, nt.pars[0].pecas, facs)
    else:
        for p in nt.pars:
            render_pecas(etree.SubElement(n, T("p")), p.pecas, facs)


# ------------------------------------------------------------------ estrutura (titulos, teses)
def norm(s):
    return re.sub(r"[^A-Z0-9 ]", "", re.sub(r"\s+", " ", s.upper().replace("Ç", "C").replace("Ã", "A")))


def eh_cabecalho_corrente(t):
    """linha de cabecalho que o OCR nao deixou na 1a posicao (ex.: "SECÇÃO I — CAPITULO III — … 75")."""
    return len(t) < 95 and re.match(r"^\W*(SEC\w{0,5}|PARTE|\d{1,3}\s+METAPH|METAPH)", t.upper().replace("Ç", "C")) \
        and ("—" in t or "-" in t) and re.search(r"\d\W*$", t) is not None


def reconhece_titulo(texto):
    """(nivel, rotulo, resto) para 'CAPITULO PRIMEIRO', 'ARTIGO I. Titulo', 'SECÇÃO II'; senão None."""
    t = texto.strip()
    if len(t) > 140:
        return None
    m = re.match(r"^(\S+)\s+([^\s.:,;]+)[\s.:,;—-]*(.*)$", t)
    if not m:
        return None
    a, b, resto = norm(m.group(1)), norm(m.group(2)), m.group(3).strip()
    ordinal = b in ORDINAIS or ROMANO.match(m.group(2).strip(".,;:")) is not None
    if not ordinal:
        return None
    if a == "PARTE":
        nivel = "parte"
    elif a.startswith("SEC") and len(a) <= 7:
        nivel = "seccao"
    elif a.startswith("CAP") and 7 <= len(a) <= 10:
        nivel = "capitulo"
    elif a in ("ARTIGO", "ARTIG0", "ARTICO", "ART") or (a.startswith("ART") and len(a) <= 7):
        nivel = "artigo"
    else:
        return None
    if resto and not (resto.isupper() or nivel == "artigo"):
        return None          # "Parte segunda é a..." em texto corrente
    rot = f"{m.group(1).strip().upper()} {m.group(2).strip('.,;:')}"
    if nivel == "artigo":
        rot = f"Artigo {m.group(2).strip('.,;:')}."
    return nivel, rot, resto


TESE = re.compile(r"^(\d{1,3})\s*[.,]\s+(.{2,140}?[.!?])\s*[—–-]+\s*(.*)$", re.S)
TESE_TITULO = re.compile(r"^(\d{1,3})\s*[.,]\s+(?P<t>[^.!?—–]{2,100}[.!?])\s*$")  # tese so com enunciado (p. ex. "12. Argumentos metaphysicos.")
SUMARIO = re.compile(r"^\s*summ?ario\s*[:.]?", re.I)


class Construtor:
    def __init__(self, alerta, facs):
        self.alerta, self.facs = alerta, facs
        self.raiz = etree.Element(T("div"), type="volume")
        self.pilha = [(0, self.raiz)]            # (nivel, elemento)
        self.pb_pend = []
        self.ultima_tese = 0
        self.tese_el = None
        self.ids, self.cont = set(), Counter()
        self.pag = None
        self.sumario = None
        self.ultimo_titulo = None                # elemento que ainda pode receber <head> de titulo

    # --- util
    def id_unico(self, base):
        i, n = base, 1
        while i in self.ids:
            n += 1
            i = f"{base}-{n}"
        self.ids.add(i)
        return i

    def atual(self):
        return self.tese_el if self.tese_el is not None else self.pilha[-1][1]

    def flush_pb(self, destino):
        for n, pid in self.pb_pend:
            etree.SubElement(destino, T("pb"), n=str(n), facs=self.facs(n))
        self.pb_pend = []

    def abre(self, nivel, rotulo):
        self.tese_el = None
        lv = NIVEL[nivel]
        while self.pilha[-1][0] >= lv:
            self.pilha.pop()
        pai = self.pilha[-1][1]
        self.cont[nivel] += 1
        sigla = {"parte": "parte", "seccao": "sec", "capitulo": "cap", "artigo": "art"}[nivel]
        d = etree.SubElement(pai, T("div"), type=nivel)
        d.set(f"{{{XML}}}id", self.id_unico(f"{sigla}-{self.cont[nivel]}"))
        self.flush_pb(d)
        h = etree.SubElement(d, T("head"), type="rotulo")
        h.text = rotulo
        self.pilha.append((lv, d))
        self.ultimo_titulo = d
        return d

    # --- itens do fluxo
    def pb(self, n, pid):
        self.pag = n
        self.pb_pend.append((n, pid))

    def fw(self, texto):
        el = etree.SubElement(self.atual(), T("fw"), type="header")
        el.text = texto
        # o pb pendente precede o cabecalho
        if self.pb_pend:
            self.flush_pb_antes(el)

    def flush_pb_antes(self, el):
        pai = el.getparent()
        i = pai.index(el)
        for n, pid in self.pb_pend:
            pb = etree.Element(T("pb"), n=str(n), facs=self.facs(n))
            pai.insert(i, pb)
            i += 1
        self.pb_pend = []

    def par(self, p):
        texto = p.texto().strip()
        t1 = texto
        if eh_cabecalho_corrente(t1):
            self.fw(t1)
            return
        # Summario (+ "ARTIGO I" colado no fim)
        if SUMARIO.match(texto):
            m = re.search(r"\s+(ARTIGO\s+[IVXL1l|]{1,5}\.?)\s*$", texto)
            tit = None
            if m:
                tit = reconhece_titulo(m.group(1))
                texto = texto[:m.start()].strip()
                p.pecas = [texto]
            m0 = SUMARIO.match(p.pecas[0])                       # o rotulo "Summario:" volta no .tex
            p.pecas[0] = p.pecas[0][m0.end():].lstrip()
            alvo = self.pilha[-1][1]
            arg = etree.Element(T("argument"))
            alvo.insert(self._pos_argumento(alvo), arg)
            ap = etree.SubElement(arg, T("p"))
            self.flush_pb_antes(ap) if self.pb_pend else None
            render_pecas(ap, p.pecas, self.facs)
            self.sumario = (ap, p)
            if tit:
                self.titulo_reconhecido(tit)
            return
        if self.sumario is not None and not reconhece_titulo(texto) and not TESE.match(texto):
            ap, ult = self.sumario
            if not FIM_FRASE.search("".join(ap.itertext())):     # Summario com recuo suspenso: continua
                m2 = re.search(r"\s+(ARTIGO\s+[IVXL1l|]{1,5}\.?)\s*$", texto)
                tit2 = reconhece_titulo(m2.group(1)) if m2 else None
                resto_s = texto[:m2.start()] if m2 else texto
                poe_texto(ap, " " + resto_s.strip())
                if tit2:
                    self.sumario = None
                    self.titulo_reconhecido(tit2)
                return
        self.sumario = None
        tit = reconhece_titulo(texto) if all(isinstance(x, str) for x in p.pecas) else None
        if tit and len(p.pecas) == 1:
            self.titulo_reconhecido(tit)
            return
        # titulo (caixa alta) logo apos um rotulo recem aberto
        if self.ultimo_titulo is not None:
            d = self.ultimo_titulo
            heads = d.findall(T("head"))
            if len(heads) == 1 and all(isinstance(x, str) for x in p.pecas) and not TESE.match(texto) and len(texto) <= 110 \
                    and (texto.isupper() or (d.get("type") == "artigo" and texto.endswith("."))):
                h = etree.SubElement(d, T("head"))
                h.text = texto
                self.flush_pb_antes(h) if self.pb_pend else None
                self.ultimo_titulo = None
                return
            self.ultimo_titulo = None
        m = TESE.match(texto) or TESE_TITULO.match(texto)
        m = m if len(p.pecas) >= 1 and isinstance(p.pecas[0], str) else None
        so_titulo = m is not None and m.re is TESE_TITULO
        if m and (not so_titulo or int(m.group(1)) == self.ultima_tese + 1) and self.tese_ok(int(m.group(1))):
            self.nova_tese(int(m.group(1)), p, m)
            return
        alvo = self.atual()
        el = etree.SubElement(alvo, T("p"))
        self.flush_pb_antes(el) if self.pb_pend else None
        if alvo.get("type") == "tese":
            self.numera_p(alvo, el)
        render_pecas(el, p.pecas, self.facs)

    def _pos_argumento(self, d):
        # depois dos <head>
        pos = 0
        for i, c in enumerate(d):
            if c.tag == T("head") or c.tag == T("pb"):
                pos = i + 1
        return pos

    def titulo_reconhecido(self, tit):
        nivel, rot, resto = tit
        d = self.abre(nivel, rot)
        if resto:
            h = etree.SubElement(d, T("head"))
            h.text = resto
            self.ultimo_titulo = None

    def tese_ok(self, n):
        e = self.ultima_tese + 1
        if n == e:
            return True
        if self.ultima_tese == 0:                       # 1a tese do trecho: qualquer numero
            return True
        if e < n <= e + 3 or n == self.ultima_tese:      # salto pequeno: dígito mal lido ou tese perdida
            self.alerta(self.pag, "tese-fora-de-sequencia", f"tese {n} depois da {self.ultima_tese}")
            return True
        return False

    def nova_tese(self, n, p, m):
        # reparte as pecas no 1o " — " apos o enunciado
        s0 = p.pecas[0]
        so_titulo = m.re is TESE_TITULO
        enun, resto0 = m.group(2).strip(), ("" if so_titulo else s0[m.start(3):])
        pai = self.pilha[-1][1]
        d = etree.SubElement(pai, T("div"), type="tese", n=str(n))
        d.set(f"{{{XML}}}id", self.id_unico(f"t{n}"))
        self.flush_pb(d)
        self.ultima_tese = n
        self.tese_el = d
        self.cont_p = 1
        el = etree.SubElement(d, T("p"))
        el.set(f"{{{XML}}}id", f"{d.get(f'{{{XML}}}id')}.p1")
        lab = etree.SubElement(el, T("label"))
        lab.text = f"{n}."
        lab.tail = " "
        hi = etree.SubElement(el, T("hi"), rend="bold")
        hi.text = enun
        hi.tail = "" if so_titulo else " — "
        render_pecas(el, [resto0] + p.pecas[1:] if resto0 else p.pecas[1:], self.facs)

    def numera_p(self, tese, el):
        self.cont_p += 1
        el.set(f"{{{XML}}}id", f"{tese.get(f'{{{XML}}}id')}.p{self.cont_p}")


def monta_xml(fluxo, facs, alerta, titulo, autor, ano):
    c = Construtor(alerta, facs)
    for it in fluxo:
        k = it[0]
        if k == "pb":
            c.pb(it[1], it[2])
        elif k == "fw":
            c.fw(it[1])
        elif k == "p":
            c.par(it[1])
    if c.pb_pend:
        c.flush_pb(c.pilha[-1][1])
    hoje = date.today().isoformat()
    cab = f"""<teiHeader>
  <fileDesc>
    <titleStmt>
      <title>{titulo}</title>
      <author>{autor}</author>
      <respStmt><resp>transcrição por OCR e estruturação mecânica (sem revisão)</resp><name>tesseract; tools/estruturar_tei.py</name></respStmt>
    </titleStmt>
    <publicationStmt><p>Rascunho de trabalho; não publicado.</p></publicationStmt>
    <sourceDesc><bibl>{autor}, {titulo}{', ' + ano if ano else ''}. Scan em PDF.</bibl></sourceDesc>
  </fileDesc>
  <revisionDesc><change when="{hoje}">TEI estruturado por tools/estruturar_tei.py a partir do .tsv do OCR por página.</change></revisionDesc>
</teiHeader>"""
    tei = etree.Element(T("TEI"), nsmap={None: TEI})
    tei.set(f"{{{XML}}}lang", "pt")
    tei.append(etree.fromstring(cab.replace("<teiHeader>", f'<teiHeader xmlns="{TEI}">', 1)))
    texto = etree.SubElement(tei, T("text"))
    etree.SubElement(texto, T("body")).append(c.raiz)
    return tei, c


def valida(tei, paginas, alerta):
    # so os <pb> do corpo: os de dentro de <note> marcam a nota que atravessa paginas
    pbs = [int(pb.get("n")) for pb in tei.iter(T("pb")) if not any(a.tag == T("note") for a in pb.iterancestors())]
    if sorted(pbs) != sorted(paginas):
        falta = sorted(set(paginas) - set(pbs))
        alerta(0, "sequencia-pb", f"{len(pbs)} <pb> contra {len(paginas)} páginas; faltam {falta[:10]}")
    elif pbs != paginas:
        i = next(i for i, (a, b) in enumerate(zip(pbs, paginas)) if a != b)
        alerta(pbs[i], "pb-fora-de-ordem", f"<pb> {pbs[i]} onde o manifesto manda {paginas[i]}")
    ids = [e.get(f"{{{XML}}}id") for e in tei.iter() if e.get(f"{{{XML}}}id")]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        alerta(0, "id-duplicado", str(dup[:10]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pasta", help="diretório de páginas (manifesto.tsv + <id>.tsv)")
    ap.add_argument("-o", "--saida", required=True)
    ap.add_argument("-f", "--de", type=int, help="1ª página impressa")
    ap.add_argument("-l", "--ate", type=int, help="última página impressa")
    ap.add_argument("--titulo", default="Elementos de Philosophia")
    ap.add_argument("--autor", default="Thiago Sinibaldi")
    ap.add_argument("--ano", default="")
    a = ap.parse_args()

    pasta, saida = Path(a.pasta), Path(a.saida)
    rel = Path(os.path.relpath(pasta.resolve(), saida.resolve().parent)).as_posix()
    facs = lambda n: f"{rel}/{n_para_id[n]}.png"
    n_para_id = {int(imp): pid for pid, imp, *_ in le_manifesto(pasta)}

    alerta = Alertas()
    fluxo, paginas = processa_paginas(pasta, a.de, a.ate, alerta)
    if not paginas:
        sys.exit("nenhuma página na faixa")
    tei, c = monta_xml(fluxo, facs, alerta, a.titulo, a.autor, a.ano)
    valida(tei, paginas, alerta)

    saida.parent.mkdir(parents=True, exist_ok=True)
    etree.ElementTree(tei).write(str(saida), encoding="UTF-8", xml_declaration=True, pretty_print=False)
    alt = saida.with_suffix(".alertas.tsv")
    with open(alt, "w", encoding="utf-8") as f:
        f.write("pagina\ttipo\tmensagem\n")
        for p, t, m in alerta:
            f.write(f"{p}\t{t}\t{m}\n")
    cont = Counter(etree.QName(e).localname for e in tei.iter() if isinstance(e.tag, str))
    tipos = Counter(t for _, t, _ in alerta)
    print(f"{saida}: {len(paginas)} páginas; " + ", ".join(
        f"{cont[k]} {k}" for k in ("div", "head", "p", "note", "fw", "pb")), file=sys.stderr)
    div = Counter(d.get("type") for d in tei.iter(T("div")))
    print("divisões:", dict(div), file=sys.stderr)
    print(f"{len(alerta)} alertas ({dict(tipos)}) → {alt}", file=sys.stderr)


if __name__ == "__main__":
    main()
