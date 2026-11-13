#!/usr/bin/env python3
"""Gerador DETERMINÍSTICO (sem LLM, sem rede) de slides beamer a partir do TEI da obra.

    python3 tools/gera_slides.py base  amostra.xml -o amostra.slides.txt
    python3 tools/gera_slides.py base  vol2/vol2.corrigido.xml --id art-6 -o art6.slides.txt
    python3 tools/gera_slides.py base  vol1/vol1.corrigido.xml -f 51 -l 56 --max-car 480
    python3 tools/gera_slides.py tex   art6.slides.txt -o art6.slides.tex
    python3 tools/gera_slides.py pdf   art6.slides.txt -o art6.slides.pdf      # ou direto do .xml
    python3 tools/gera_slides.py valida art6.slides.txt                        # sai 1 se houver problemas
    python3 tools/gera_slides.py resumo vol2/vol2.corrigido.xml --id cap-1     # slides por tipo

Dois passos, com uma FONTE intermediária editável (o que os editores corrigem no site):

    TEI --tei_para_fonte--> X.slides.txt --fonte_para_tex--> X.slides.tex --compilar--> X.slides.pdf

A fonte nunca é LaTeX: tudo o que está nela é tratado como TEXTO e escapado (`\\ { } $ & # % _ ^ ~`,
`[ ]`, `< > |`, crase), de modo que o `.tex` pode ser compilado num servidor com entrada não confiável.

FORMATO DA FONTE (.slides.txt)
  * linhas começadas por `%` são comentário;
  * um slide começa em `=== <tipo>`; tipos: capa secao tese definicao divisao argumento objecao
    resposta corolario escolio observacao citacao texto (tipo desconhecido vira `texto`);
  * logo depois, opcionais e em qualquer ordem: `# <título>` e `@ <referência>` (ex.: `n. 29 · p. 35`);
    em `capa` a primeira linha do corpo é o subtítulo; em `secao` a (única) linha de corpo é o rótulo
    (ex.: `Artigo II.`);
  * corpo, linha a linha: linha em branco separa parágrafos; `! texto` enunciado em destaque;
    `- item` tópico, `  - subitem` (2 espaços) aninhado em 1 nível; `> texto` citação;
    `Rótulo:: texto` linha rotulada (rótulo de até 20 caracteres, sem `::`; consecutivas formam um
    grupo); qualquer outra linha é parágrafo (linhas consecutivas se juntam);
    `+continua` (sozinha) = o slide segue no próximo;
  * inline: `*itálico*`, `**negrito**`, `^versalete^`; `\\*`, `\\^`, `\\\\` são os literais.
    Marcação sem par vira texto literal (nunca erro de compilação);
  * NEUTRALIZAÇÃO de início de linha: um parágrafo que começaria por `- ! > # @ % = +` ou que pareceria
    `Rótulo::` (ou `=== `, `+continua`) leva um `\\` na frente. O leitor da fonte tira esse `\\` e trata a
    linha como parágrafo (`\\` seguido de `\\`, `*` ou `^` é o escape inline, não o neutralizador).

REGRAS TEI -> FONTE (resumo; detalhes no código)
  * capa; um `secao` por div parte/seccao/capitulo/artigo (rótulo + título dos `head`); descartam-se
    `fw`, `pb` (só alimentam a página corrente), notas (salvo `--notas`) e `argument` (sumário);
  * `p type=` explícito manda; senão heurística por parágrafo/oração: tese (rótulo numérico + negrito
    inicial), definição, divisão, argumento (maior / `Ora` menor / `Logo` conclusão), objeção, resposta,
    corolário, escólio, observação, citação (latim / « »); o resto é `texto`;
  * subdivisões `a)`, `1.º`, `I.` viram slides próprios (título da tese + marcador + rubrica);
  * texto corrido vira tópicos (nos ` — ` e nas frases); nada é parafraseado: todo o texto do corpo
    aparece, literal e em ordem, exceto os conectivos `Ora`/`Logo` que viram rótulo (`Menor`,
    `Conclusão`), a numeração/marcador de subdivisão e a rubrica (que vão para o título);
  * paginação por orçamento ESTIMADO EM LINHAS (`--max-car` é a escala; padrão 544 = 8 linhas de parágrafo
    do tema: parágrafo/tópicos 8 linhas, `rotulados` 10 (9 com título de 2 linhas), enunciado até 5 linhas);
    o que couber num quadro fica num quadro (um argumento só é partido se Maior+Menor+Conclusão não couberem,
    e então dentro da linha mais longa, `Menor (cont.)`, com a Conclusão junto da última premissa); `+continua`
    e título `(cont.)`; frase única maior que o orçamento vai inteira; enunciado `!` de mais de 5 linhas vira
    parágrafo; no `!` o negrito do OCR é removido (só o termo definido fica em negrito nas definições);
    polissilogismo repete os rótulos `Menor`/`Conclusão`;
  * lixo de fim de linha do OCR (`|`, `¦`, caractere não alfanumérico solto que não seja pontuação legítima)
    é removido na leitura; são só caracteres não-palavra, então a conferência de texto integral não muda;
  * títulos: o título completo só no slide `tese`; subdivisões e continuações usam título curto (~60
    caracteres): `30. Título curto — a) rubrica` (tese com título em negrito) ou `n. 30 — a)`;
  * marcador de subdivisão + rubrica (itálico, ou cabeçalho curto `Pharinge. —`) vão para o título;
    fragmentos de linha do OCR (parágrafo sem pontuação final seguido de minúscula) são religados.
Só stdlib + lxml; sem efeitos colaterais no import.
"""
import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from lxml import etree

RAIZ = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- constantes
# Orçamento em LINHAS (tema academia-slides, medido): parágrafo 14/18 pt = 8 linhas de ~68 caracteres;
# `rotulados` 12,5/15 pt = 10 linhas de ~64 (9 se o título tiver 2 linhas); tópicos ~66 por linha;
# enunciado 16/20,5 pt ~56 por linha (até 5 linhas sem encolher). Pesos em "caracteres equivalentes"
# (linhas de parágrafo x UNIDADE); `--max-car` é a escala (MAX_CAR = corpo só de parágrafo = 8 linhas).
UNIDADE = 68
MAX_CAR = 544
CAP_P = 8.3            # capacidade (linhas de parágrafo) de um slide sem linhas rotuladas
CAP_ROT1 = 9.1         # idem, com `rotulados` e título de 1 linha (<= 45 caracteres)
CAP_ROT2 = 8.3         # idem, título de 2 linhas
RESERVA_L = 1.2        # linha "(continua)" nos slides que seguem no próximo
ENUNC_LINHAS = 5       # enunciado com mais linhas que isto encolhe a caixa: vira parágrafo
TITULO_1LINHA = 45
FOLGA_CAB = 0.0
# caracteres por linha, altura da linha (em linhas de parágrafo) e espaço extra de cada tipo de item
_CPL = {"p": 68, "-": 66, "--": 62, "rot": 64, "!": 56, ">": 62}
_LH = {"p": 1.0, "-": 1.0, "--": 1.0, "rot": 0.833, "!": 1.14, ">": 1.05}
_EXTRA = {"p": 0.35, "-": 0.33, "--": 0.25, "rot": 0.25, "!": 1.7, ">": 0.4}
LIMITE_CORRIDO = 260   # parágrafo `texto` até este tamanho (sem travessão) fica como parágrafo
PEQUENO = 28           # pedaço menor que isto é colado ao vizinho
TITULO_MAX = 80        # truncamento do título derivado de enunciado
OBRA = "Elementos de Philosophia"
AUTOR = "Thiago Sinibaldi"

TIPOS = {
    "capa": "Capa", "secao": "Seção", "tese": "Tese", "definicao": "Definição",
    "divisao": "Divisão", "argumento": "Argumento", "objecao": "Objeção", "resposta": "Resposta",
    "corolario": "Corolário", "escolio": "Escólio", "observacao": "Observação",
    "citacao": "Citação", "texto": "Texto",
}
P_TIPOS = {  # p@type do esquema -> tipo de slide
    "definicao": "definicao", "divisao": "divisao", "enunciado": "tese", "argumento": "argumento",
    "objecao": "objecao", "resposta": "resposta", "escolio": "escolio", "corolario": "corolario",
    "observacao": "observacao",
}
NIVEIS_SEC = ("parte", "seccao", "capitulo", "artigo")

IT, BOLD, SC = 1, 2, 4
REND = {"it": IT, "italic": IT, "i": IT, "bold": BOLD, "b": BOLD, "sc": SC, "smallcaps": SC}

MARC = "[\U000F0000-\U000FFFFD]"      # marcador de página (plano 15 PUA): 1 caractere por <pb>
MARC_RE = re.compile(MARC)
M = MARC + "*"
VISIVEL_RE = re.compile(r"[^\s\U000F0000-\U000FFFFD]")


class ErroSlides(Exception):
    """Falha de geração/compilação. `.mensagem` e `.log_resumido` (últimas linhas relevantes do log)."""

    def __init__(self, mensagem, log_resumido=""):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.log_resumido = log_resumido

    def __str__(self):
        return self.mensagem


# --------------------------------------------------------------------------- texto rico
class R:
    """Texto com formatação por caractere (`f`: bits IT/BOLD/SC) e marcadores de página inline."""
    __slots__ = ("s", "f")

    def __init__(self, s="", f=None):
        self.s = s
        self.f = f if f is not None else bytearray(len(s))

    def __len__(self):
        return len(self.s)

    def __getitem__(self, k):
        if not isinstance(k, slice):
            raise TypeError("só fatias")
        a, b, _ = k.indices(len(self.s))
        return R(self.s[a:b], bytearray(self.f[a:b]))

    def __add__(self, o):
        return R(self.s + o.s, bytearray(self.f) + o.f)

    @property
    def plano(self):
        return MARC_RE.sub("", self.s)

    def vazio(self):
        return not VISIVEL_RE.search(self.s)

    def strip(self):
        s = self.s
        a, b = 0, len(s)
        while a < b and s[a].isspace():
            a += 1
        while b > a and s[b - 1].isspace():
            b -= 1
        return self[a:b]

    def lstrip_chars(self, chars):
        """tira, no início, espaços e `chars` (preserva marcadores de página, recolocando-os)."""
        s, i = self.s, 0
        marc = []
        while i < len(s) and (s[i].isspace() or s[i] in chars or MARC_RE.match(s[i])):
            if MARC_RE.match(s[i]):
                marc.append(s[i])
            i += 1
        resto = self[i:]
        return R("".join(marc), bytearray(len(marc))) + resto if marc else resto

    def rstrip_chars(self, chars):
        s, b = self.s, len(self.s)
        while b > 0 and (s[b - 1].isspace() or s[b - 1] in chars):
            b -= 1
        return self[:b]


def junta(partes, sep=" "):
    partes = [p for p in partes if len(p)]
    if not partes:
        return R()
    s = []
    f = bytearray()
    for i, p in enumerate(partes):
        if i and sep:
            s.append(sep)
            f.extend(b"\0" * len(sep))
        s.append(p.s)
        f.extend(p.f)
    return R("".join(s), f)


LEGITIMA = set("—–-;:,.?!»«)(\"'“”…§&")
_JUNK_SOLTO = re.compile(r"(?:(?<=\s)|^)([^\w\s" + re.escape("".join(LEGITIMA)) + r"])(?=\s|$)")
_JUNK_FIM = re.compile(r"[|¦]+(?=" + M + r"\s*$)")


def limpa_lixo(r):
    """tira do OCR as marcas isoladas de fim de linha: `|`, `¦` e qualquer caractere não alfanumérico sozinho
    entre espaços que não seja pontuação legítima (`— – - ; : , . ? ! » « ) ( " ' § &`); também `|`/`¦`
    colados ao fim do bloco. Só remove caracteres não-palavra: a comparação de palavras não muda."""
    s = r.s
    corte = [False] * len(s)
    for rx in (_JUNK_SOLTO, _JUNK_FIM):
        for m in rx.finditer(s):
            for k in range(m.start(), m.end()):
                if not MARC_RE.match(s[k]):
                    corte[k] = True
    if not any(corte):
        return r
    out = R("".join(c for c, x in zip(s, corte) if not x),
            bytearray(f for f, x in zip(r.f, corte) if not x))
    return normaliza(out)


def r_de(txt, flag=0):
    return R(txt, bytearray([flag]) * len(txt))


def normaliza(r):
    """espaços colapsados; marcador de página fica depois do espaço que o segue."""
    s, f = r.s, r.f
    os_, of = [], bytearray()
    i, n = 0, len(s)
    prev_esp = True  # trata o início como "depois de espaço" (corta espaços iniciais)
    while i < n:
        ch = s[i]
        if ch.isspace() or ch in "\u00ad\u200b\ufeff":
            if ch in "\u00ad\u200b\ufeff":
                i += 1
                continue
            # espaço(s) possivelmente entremeados de marcadores
            j = i
            marc = []
            while j < n and (s[j].isspace() or MARC_RE.match(s[j])):
                if MARC_RE.match(s[j]):
                    marc.append(s[j])
                j += 1
            if not prev_esp:
                os_.append(" ")
                of.append(f[i])
                prev_esp = True
            for m in marc:
                os_.append(m)
                of.append(0)
            i = j
            continue
        if ord(ch) < 32 or MARC_RE.match(ch) and False:
            i += 1
            continue
        os_.append(ch)
        of.append(f[i])
        prev_esp = False
        i += 1
    out = R("".join(os_), of)
    return out.strip()


# --------------------------------------------------------------------------- serialização da fonte
def esc_inline(txt):
    return txt.replace("\\", "\\\\").replace("*", "\\*").replace("^", "\\^")


def _marcas(fl):
    return [m for bit, m in ((BOLD, "**"), (IT, "*"), (SC, "^")) if fl & bit]


def r_para_fonte(r):
    """R -> marcação inline da fonte (sem marcadores de página). Espaços de borda ficam fora das marcas."""
    runs = []
    for ch, fl in zip(r.s, r.f):
        if MARC_RE.match(ch):
            continue
        if runs and runs[-1][0] == fl:
            runs[-1][1].append(ch)
        else:
            runs.append((fl, [ch]))
    pecas = []
    for fl, chars in runs:
        txt = "".join(chars)
        if fl:
            miolo = txt.strip(" ")
            if not miolo:
                pecas.append((0, txt))
                continue
            lead = len(txt) - len(txt.lstrip(" "))
            trail = len(txt) - len(txt.rstrip(" "))
            if lead:
                pecas.append((0, txt[:lead]))
            pecas.append((fl, miolo))
            if trail:
                pecas.append((0, txt[len(txt) - trail:]))
        else:
            pecas.append((0, txt))
    pilha, res = [], []
    for fl, txt in pecas:
        alvo = _marcas(fl)
        k = 0
        while k < len(pilha) and k < len(alvo) and pilha[k] == alvo[k]:
            k += 1
        for m in reversed(pilha[k:]):
            res.append(m)
        pilha = pilha[:k]
        for m in alvo[k:]:
            res.append(m)
            pilha.append(m)
        res.append(esc_inline(txt))
    for m in reversed(pilha):
        res.append(m)
    return "".join(res)


_ROT_RE = re.compile(r"^([^:\n]{1,20})::(?:\s+(.*))?$")


def linha_paragrafo(fonte_txt):
    """neutraliza o início de uma linha de parágrafo (ver docstring)."""
    t = fonte_txt
    if not t:
        return t
    if t[0] in "-!>#@%=+" or _ROT_RE.match(t):
        return "\\" + t
    return t


# --------------------------------------------------------------------------- inline da fonte
_TOK_RE = re.compile(r"\\.|\*+|\^|[^\\*^]+|\\", re.S)


def _parse_inline(raw):
    """-> (tokens, literais). tokens: ('t', texto) | ('+', k) | ('-', k), k em 'b','i','s'.
    Marcas sem par viram texto (e entram em `literais`)."""
    toks = []          # cada elemento: [tipo, valor]
    pilha = []         # índices em toks das aberturas
    literais = []
    lit = {"b": "**", "i": "*", "s": "^"}

    def vira_literal(j):
        literais.append(lit[toks[j][1]])
        toks[j] = ["t", lit[toks[j][1]]]

    def fecha(ix):
        for j in pilha[ix + 1:]:          # abertas por cima ficam sem par
            vira_literal(j)
        k = toks[pilha[ix]][1]
        del pilha[ix:]
        toks.append(["-", k])

    def abre(k):
        pilha.append(len(toks))
        toks.append(["+", k])

    for m in _TOK_RE.finditer(raw):
        t = m.group(0)
        if t[0] == "\\":
            toks.append(["t", t[1] if len(t) == 2 and t[1] in "\\*^" else t])
        elif t[0] == "*":
            n = len(t)
            while n:
                topo = toks[pilha[-1]][1] if pilha else None
                abertos = [toks[j][1] for j in pilha]
                if topo == "i" and n >= 1:
                    if n == 1 or "b" in abertos or n >= 3:
                        fecha(len(pilha) - 1)
                        n -= 1
                    else:                                  # `**` dentro de itálico, sem negrito aberto
                        abre("b")
                        n -= 2
                elif topo == "b" and n >= 2:
                    fecha(len(pilha) - 1)
                    n -= 2
                elif n >= 2 and "b" in abertos:
                    fecha(len(abertos) - 1 - abertos[::-1].index("b"))
                    n -= 2
                elif n >= 2:
                    abre("b")
                    n -= 2
                elif "i" in abertos:
                    fecha(len(abertos) - 1 - abertos[::-1].index("i"))
                    n -= 1
                else:
                    abre("i")
                    n -= 1
        elif t == "^":
            ix = [x for x, j in enumerate(pilha) if toks[j][1] == "s"]
            if ix:
                fecha(ix[-1])
            else:
                abre("s")
        else:
            toks.append(["t", t])
    for j in pilha:
        vira_literal(j)
    return [tuple(t) for t in toks], literais


def parse_inline(raw):
    return _parse_inline(raw)[0]


def marcas_sem_par(raw):
    """marcas inline que ficaram sem par (para a validação)."""
    return _parse_inline(raw)[1]


def plano(raw):
    return "".join(v for k, v in parse_inline(raw) if k == "t")


_ESC_TEX = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    "|": r"\textbar{}", "<": r"\textless{}", ">": r"\textgreater{}", "[": "{[}", "]": "{]}",
    "`": r"\textasciigrave{}",
}
_ESC_RE = re.compile("[" + re.escape("".join(_ESC_TEX)) + "]")
_CTRL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffe\uffff\U000F0000-\U000FFFFD]")
_CMD = {"b": r"\textbf{", "i": r"\textit{", "s": r"\textsc{"}


def esc_tex(txt):
    txt = _CTRL_RE.sub("", txt)
    txt = _ESC_RE.sub(lambda m: _ESC_TEX[m.group(0)], txt)
    txt = re.sub(r"\s*\u2014\s*", " --- ", txt) if " \u2014 " in txt else txt
    return txt.replace("\u2014", "---").replace("\u2013", "--")


def inline_tex(raw):
    out = []
    for k, v in parse_inline(raw):
        if k == "t":
            out.append(esc_tex(v))
        elif k == "+":
            out.append(_CMD[v])
        else:
            out.append("}")
    return "".join(out)


# --------------------------------------------------------------------------- leitor da fonte
_TIPO_RE = re.compile(r"^===[ \t]*(\S*)[ \t]*(.*)$")


def _parse(fonte):
    """-> (slides, msgs). slide = dict(linha, tipo, titulo, ref, corpo, continua)."""
    msgs = []
    slides = []
    cur = None
    para = []
    para_ini = 0
    apos_continua = False

    def fecha_para():
        nonlocal para
        if para and cur is not None:
            cur["corpo"].append(("p", " ".join(para), para_ini))
        para = []

    for num, linha in enumerate(fonte.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        s = linha.rstrip()
        if s.startswith("%"):
            continue
        if not s.strip():
            fecha_para()
            continue
        neutro = False
        if s.startswith("\\") and len(s) > 1 and s[1] not in "\\*^":
            s = s[1:]
            neutro = True
        if not neutro and s.startswith("==="):
            fecha_para()
            m = _TIPO_RE.match(s)
            t = (m.group(1) or "").lower()
            ok = t in TIPOS
            if not ok:
                msgs.append(f"linha {num}: tipo de slide desconhecido {m.group(1)!r} (será usado 'texto')")
                t = "texto"
            if m.group(2):
                msgs.append(f"linha {num}: texto depois do tipo foi ignorado")
            cur = {"linha": num, "tipo": t, "titulo": None, "ref": None, "corpo": [], "continua": False,
                   "meta_linha": {}}
            slides.append(cur)
            apos_continua = False
            continue
        if cur is None:
            msgs.append(f"linha {num}: conteúdo antes do primeiro '===' (ignorado)")
            continue
        if apos_continua:
            msgs.append(f"linha {num}: conteúdo depois de '+continua' (o '+continua' deve ser a última linha do slide)")
            apos_continua = False
        if not neutro:
            if s.startswith("# ") or s == "#":
                fecha_para()
                if cur["titulo"] is not None:
                    msgs.append(f"linha {num}: '#' repetido no mesmo slide (mantido o primeiro)")
                else:
                    cur["titulo"] = s[1:].strip()
                    cur["meta_linha"]["titulo"] = num
                continue
            if s.startswith("@ ") or s == "@":
                fecha_para()
                if cur["ref"] is not None:
                    msgs.append(f"linha {num}: '@' repetido no mesmo slide (mantido o primeiro)")
                else:
                    cur["ref"] = s[1:].strip()
                    cur["meta_linha"]["ref"] = num
                continue
            if s.strip() == "+continua":
                fecha_para()
                cur["continua"] = True
                apos_continua = True
                continue
            if s[0] == "!" and (len(s) == 1 or s[1] == " "):
                fecha_para()
                cur["corpo"].append(("!", s[1:].strip(), num))
                continue
            if s[0] == ">" and (len(s) == 1 or s[1] == " "):
                fecha_para()
                cur["corpo"].append((">", s[1:].strip(), num))
                continue
            m = re.match(r"^(?: {2,}|\t+)-(?:\s+(.*))?$", s)
            if m:
                fecha_para()
                cur["corpo"].append(("--", (m.group(1) or "").strip(), num))
                continue
            m = re.match(r"^-(?:\s+(.*))?$", s)
            if m:
                fecha_para()
                cur["corpo"].append(("-", (m.group(1) or "").strip(), num))
                continue
            m = _ROT_RE.match(s)
            if m:
                fecha_para()
                cur["corpo"].append(("rot", (m.group(2) or "").strip(), num, m.group(1).strip()))
                continue
        if not para:
            para_ini = num
        para.append(s.strip())
    fecha_para()
    return slides, msgs


def validar(fonte):
    """lista de mensagens `linha N: …` (vazia = fonte sem problemas)."""
    slides, msgs = _parse(fonte)
    for sl in slides:
        n = sl["linha"]
        if sl["titulo"] in (None, "") and not sl["corpo"]:
            msgs.append(f"linha {n}: slide vazio (sem título nem corpo)")
        elif sl["tipo"] in ("capa", "secao") and not sl["titulo"]:
            msgs.append(f"linha {n}: slide '{sl['tipo']}' sem título ('# …')")
        ant = None
        for it in sl["corpo"]:
            if it[0] == "--" and ant not in ("-", "--"):
                msgs.append(f"linha {it[2]}: tópico aninhado sem tópico pai (tratado como tópico)")
            ant = it[0]
        linhas = []
        if sl["titulo"]:
            linhas.append((sl["meta_linha"].get("titulo", n), sl["titulo"]))
        if sl["ref"]:
            linhas.append((sl["meta_linha"].get("ref", n), sl["ref"]))
        for it in sl["corpo"]:
            linhas.append((it[2], it[1]))
        for ln_, raw in linhas:
            sem = marcas_sem_par(raw)
            if sem:
                msgs.append(f"linha {ln_}: marcação {', '.join(repr(x) for x in dict.fromkeys(sem))} "
                            f"sem par (será tratada como texto)")
    def chave(m):
        mm = re.match(r"linha (\d+):", m)
        return int(mm.group(1)) if mm else 0
    return sorted(msgs, key=chave)


def contar_slides(fonte):
    return len(_parse(fonte)[0])


# --------------------------------------------------------------------------- fonte -> LaTeX
def _corpo_tex(corpo):
    blocos = []
    i, n = 0, len(corpo)
    while i < n:
        k = corpo[i][0]
        if k == "p":
            blocos.append(inline_tex(corpo[i][1]))
            i += 1
        elif k == "!":
            blocos.append("\\begin{enunciado}\n" + inline_tex(corpo[i][1]) + "\n\\end{enunciado}")
            i += 1
        elif k in ("-", "--"):
            j = i
            while j < n and corpo[j][0] in ("-", "--"):
                j += 1
            blocos.append(_topicos_tex(corpo[i:j]))
            i = j
        elif k == ">":
            j = i
            while j < n and corpo[j][0] == ">":
                j += 1
            blocos.append("\\begin{citacao}\n" + "\n\n".join(inline_tex(c[1]) for c in corpo[i:j])
                          + "\n\\end{citacao}")
            i = j
        elif k == "rot":
            j = i
            while j < n and corpo[j][0] == "rot":
                j += 1
            linhas = [f"\\rot{{{inline_tex(c[3])}}}{{{inline_tex(c[1])}}}" for c in corpo[i:j]]
            blocos.append("\\begin{rotulados}\n" + "\n".join(linhas) + "\n\\end{rotulados}")
            i = j
        else:  # nunca acontece
            i += 1
    return "\n\n".join(blocos)


def _topicos_tex(itens):
    out = ["\\begin{topicos}"]
    aninhado = False
    for it in itens:
        if it[0] == "--" and not (len(out) > 1):
            it = ("-",) + tuple(it[1:])          # sem pai: vira tópico
        if it[0] == "--":
            if not aninhado:
                out.append("\\begin{topicos}")
                aninhado = True
            out.append("\\item " + inline_tex(it[1]))
        else:
            if aninhado:
                out.append("\\end{topicos}")
                aninhado = False
            out.append("\\item " + inline_tex(it[1]))
    if aninhado:
        out.append("\\end{topicos}")
    out.append("\\end{topicos}")
    return "\n".join(out)


def fonte_para_tex(fonte, *, trecho=None):
    """fonte -> documento beamer completo (o contrato com tex/slides/academia-slides.sty)."""
    slides, _ = _parse(fonte)
    if trecho is None:
        trecho = next((plano(s["titulo"]) for s in slides if s["tipo"] == "capa" and s["titulo"]), "")
    out = [
        "% !TEX program = lualatex",
        "\\documentclass[aspectratio=169,11pt]{beamer}",
        "\\usepackage{academia-slides}",
        f"\\slidesmeta{{{esc_tex(OBRA)}}}{{{esc_tex(AUTOR)}}}{{{esc_tex(trecho)}}}",
        "\\begin{document}",
        "",
    ]
    for sl in slides:
        t = sl["tipo"] if sl["tipo"] in TIPOS else "texto"
        tit = inline_tex(sl["titulo"] or "")
        ref = inline_tex(sl["ref"] or "")
        primeiro = inline_tex(sl["corpo"][0][1]) if sl["corpo"] else ""
        if t == "capa":
            out.append(f"\\slidecapa{{{tit}}}{{{primeiro}}}{{{ref}}}")
        elif t == "secao":
            out.append(f"\\slidesecao{{{primeiro}}}{{{tit}}}")
        else:
            corpo = _corpo_tex(sl["corpo"])
            out.append(f"\\begin{{slide}}{{{t}}}{{{tit}}}{{{ref}}}")
            if corpo:
                out.append(corpo)
            if sl["continua"]:
                out.append("\\continua")
            out.append("\\end{slide}")
        out.append("")
    out.append("\\end{document}")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- compilação
def _resumo_log(log_txt):
    linhas = log_txt.splitlines()
    achados = []
    for i, l in enumerate(linhas):
        if l.startswith("!") or "Fatal error" in l or "Emergency stop" in l:
            achados.extend(linhas[i:i + 6])
            if len(achados) > 30:
                break
    return "\n".join(achados[:30] or linhas[-20:])


def compilar(tex, destino_pdf, *, timeout=180):
    """compila `tex` (lualatex, via latexmk) em diretório temporário e copia o PDF para `destino_pdf`."""
    destino_pdf = Path(destino_pdf)
    if shutil.which("latexmk") is None:
        raise ErroSlides("latexmk não encontrado no servidor")
    with tempfile.TemporaryDirectory(prefix="slides-") as d:
        d = Path(d)
        (d / "slides.tex").write_text(tex, encoding="utf-8")
        env = dict(os.environ)
        env["TEXINPUTS"] = f"{RAIZ / 'tex' / 'slides'}//:" + env.get("TEXINPUTS", "")
        env["shell_escape"] = "f"          # sem \write18, de qualquer modo
        env["openout_any"] = "p"
        cmd = ["latexmk", "-lualatex", "-interaction=nonstopmode", "-halt-on-error",
               "slides.tex"]
        proc = subprocess.Popen(cmd, cwd=d, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            saida, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.communicate()
            raise ErroSlides(f"compilação passou de {timeout}s e foi interrompida")
        log = d / "slides.log"
        log_txt = log.read_text(encoding="utf-8", errors="replace") if log.exists() else (
            saida.decode("utf-8", "replace"))
        pdf = d / "slides.pdf"
        if proc.returncode != 0 or not pdf.exists():
            raise ErroSlides("o LaTeX falhou ao compilar os slides", _resumo_log(log_txt))
        destino_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, destino_pdf)


# =========================================================================== TEI -> fonte
def ln(e):
    t = e.tag
    return t.split("}", 1)[1] if isinstance(t, str) and t.startswith("{") else t


XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

ABREV = set("""s st sto sta sr sra srs dr p pp pag pg q qq a aa art arts c cc cap caps l ll lib liv v vv vol
tom t n nn th cf cfr etc ib ibid id op cit ex exs gr lat ed seg sq sqq ss obj resp trad ob sent disp lect
dist ad cont gent summ theol met phys anim eth post prior pr prol ver vers tit pars part ca fol
obs corp conc tr sup inf e.g i.e v.g vg m mm ms sec secc fig figs ap apud ch cor col vid""".split())
INICIOS_FRASE = {"ora", "logo", "mas", "por", "assim", "se", "porém", "todavia", "portanto", "pois",
                 "além", "ao", "a", "o", "as", "os", "um", "uma", "em", "na", "no", "quando", "que"}
ROMANO = re.compile(r"^[IVXLCDM]{1,5}$")
_FIM_RE = re.compile(r"[.!?…]+[»”\"')\]]*" + M + r"(?=\s)")


def fronteiras(s):
    """lista de (corte, inicio_da_proxima): onde uma frase termina e a seguinte começa."""
    out = []
    n = len(s)
    for m in _FIM_RE.finditer(s):
        fim = m.end()
        k = fim
        while k < n and (s[k].isspace() or MARC_RE.match(s[k])):
            k += 1
        if k >= n:
            continue
        k2 = k
        if s[k] in "—–" and k + 1 < n and s[k + 1].isspace():
            k2 = k + 1
            while k2 < n and (s[k2].isspace() or MARC_RE.match(s[k2])):
                k2 += 1
            if k2 >= n:
                continue
        nxt = s[k2]
        if nxt in "«“\"(¿[":
            if k2 + 1 >= n or not (s[k2 + 1].isupper() or s[k2 + 1].isdigit()):
                continue
        elif not nxt.isupper():
            continue
        pont = re.match(r"[.!?…]+", m.group(0)).group(0)
        if pont == ".":
            anterior = MARC_RE.sub("", s[:m.start()])
            mw = re.search(r"(\S+)$", anterior)
            w = mw.group(1) if mw else ""
            wl = w.lower().strip("([«“\"'*")
            if wl == "etc":
                prox = re.match(r"\w+", MARC_RE.sub("", s[k2:]))
                if not (prox and prox.group(0).lower() in INICIOS_FRASE):
                    continue
            elif wl in ABREV or (len(w) == 1 and w.isalpha()) or ROMANO.match(w.strip("([«“\"'")):
                continue
        out.append((fim, k2))
    return out


def frases(r):
    """divide R em frases (o travessão que abre a frase seguinte é descartado)."""
    s = r.s
    cortes = fronteiras(s)
    if not cortes:
        x = r.strip()
        return [x] if not x.vazio() else []
    out = []
    ini = 0
    for corte, prox in cortes:
        x = r[ini:corte].strip()
        if not x.vazio():
            out.append(x)
        ini = prox
    x = r[ini:].strip()
    if not x.vazio():
        out.append(x)
    return out


_TRAV_RE = re.compile(r"\s(?:[—–]|-{1,2})\s|(?<=[;:,.])\s(?=\d{1,2}\.º\s)")


def divide_travessao(r):
    """-> lista de (R, depois_de_travessao). Preserva tudo exceto o próprio travessão."""
    s = r.s
    out = []
    ini = 0
    trav = False
    for m in _TRAV_RE.finditer(s):
        x = r[ini:m.start()].strip()
        if not x.vazio():
            out.append((x, trav))
        trav = bool(m.group(0).strip())
        ini = m.end()
    x = r[ini:].strip()
    if not x.vazio():
        out.append((x, trav))
    return out


def pedacos(r):
    """frases e membros separados por travessão, com colagem dos pedaços minúsculos."""
    lista = []
    for fr in frases(r):
        for x, tr in divide_travessao(fr):
            lista.append([x, tr])
    out = []
    for x, tr in lista:
        if out and len(x.plano) < PEQUENO:
            out[-1][0] = junta([out[-1][0], x], " — " if tr else " ")
        else:
            out.append([x, tr])
    if len(out) >= 2 and len(out[0][0].plano) < PEQUENO:
        a = out.pop(0)
        out[0][0] = junta([a[0], out[0][0]], " ")
    return out


# --- classificação de frases ------------------------------------------------------------
LAT = set("""est sunt et non quod quia qui quae quid ut sed autem enim ergo esse cum sicut ab ex nec vel aut sit
potest ens omnis omne nihil igitur etiam unde ideo tamen secundum scilicet dicitur dico inquit ait ipse ipsum
hoc haec illa ille eius eorum fit fieri sibi sui suo suae dei in per ad quo quam quem quibus quidem tamquam
nam si ita vero quoniam aliquid aliquod alia alius omnia omnium habet habent possunt potest oportet eo ea id
rei res rerum sive seu dum cui cuius quoque itaque neque nisi tantum solum tunc modo enim mihi tibi nos""".split())
PT = set("""que não é uma para como mas os as do da dos das se por são um com ao em na no nas nos ou mais pelo pela
isto esta este tambem porque quando ella elle ser seu sua seus suas tem ha póde também só já aos às
pois onde cada sem sob entre sobre todo toda todos todas então assim mesmo pode sua""".split())


def razao_latim(txt):
    ws = re.findall(r"[^\W\d_]+", txt.lower())
    if len(ws) < 8:
        return 0.0
    la = sum(1 for w in ws if w in LAT)
    pt = sum(1 for w in ws if w in PT)
    if la + pt < 4:
        return 0.0
    return la / (la + pt)


def eh_citacao(r):
    t = r.plano.strip()
    if len(t.split()) >= 8 and t[0] in "«“" and re.search(r"[»”][.,;:!?]?$", t):
        return True
    return razao_latim(t) >= 0.6


_PT_PRE = r"^(?:\W*)"
RX_OBJ = re.compile(_PT_PRE + r"(?:Objec[çc][ãa]o|Objec[çc][õo]es|Objecta(?:m|-se)?|Objectam|Opp[õo]em|Opp[õo]e-se|"
                    r"Dizem|Diz-se que|Alguns (?:dizem|objectam)|Obje[çc][ãõ]|Objetam|Objecta)(?![\w-])", re.I)
RX_RESP = re.compile(_PT_PRE + r"(?:Respondemos|Responde-se|Resp\b\.?|Resposta|Respondo|Responde(?:m)?)\b", re.I)
RX_COR = re.compile(_PT_PRE + r"(?:Corollari[oa]s?|Corol[aá]ri[oa]s?|Coroll\b\.?|Corol\b\.?)", re.I)
RX_ESC = re.compile(_PT_PRE + r"(?:Escholi[oa]s?|Esc[oó]li[oa]s?|Scholi[oa]s?|Scholium|Scholia|Esch\b\.?|Schol\b\.?)", re.I)
RX_OBS = re.compile(_PT_PRE + r"(?:Observa[çc][ãa]o|Observa[çc][õo]es|Nota-se|Notae|Advirta-se|Advertimos|"
                    r"Advert[êe]ncia|Note-se|Observe-se|Observa-se|Nota\b[.:])", re.I)
RX_DIV_FORTE = re.compile(
    r"\b(?:divide-se|dividem-se|dividir-se|d[ií]vide-se|Divis[ãa]o|Divis[õo]es|distinguem-se em|distingue-se em|"
    r"é de (?:duas|tres|três|quatro|cinco|seis|varias|várias|diversas|differentes) "
    r"(?:especies|espécies|classes|generos|gêneros|sortes|modos|maneiras)|"
    r"(?:ha|há|são|temos) (?:duas|tres|três|quatro|cinco|seis|varias|várias) "
    r"(?:especies|espécies|classes|generos|sortes|modos|partes|maneiras))\b", re.I)
RX_DIV_FRACO = re.compile(r"\b(?:p[óo]de ser|podem ser)\b", re.I)
RX_DEF_VERBO = re.compile(r"\b(?:é|são|chama-se|chamam-se|diz-se|dizem-se|denomina-se|denominam-se|significa|"
                          r"entende-se|define-se)\b")
RX_DEF_INICIO = re.compile(r"^\W*(?:Entende-se por|Define-se|Chama-se|Chamam-se|Diz-se|Dizem-se|Entendemos por|"
                           r"Chamamos|Denomina-se|Denominam-se)\b")
RX_DEF_ART = re.compile(r"^(?:o|a|á|à|os|as|um|uma|aquell[ea]s?|toda|todo|que|propriedade|expressão|qualidade)\b", re.I)
RX_TIT_DEF = re.compile(r"^\W*(?:Noção|Noções|Definição|Definições|Natureza|Conceito|Idea|Ideia|Que é|O que é)\b", re.I)


def tipo_da_frase(r, forte_def=False):
    """tipo sugerido por uma frase (None = comum)."""
    p = r.plano.strip()
    if not p:
        return None
    if RX_COR.match(p):
        return "corolario"
    if RX_ESC.match(p):
        return "escolio"
    if RX_OBS.match(p):
        return "observacao"
    if RX_RESP.match(p):
        return "resposta"
    if RX_OBJ.match(p):
        return "objecao"
    if eh_citacao(r):
        return "citacao"
    # divisão: gatilho forte em qualquer ponto; fraco só com >= 2 termos em itálico/negrito depois
    m = RX_DIV_FORTE.search(p)
    if m and 45 <= len(p) < 700:
        if not re.match(r"Divis[ãõ]", m.group(0), re.I) or len(p) >= 70:
            return "divisao"
    m = RX_DIV_FRACO.search(p)
    if m and len(p) < 320:
        ini = m.end()
        depois = r.plano
        # conta runs formatados depois do gatilho (usa o R com offsets do plano; markers não contam)
        pos_plano = 0
        runs = 0
        em = False
        for ch, fl in zip(r.s, r.f):
            if MARC_RE.match(ch):
                continue
            if pos_plano >= ini:
                if fl & (IT | BOLD):
                    if not em:
                        runs += 1
                        em = True
                else:
                    em = False
            pos_plano += 1
        if runs >= 2:
            return "divisao"
    # definição
    if RX_DEF_INICIO.match(p):
        return "definicao"
    m = RX_DEF_VERBO.search(p)
    if m and len(p) >= 25 and len(p[:m.start()].split()) <= 7:
        antes = p[:m.start()]
        ult = antes.split()[-1].lower().strip(",.;:") if antes.split() else ""
        if ("," not in antes and " que " not in antes and ";" not in antes
                and ult not in ("não", "nem", "tambem", "também", "só", "já", "ainda", "pois", "logo",
                                "então", "mas", "se", "como", "porque", "é", "são")):
            # há formatação (itálico/negrito) antes do verbo?
            pos_plano = 0
            tem_fmt = False
            for ch, fl in zip(r.s, r.f):
                if MARC_RE.match(ch):
                    continue
                if pos_plano >= m.start():
                    break
                if fl & (IT | BOLD) and not ch.isspace():
                    tem_fmt = True
                    break
                pos_plano += 1
            if tem_fmt:
                depois = p[m.end():].strip()
                verbo = m.group(0)
                if verbo in ("chama-se", "chamam-se", "diz-se", "dizem-se", "denomina-se", "denominam-se",
                             "significa", "entende-se", "define-se"):
                    return "definicao"
                if RX_DEF_ART.match(depois):
                    return "definicao"
    return None


# --- silogismo ---------------------------------------------------------------------------
_FIM_CL = ".;:!?—–-»”)"


def _clausulas(s, palavra):
    pos = []
    for m in re.finditer(r"(?<![\w])" + palavra + r"(?![\w])", s):
        pre = MARC_RE.sub("", s[:m.start()]).rstrip()
        if pre and pre[-1] not in _FIM_CL:
            continue
        resto = MARC_RE.sub("", s[m.end():])
        if palavra == "Logo" and re.match(r"[,\s]*(?:que|depois|após|apos|a seguir|então|antes)\b", resto):
            continue
        if not resto[:1] or resto[0] not in " ,":
            continue
        pos.append((m.start(), m.end()))
    return pos


def _depois(r, ini, fim, ate):
    """R do texto depois do conectivo [ini:fim) até `ate` (vírgula/espaços seguintes caem; marcadores ficam)."""
    s = r.s
    k = fim
    while k < ate and (s[k].isspace() or s[k] == ","):
        k += 1
    pref = [c for c in s[ini:k] if MARC_RE.match(c)]
    out = r[k:ate]
    if pref:
        out = R("".join(pref), bytearray(len(pref))) + out
    return out


def _fim_frase(s, depois_de):
    for c, prox in fronteiras(s):
        if c > depois_de:
            return c, prox
    return len(s), len(s)


def silogismo(r):
    """-> (linhas [(rotulo, R)], consumidos [str], resto R) ou None."""
    s = r.s
    logos = _clausulas(s, "Logo")
    if not logos:
        return None
    oras = _clausulas(s, "Ora")
    l1 = logos[0]
    ora1 = next((o for o in oras if o[1] <= l1[0]), None)
    if ora1 is None:
        premissa = r[:l1[0]].rstrip_chars(" —–-")
        if premissa.vazio() or len(premissa.plano) > 700:
            return None
        linhas = [("Premissa", premissa)]
        consumidos = ["Logo"]
    else:
        maior = r[:ora1[0]].rstrip_chars(" —–-")
        menor = _depois(r, ora1[0], ora1[1], l1[0]).rstrip_chars(" —–-")
        linhas = []
        if not maior.vazio():
            linhas.append(("Maior", maior))
        linhas.append(("Menor", menor))
        consumidos = ["Ora", "Logo"]
    fim_c, prox = _fim_frase(s, l1[1])
    linhas.append(("Conclusão", _depois(r, l1[0], l1[1], fim_c)))
    resto = r[prox:]
    while True:                       # polissilogismo: `Ora … Logo …` logo em seguida
        rs = resto.s
        o, l = _clausulas(rs, "Ora"), _clausulas(rs, "Logo")
        if not o or not l or MARC_RE.sub("", rs[:o[0][0]]).strip():
            break
        lg = next((x for x in l if x[0] > o[0][1]), None)
        if lg is None:
            break
        menor2 = _depois(resto, o[0][0], o[0][1], lg[0]).rstrip_chars(" —–-")
        fim2, prox2 = _fim_frase(rs, lg[1])
        linhas.append(("Menor", menor2))
        linhas.append(("Conclusão", _depois(resto, lg[0], lg[1], fim2)))
        consumidos += ["Ora", "Logo"]
        resto = resto[prox2:]
    return linhas, consumidos, resto


# --- estruturas de slide --------------------------------------------------------------------
class Item:
    __slots__ = ("kind", "r", "rot", "grp")

    def __init__(self, kind, r, rot=None, grp=None):
        self.kind, self.r, self.rot, self.grp = kind, r, rot, grp

    def linhas(self):
        k = self.kind if self.kind in _CPL else "p"
        return max(1, -(-int(len(self.r.plano) * 1.05) // _CPL[k]))

    def peso(self):
        """altura estimada em "caracteres equivalentes" (linhas de parágrafo x UNIDADE)."""
        k = self.kind if self.kind in _CPL else "p"
        extra = _EXTRA[k] + (0.2 if k == "rot" and (self.rot or "").startswith("Conclus") else 0)
        return int((self.linhas() * _LH[k] + extra) * UNIDADE)


class Slide:
    def __init__(self, tipo, titulo="", n=None, corpo=None, consumidos=None, cont=False, continua=False):
        self.tipo, self.titulo, self.n = tipo, titulo, n
        self.corpo = corpo if corpo is not None else []
        self.consumidos = consumidos if consumidos is not None else []
        self.cont, self.continua = cont, continua
        self.titulo_cont = None
        self.ref = ""
        self.pagina = None


def trunc(txt, n=TITULO_MAX):
    txt = " ".join(txt.split())
    if len(txt) <= n:
        return txt
    c = txt[:n].rsplit(" ", 1)[0].rstrip(",;:—-")
    return c + "…"


_GRP = [0]


def novo_grupo():
    _GRP[0] += 1
    return _GRP[0]


def topicos(r):
    """texto corrido -> itens: parágrafo curto ou tópicos (nos ` — ` e nas frases)."""
    r = r.strip()
    if r.vazio():
        return []
    pd = pedacos(r)
    if len(pd) == 1 or (len(r.plano) <= LIMITE_CORRIDO and not any(t for _, t in pd[1:])):
        return [Item("p", r)]
    return [Item("-", x) for x, _ in pd]


def marca_definido(r):
    """primeiro termo em itálico no início da definição passa a negrito (só formatação)."""
    s, f = r.s, bytearray(r.f)
    vis = 0
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if MARC_RE.match(ch):
            i += 1
            continue
        if vis > 60:
            break
        if f[i] & IT:
            j = i
            while j < n and (f[j] & IT or MARC_RE.match(s[j]) or (s[j] == " " and j + 1 < n and f[j + 1] & IT)):
                f[j] = (f[j] & ~IT) | BOLD
                j += 1
            return R(s, f)
        if not ch.isspace():
            vis += 1
        i += 1
    return r


def sem_negrito(r):
    """tira TODO o negrito (o OCR marca palavras soltas do enunciado; a caixa já destaca)."""
    return R(r.s, bytearray(fl & ~BOLD for fl in r.f))


def destaque(r):
    """enunciado em destaque (`!`; quem chama já tirou o negrito), salvo se passar de ENUNC_LINHAS linhas (a caixa encolheria)."""
    it = Item("!", r)
    if it.linhas() > ENUNC_LINHAS:
        return Item("p", r)
    return it


def itens_do_seg(tipo, r, definido=True):
    """corpo (itens) de um segmento de um tipo, a partir do texto."""
    r = r.strip()
    if tipo in ("definicao", "divisao"):
        fr = frases(r)
        if not fr:
            return []
        primeira = marca_definido(sem_negrito(fr[0])) if tipo == "definicao" and definido else sem_negrito(fr[0])
        resto = junta(fr[1:], " ")
        return [destaque(primeira)] + topicos(resto)
    if tipo == "citacao":
        return [Item(">", r)]
    return topicos(r)


class Seg:
    def __init__(self, tipo, itens, consumidos=None):
        self.tipo, self.itens, self.consumidos = tipo, itens, consumidos or []


def segmenta(r, forcado=None, cabeca=False, titulo_def=False):
    """parágrafo (sem marcador/rubrica) -> lista de Seg."""
    r = r.strip()
    mt = re.match(r"^(?:" + M + r")*(?:[—–]+|-(?=\s))\s*", r.s)
    if mt:                                   # travessão solto no início (resto de fragmento): não é palavra
        marc = "".join(c for c in mt.group(0) if MARC_RE.match(c))
        r = R(marc, bytearray(len(marc))) + r[mt.end():]
    if r.vazio():
        return []
    # argumento (maior / Ora menor / Logo conclusão): vale para qualquer tipo, salvo citação/def/div explícitos
    if forcado in (None, "argumento", "tese", "objecao", "resposta", "corolario", "escolio", "observacao"):
        sil = silogismo(r)
        if sil is not None and (forcado is not None or not eh_citacao(r)):
            linhas, cons, resto = sil
            tipo = "argumento" if forcado in (None, "argumento") else forcado
            if forcado == "tese":
                tipo = "argumento"
            g = novo_grupo()
            itens = [Item("rot", x, rot, g + i) for i, (rot, x) in enumerate(linhas)]
            segs = [Seg(tipo, itens, cons)]
            return segs + segmenta(resto, None, False)
    if forcado is not None and forcado != "argumento":
        if forcado == "tese":
            return [Seg("tese", [destaque(sem_negrito(r))])]
        return [Seg(forcado, itens_do_seg(forcado, r))]
    if forcado == "argumento":
        return [Seg("argumento", topicos(r))]
    segs = []
    for fr in frases(r):
        k = tipo_da_frase(fr)
        if titulo_def and not segs and k is None:
            k = "definicao"
        if segs and (k is None or k == segs[-1][0]):
            segs[-1][1].append(fr)
        else:
            segs.append([k, [fr]])
    out = []
    for k, frs in segs:
        tipo = k or ("tese" if cabeca and not out else "texto")
        txt = junta(frs, " ")
        out.append(Seg(tipo, itens_do_seg(tipo, txt)))
        cabeca = False
    return out


# --- marcador de subdivisão ----------------------------------------------------------------
_VAR = {"á": "a", "à": "a", "â": "a", "ã": "a", "aj": "a", "€": "c", "ç": "c", "o": "c", "ó": "c"}
RX_SUB_LETRA = re.compile(r"^(" + M + r")\(?([a-hA-H]|á|à|â|ã|aj|€|ç|o|ó)\s?\)\s*")
RX_SUB_ORD = re.compile(r"^(" + M + r")(\d{1,2})(?:\.º|º|°|\.°)\s+")
RX_SUB_ROM = re.compile(r"^(" + M + r")(I{1,3}|IV|VI{0,3}|IX|X)\.\s+(?=[A-ZÁÉÍÓÚ*«\"])")


def marcador(r, anterior=None):
    """-> (rotulo_normalizado, resto R, texto consumido) ou None."""
    s = r.s
    m = RX_SUB_LETRA.match(s)
    if m:
        raw = m.group(2)
        let = raw.lower() if len(raw) == 1 and raw.lower() in "abcdefgh" else None
        if let is None:
            esperado = chr(ord(anterior) + 1) if anterior else "a"
            if _VAR.get(raw) != esperado:
                return None
            let = esperado
        return f"{let})", r[m.end():], MARC_RE.sub("", m.group(0)).strip()
    m = RX_SUB_ORD.match(s)
    if m:
        return f"{m.group(2)}.º", r[m.end():], MARC_RE.sub("", m.group(0)).strip()
    m = RX_SUB_ROM.match(s)
    if m:
        return f"{m.group(2)}.", r[m.end():], MARC_RE.sub("", m.group(0)).strip()
    return None


def rubrica(r):
    """rubrica de subdivisão: `*Rubrica* — corpo` ou cabeçalho curto `Pharinge. — corpo`.
    -> (rubrica_plana, resto R) ou (None, r)."""
    s, f = r.s, r.f
    i = 0
    while i < len(s) and (MARC_RE.match(s[i]) or s[i].isspace()):
        i += 1
    if i < len(s) and (f[i] & IT):
        j = i
        while j < len(s) and (f[j] & IT or MARC_RE.match(s[j]) or (s[j] == " " and j + 1 < len(s) and f[j + 1] & IT)):
            j += 1
        rub = r[i:j]
        depois = s[j:]
        m = re.match(r"^\s*[.,:;]?\s*[—–-]{1,2}\s+", MARC_RE.sub("", depois)) if depois else None
        if m and len(rub.plano) <= 80:
            k = j
            while k < len(s) and (s[k].isspace() or s[k] in ".,:;—–-" or MARC_RE.match(s[k])):
                k += 1
            pref = [c for c in s[j:k] if MARC_RE.match(c)]
            resto = r[k:]
            if pref:
                resto = R("".join(pref), bytearray(len(pref))) + resto
            return rub.plano.strip().rstrip(".,;:"), resto
    m = _TRAV_RE.search(s)
    if m and m.group(0).strip():
        cab = r[:m.start()].strip().plano.strip().rstrip(".")
        if 0 < len(cab) <= 40 and len(cab.split()) <= 4 and not re.search(r"[.!?;:]", cab):
            resto = r[m.end():]
            pref = [c for c in s[:m.end()] if MARC_RE.match(c)]
            if pref:
                resto = R("".join(pref), bytearray(len(pref))) + resto
            return cab, resto
    return None, r


# =========================================================================== TEI -> eventos
class Par:
    __slots__ = ("r", "tipo", "pag", "notas", "label")

    def __init__(self, r, tipo, pag, notas, label):
        self.r, self.tipo, self.pag, self.notas, self.label = r, tipo, pag, notas, label


class Sec:
    __slots__ = ("nivel", "rotulo", "titulo", "pag", "id")

    def __init__(self, nivel, rotulo, titulo, pag, id_):
        self.nivel, self.rotulo, self.titulo, self.pag, self.id = nivel, rotulo, titulo, pag, id_


class Ini:
    __slots__ = ("n", "id")

    def __init__(self, n, id_):
        self.n, self.id = n, id_


class Conv:
    def __init__(self, notas=False):
        self.notas = notas
        self.eventos = []
        self.pagina = None
        self.tabela = []          # índice do marcador -> página (str)
        self.pend = []            # marcadores aguardando o próximo parágrafo
        self.pagina_inicial = None

    def marca(self, pag):
        self.tabela.append(pag)
        return chr(0xF0000 + (len(self.tabela) - 1) % 0xFFFE)

    # ---- inline
    def rico(self, e, notas_out=None, em_nota=False):
        s, f = [], bytearray()
        colar = [False]

        def add(txt, fl):
            if not txt:
                return
            txt = _CTRL_RE.sub("", txt)
            if colar[0]:
                colar[0] = False
                if s and s[-1].endswith(" ") and re.match(r"[.,;:!?)]", txt):
                    s[-1] = s[-1][:-1]
                    del f[-1]
            s.append(txt)
            f.extend(bytes([fl]) * len(txt))

        def ultimo():
            return s[-1][-1] if s and s[-1] else ""

        def pb(c):
            if em_nota:
                return
            pag = c.get("n")
            self.pagina = pag
            m = self.marca(pag)
            u = ultimo()
            if u and not u.isspace() and u != "-" and not MARC_RE.match(u):
                s.append(" ")
                f.append(0)
            s.append(m)
            f.append(0)

        def walk(x, fl):
            add(x.text, fl)
            for c in x:
                if not isinstance(c.tag, str):
                    add(c.tail, fl)
                    continue
                n = ln(c)
                if n == "pb":
                    pb(c)
                elif n == "fw":
                    pass
                elif n == "note":
                    if notas_out is not None and not em_nota:
                        notas_out.append(c)
                    colar[0] = True
                elif n == "hi":
                    walk(c, fl | REND.get((c.get("rend") or "").split()[0] if c.get("rend") else "", 0))
                elif n == "quote" and c.get("type") in ("direta", "mencao"):
                    add("«", fl)                # o texto da citação vem sem aspas (web/obra/esquema.py)
                    walk(c, fl)
                    add("»", fl)
                elif n in ("foreign", "emph", "title", "quote"):
                    walk(c, fl | IT if n != "quote" else fl)
                elif n == "lb":
                    add(" ", fl)
                else:
                    walk(c, fl)
                add(c.tail, fl)

        walk(e, 0)
        return normaliza(R("".join(s), f))

    def texto_simples(self, e):
        t = "".join(x for x in e.itertext() if x)
        return " ".join(MARC_RE.sub("", t).split())

    # ---- estrutura
    def filho(self, c):
        if not isinstance(c.tag, str):
            return
        n = ln(c)
        if n == "div":
            self.div(c, True)
        elif n == "pb":
            self.pagina = c.get("n")
            self.pend.append(self.marca(self.pagina))
        elif n in ("fw", "head", "argument", "note", "milestone", "teiHeader"):
            return
        elif n == "p":
            self.par(c)
        elif any(isinstance(x.tag, str) and ln(x) == "p" for x in c.iter()):
            for cc in c:
                self.filho(cc)
        else:
            self.par(c)

    def par(self, p):
        pag0 = self.pagina
        ns = [] if self.notas else None
        r = limpa_lixo(self.rico(p, ns))
        if self.pend:
            r = R("".join(self.pend), bytearray(len(self.pend))) + r if not r.vazio() else r
            self.pend = []
        if r.vazio():
            return
        tipo = P_TIPOS.get(p.get("type") or "")
        label = len(p) > 0 and isinstance(p[0].tag, str) and ln(p[0]) == "label" and not (p.text or "").strip()
        notas = []
        for nt in ns or []:
            nr = limpa_lixo(self.rico(nt, None, em_nota=True))
            if not nr.vazio():
                notas.append(nr)
        self.eventos.append(Par(r, tipo, pag0, notas, label))

    def div(self, d, emite):
        tipo = d.get("type") or ""
        if tipo in NIVEIS_SEC:
            if emite:
                rot = " ".join(self.texto_simples(h) for h in d if isinstance(h.tag, str) and ln(h) == "head"
                               and h.get("type") == "rotulo")
                tit = " ".join(self.texto_simples(h) for h in d if isinstance(h.tag, str) and ln(h) == "head"
                               and h.get("type") != "rotulo")
                self.eventos.append(Sec(tipo, rot, tit, self.pagina, d.get(XML_ID)))
        elif tipo == "tese":
            self.eventos.append(Ini(d.get("n"), d.get(XML_ID)))
        for c in d:
            self.filho(c)


def _carrega(xml):
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    try:
        return etree.fromstring(xml, etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        return etree.fromstring(xml, etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True,
                                                     recover=True))


def _int(x):
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


def _titulo_div(conv, d):
    rot = " ".join(conv.texto_simples(h) for h in d if isinstance(h.tag, str) and ln(h) == "head"
                   and h.get("type") == "rotulo")
    tit = " ".join(conv.texto_simples(h) for h in d if isinstance(h.tag, str) and ln(h) == "head"
                   and h.get("type") != "rotulo")
    return " ".join(x for x in (rot, tit) if x).strip()


def eventos_do_tei(xml, seletor_id=None, notas=False):
    raiz = _carrega(xml)
    conv = Conv(notas)
    corpo = None
    for e in raiz.iter():
        if isinstance(e.tag, str) and ln(e) == "body":
            corpo = e
            break
    base = corpo if corpo is not None else raiz
    titulo_raiz = None
    if seletor_id:
        alvo = None
        for e in base.iter():
            if isinstance(e.tag, str) and e.get(XML_ID) == seletor_id:
                alvo = e
                break
        if alvo is None:
            for e in raiz.iter():
                if isinstance(e.tag, str) and e.get(XML_ID) == seletor_id:
                    alvo = e
                    break
        if alvo is None:
            raise ValueError(f"xml:id {seletor_id!r} não encontrado no TEI")
        # página corrente na entrada do alvo: último pb antes dele
        for e in base.iter():
            if e is alvo:
                break
            if isinstance(e.tag, str) and ln(e) == "pb" and not any(
                    ln(a) == "note" for a in e.iterancestors() if isinstance(a.tag, str)):
                conv.pagina = e.get("n")
        if ln(alvo) == "div":
            titulo_raiz = _titulo_div(conv, alvo) or None
            if alvo.get("type") == "tese":
                titulo_raiz = titulo_raiz or (f"Tese {alvo.get('n')}" if alvo.get("n") else None)
            conv.pagina_inicial = conv.pagina
            conv.div(alvo, False)
        elif ln(alvo) == "p":
            conv.pagina_inicial = conv.pagina
            conv.par(alvo)
        else:
            conv.pagina_inicial = conv.pagina
            for c in alvo:
                conv.filho(c)
    else:
        for c in base:
            conv.filho(c)
        t = None
        for e in raiz.iter():
            if isinstance(e.tag, str) and ln(e) == "title":
                t = conv.texto_simples(e)
                break
        titulo_raiz = t or None
    return conv, titulo_raiz


# =========================================================================== eventos -> slides
RX_NUM = re.compile(r"^(" + M + r")\s*(\d{1,3})\s*[.,](?![º°\d])\s*(?=\S)")


def _cabeca_numerada(r):
    m = RX_NUM.match(r.s)
    if not m:
        return None
    return int(m.group(2))


def reflui(pars):
    """junta fragmentos de linha do OCR: `p` que não termina em pontuação seguido de `p` em minúscula."""
    out = []
    for p in pars:
        if out:
            a = out[-1]
            ta = a.r.plano.rstrip()
            tb = p.r.plano.lstrip()
            if a.tipo is None and p.tipo is None and ta and tb:
                termina = ta[-1] in ".!?:;»”\"" or ta.endswith(".)")
                hifen = ta.endswith("-") and ta[-2:-1].isalpha()
                inicia_min = (tb[0].islower() or bool(re.match(r"^\d{1,4}\s+[a-zà-ú]", tb))) \
                    and not re.match(r"^[a-h]\)", tb)
                continua_arg = len(out) >= 2 and bool(re.match(r"^(?:Logo|Ora)\b(?!\s+que\b)", tb))
                if hifen or (not termina and inicia_min) or continua_arg:
                    sep = "" if hifen else " "
                    a.r = junta([a.r, p.r], sep)
                    a.notas = a.notas + p.notas
                    continue
        out.append(Par(p.r, p.tipo, p.pag, list(p.notas), p.label))
    return out


def _negrito_apos_numero(r):
    m = RX_NUM.match(r.s)
    if not m:
        return False
    k = m.end()
    while k < len(r.s) and (r.s[k].isspace() or MARC_RE.match(r.s[k])):
        k += 1
    return k < len(r.s) and bool(r.f[k] & BOLD)


def _agrupa(eventos):
    """-> lista de ('sec', Sec) | ('grupo', n, [Par])."""
    out = []
    grupo = None
    ant_n = None

    def fecha():
        nonlocal grupo
        if grupo is not None and grupo[1:] and grupo[2]:
            out.append(("grupo", grupo[1], reflui(grupo[2])))
        grupo = None

    for ev in eventos:
        if isinstance(ev, Sec):
            fecha()
            out.append(("sec", ev))
        elif isinstance(ev, Ini):
            fecha()
            grupo = ["g", _int(ev.n), []]
            if grupo[1] is not None:
                ant_n = grupo[1]
        else:
            num = _cabeca_numerada(ev.r)
            if grupo is None:
                grupo = ["g", num, []]
                if num is not None:
                    ant_n = num
            elif not grupo[2]:
                if grupo[1] is None and num is not None:
                    grupo[1] = num
                    ant_n = num
            elif num is not None and ant_n is not None and (
                    _negrito_apos_numero(ev.r) or (
                    num == ant_n + 1 or (ant_n < num <= ant_n + 3)
                    or (ant_n < num <= ant_n + 60 and (ev.label or ev.tipo == "enunciado")))):
                fecha()
                grupo = ["g", num, []]
                ant_n = num
            grupo[2].append(ev)
    fecha()
    return out


def _consome_numero(r):
    m = RX_NUM.match(r.s)
    if not m:
        return r, None
    pref = [c for c in m.group(1)]
    resto = r[m.end():]
    if pref:
        resto = R("".join(pref), bytearray(len(pref))) + resto
    return resto, m.group(2) + "."


_TIT_FIM = re.compile(r"[.!?:]\s*$")


def _titulo_estilo(c):
    """conteúdo (sem o número) -> (titulo R, resto R) se for `**Título.** — corpo`, senão None."""
    s, f = c.s, c.f
    i = 0
    while i < len(s) and (MARC_RE.match(s[i]) or s[i].isspace()):
        i += 1
    if i >= len(s) or not (f[i] & BOLD):
        return None
    m = _TRAV_RE.search(s, i)
    if not m:
        return None
    t = c[i:m.start()].strip()
    pl = t.plano
    if len(pl) > 140 or len(pl) < 3:
        return None
    # não pode haver fim de frase no meio do título
    if re.search(r"[.!?]\s+\S", MARC_RE.sub("", pl)) and len(frases(t)) > 1:
        return None
    resto = c[m.end():]
    pref = [ch for ch in s[:i] + s[m.start():m.end()] if MARC_RE.match(ch)]
    if pref:
        resto = R("".join(pref), bytearray(len(pref))) + resto
    return t, resto


def _base_titulo(n, titulo):
    if n is not None and titulo:
        return f"{n}. {titulo}"
    if n is not None:
        return f"{n}."
    return titulo


TITULO_DERIVADO = 60


def _titulo_sub(base, marc, rub):
    """título curto de subdivisão: `base — a) rubrica`, no máximo ~60 caracteres."""
    rub = trunc(rub, 30) if rub else ""
    suf = marc + (f" {rub}" if rub else "")
    if not base:
        return suf
    sobra = max(18, TITULO_DERIVADO - len(" — ") - len(suf))
    return f"{trunc(base, sobra)} — {suf}"


def slides_do_grupo(n, pars, titulo_ctx, usar_notas=False):
    """-> lista de Slide (sem paginar)."""
    slides = []
    base = f"n. {n}" if n is not None else trunc(titulo_ctx or "", TITULO_DERIVADO)
    base_full = base
    cons_base = []
    primeira_letra = None
    if not pars:
        return slides
    i0 = 0
    head_slides = []
    ult_marc_letra = None
    ref_n = str(n) if n is not None else None

    def novo(tipo, titulo, itens, cons=None):
        sl = Slide(tipo, titulo, ref_n, itens, cons or [])
        return sl

    # ---- cabeça
    if n is not None:
        p0 = pars[0]
        c, numtxt = _consome_numero(p0.r)
        cons = [numtxt] if numtxt else []
        ts = _titulo_estilo(c) if p0.tipo != "enunciado" else None
        if ts is not None:
            tit_r, resto = ts
            tit_pl = tit_r.plano.strip().rstrip(".")
            base = base_full = _base_titulo(n, trunc(tit_pl, 90))
            base = trunc(base, TITULO_DERIVADO)
            cons += [tit_r.plano.strip()]
            segs = segmenta(resto, p0.tipo if p0.tipo not in (None, "enunciado") else None, cabeca=True,
                            titulo_def=bool(RX_TIT_DEF.match(tit_pl)))
            for sg in segs:
                head_slides.append(novo(sg.tipo, base_full, sg.itens, sg.consumidos))
            for hs_ in head_slides:
                hs_.titulo_cont = base
            if head_slides:
                head_slides[0].consumidos = cons + head_slides[0].consumidos
            elif len(pars) > 1:
                cons_base = cons          # o título vive nos slides seguintes; consumidos vão no primeiro
            else:
                head_slides.append(novo("tese", base, [], cons))
        else:
            fr = frases(c)
            if p0.tipo in P_TIPOS and p0.tipo != "enunciado":
                # tipo explícito no parágrafo da tese: o texto inteiro vai para o tipo pedido
                base_full = _base_titulo(n, trunc(c.plano.strip(), 90))
                segs = segmenta(c, p0.tipo, cabeca=True)
                for sg in segs:
                    head_slides.append(novo(sg.tipo, base_full, sg.itens, sg.consumidos))
                    head_slides[-1].titulo_cont = base
                if head_slides:
                    head_slides[0].consumidos = cons + head_slides[0].consumidos
            else:
                if fr:
                    enun = fr[0]
                    resto = junta(fr[1:], " ")
                else:
                    enun, resto = c, R()
                enun_pl = enun.plano.strip()
                if len(frases(c)) > 1 and len(c.plano) <= 330 and p0.tipo == "enunciado":
                    enun, resto = c, R()
                base_full = _base_titulo(n, trunc(enun_pl.rstrip("."), 90))
                itens = [destaque(sem_negrito(enun))]
                extra = segmenta(resto, None, cabeca=False) if not resto.vazio() else []
                # o que sobra e é `texto` vai para o slide da tese
                while extra and extra[0].tipo == "texto":
                    itens += extra[0].itens
                    extra = extra[1:]
                hs = novo("tese", base_full, itens, cons)
                hs.titulo_cont = base
                head_slides.append(hs)
                for sg in extra:
                    head_slides.append(novo(sg.tipo, base, sg.itens, sg.consumidos))
        if p0.notas and usar_notas:
            head_slides += _slides_notas(p0.notas, base, ref_n)
        slides += head_slides
        i0 = 1
    elif titulo_ctx:
        base = titulo_ctx
    # ---- demais parágrafos
    pend_juncao = None
    pend_sub = None
    for p in pars[i0:]:
        c = p.r
        cons = list(cons_base)
        cons_base = []
        # parágrafo-lixo (quase sem letras): cola ao anterior em vez de virar slide
        letras = sum(ch.isalnum() for ch in c.plano)
        if letras < 4 and slides and slides[-1].corpo:
            ult = slides[-1].corpo[-1]
            ult.r = junta([ult.r, c], " ")
            continue
        mk = marcador(c, ult_marc_letra) if pend_sub is None else None
        titulo = base
        if pend_sub is not None:                       # cabeçalho curto `b) Pharinge.` do parágrafo anterior
            marc, rub = pend_sub
            pend_sub = None
            titulo = _titulo_sub(base, marc, rub)
            mk = (marc, c, "")
        elif mk is not None:
            marc, resto, consumido = mk
            ult_marc_letra = marc[0] if marc.endswith(")") else ult_marc_letra
            cons.append(consumido)
            rub, resto2 = rubrica(resto)
            if rub:
                cons.append(rub)
                resto = resto2
            elif (len(resto.plano.strip()) <= 40 and len(resto.plano.split()) <= 4 and not resto.vazio()
                  and p is not pars[-1] and marcador(pars[pars.index(p) + 1].r, marc[0]) is None
                  and pars[pars.index(p) + 1].tipo is None):
                pend_sub = (marc, resto.plano.strip().rstrip(".,;:"))
                cons.append(resto.plano.strip())
                slides_cons = cons
                if slides:
                    slides[-1].consumidos += cons
                    cons = []
                else:
                    pend_juncao = (pend_juncao or []) + cons
                    cons = []
                continue
            titulo = _titulo_sub(base, marc, rub)
            c = resto
        segs = segmenta(c, p.tipo, cabeca=False)
        novos = []
        for sg in segs:
            novos.append(novo(sg.tipo, titulo, sg.itens, sg.consumidos))
        if novos:
            novos[0].consumidos = cons + novos[0].consumidos
        elif cons:
            if slides:
                slides[-1].consumidos += cons
            else:
                pend_juncao = (pend_juncao or []) + cons
        if pend_juncao and novos:
            novos[0].consumidos = pend_juncao + novos[0].consumidos
            pend_juncao = None
        # junta `texto` com `texto` quando nenhum dos dois traz marcador próprio
        for sl in novos:
            if (slides and mk is None and sl.tipo == "texto" and slides[-1].tipo == "texto"
                    and slides[-1].titulo == sl.titulo and not getattr(slides[-1], "_marc", False)):
                slides[-1].corpo += sl.corpo
                slides[-1].consumidos += sl.consumidos
            else:
                if mk is not None:
                    sl._marc = True
                slides.append(sl)
        if p.notas and usar_notas:
            slides += _slides_notas(p.notas, titulo, ref_n)
    if pend_juncao:
        if slides:
            slides[-1].consumidos += pend_juncao
        else:
            slides.append(Slide("texto", base, ref_n, [], pend_juncao))
    return slides


def _slides_notas(notas, base, ref_n):
    out = []
    for k, nr in enumerate(notas, 1):
        tipo = "citacao" if eh_citacao(nr) else "observacao"
        itens = [Item(">", nr)] if tipo == "citacao" else topicos(nr)
        out.append(Slide(tipo, f"{trunc(base, 60)} — nota {k}" if base else f"Nota {k}", ref_n, itens, []))
    return out


# --- paginação --------------------------------------------------------------------------------
def _expande(it):
    if it.kind in ("p", ">", "rot"):
        fr = frases(it.r)
        if len(fr) > 1:
            g = it.grp if it.grp is not None else novo_grupo()
            return [Item(it.kind, x, it.rot, g) for x in fr]
        it.grp = it.grp if it.grp is not None else novo_grupo()
    return [it]


def _titulo_cont(sl):
    base = sl.titulo_cont or trunc(sl.titulo, 60)
    base = base[:-len(" (cont.)")] if base.endswith(" (cont.)") else base
    return (base + " (cont.)") if base else "(cont.)"


def _capacidade(itens, titulo, max_car):
    """capacidade do slide em caracteres equivalentes (escala = max_car / MAX_CAR)."""
    f = max_car / MAX_CAR
    if any(i.kind == "rot" for i in itens):
        cap = CAP_ROT1 if len(titulo) <= TITULO_1LINHA else CAP_ROT2
    else:
        cap = CAP_P
    return cap * f * UNIDADE


def pagina_slide(sl, max_car):
    """parte um slide em vários, ao longo de fronteiras de frase; o que couber num quadro fica num quadro."""
    if sl.tipo in ("capa", "secao"):
        return [sl]
    exp = []
    for it in sl.corpo:
        exp.extend(_expande(it))
    # título das continuações pode ter 2 linhas: capacidade calculada com ele (pior caso)
    tit_cont = _titulo_cont(sl)
    cap = _capacidade(exp, tit_cont if len(exp) and len(tit_cont) > TITULO_1LINHA else sl.titulo, max_car)
    reserva = RESERVA_L * (max_car / MAX_CAR) * UNIDADE
    paginas = [[]]
    soma = 0
    if sum(x.peso() for x in exp) <= cap:            # cabe num quadro só
        paginas = [list(exp)]
    else:
        for it in exp:
            w = it.peso()
            limite = cap if it is exp[-1] else cap - reserva
            if paginas[-1] and soma + w > limite:
                ult = paginas[-1]
                mover = []
                while len(ult) > 1 and ult[-1].kind == "!":
                    mover.insert(0, ult.pop())
                # a conclusão não fica sozinha: leva consigo o último item da página anterior
                if it.kind == "rot" and (it.rot or "").startswith("Conclus") and len(ult) > 1 and not mover:
                    mover.insert(0, ult.pop())
                paginas.append(mover)
                soma = sum(x.peso() for x in mover)
            paginas[-1].append(it)
            soma += w
    out = []
    ant_grp = None
    for k, itens in enumerate(paginas):
        fund = []
        for it in itens:                              # reagrupa os pedaços do mesmo item
            if fund and fund[-1].grp is not None and fund[-1].grp == it.grp and fund[-1].kind == it.kind \
                    and it.kind in ("p", ">", "rot"):
                fund[-1] = Item(it.kind, junta([fund[-1].r, it.r], " "), fund[-1].rot, it.grp)
            else:
                fund.append(Item(it.kind, it.r, it.rot, it.grp))
        if k > 0 and fund and fund[0].kind == "rot" and ant_grp is not None and fund[0].grp == ant_grp \
                and "(cont.)" not in (fund[0].rot or ""):
            fund[0].rot = f"{fund[0].rot} (cont.)"
        ant_grp = fund[-1].grp if fund else None
        tit = sl.titulo if k == 0 else tit_cont
        cabe_continua = sum(x.peso() for x in fund) <= cap - reserva   # senão a linha (continua) transborda
        ns = Slide(sl.tipo, tit, sl.n, fund, sl.consumidos if k == 0 else [], sl.cont or k > 0,
                   k < len(paginas) - 1 and cabe_continua)
        ns.titulo_cont = sl.titulo_cont
        out.append(ns)
    return out


# --- finalização: página de cada slide e serialização -----------------------------------------------
def _varre(r, cur, tabela):
    s = r.s
    mv = VISIVEL_RE.search(s)
    p0 = mv.start() if mv else None
    pag0 = None
    for m in MARC_RE.finditer(s):
        if p0 is not None and pag0 is None and m.start() > p0:
            pag0 = cur
        cur = tabela[(ord(m.group(0)) - 0xF0000)]
    if p0 is not None and pag0 is None:
        pag0 = cur
    return cur, pag0


def _ref(n, pag):
    partes = []
    if n is not None:
        partes.append(f"n. {n}")
    if pag:
        partes.append(f"p. {pag}")
    return " · ".join(partes)


def _escreve_item(it):
    t = r_para_fonte(it.r)
    if it.kind == "p":
        return linha_paragrafo(t)
    if it.kind == "!":
        return "! " + t
    if it.kind == "-":
        return "- " + t
    if it.kind == "--":
        return "  - " + t
    if it.kind == ">":
        return "> " + t
    return f"{it.rot}:: {t}"


def _escreve_slides(slides):
    linhas = []
    for sl in slides:
        linhas.append(f"=== {sl.tipo}")
        if sl.titulo:
            linhas.append("# " + esc_inline(" ".join(sl.titulo.split())))
        if sl.ref:
            linhas.append("@ " + esc_inline(sl.ref))
        prev_k = None
        for it in sl.corpo:
            if it.r.vazio():
                continue
            if prev_k is not None and (it.kind == "p" or prev_k == "p"):
                linhas.append("")
            linhas.append(_escreve_item(it))
            prev_k = it.kind
        if sl.continua:
            linhas.append("+continua")
        linhas.append("")
    return "\n".join(linhas)


CABECALHO = """% Fonte dos slides — gerada por tools/gera_slides.py; edite à vontade (não escreva LaTeX: tudo é texto).
% Um slide começa em "=== tipo" (capa secao tese definicao divisao argumento objecao resposta corolario
% escolio observacao citacao texto). Depois, opcionais: "# título" e "@ referência".
% Corpo: linha em branco separa parágrafos; "! texto" enunciado em destaque; "- item" tópico ("  - sub" aninha);
% "> texto" citação; "Rótulo:: texto" linha rotulada (Maior::, Menor::, Conclusão::); "+continua" = segue no próximo.
% Inline: *itálico*  **negrito**  ^versalete^ ; use \\* \\^ \\\\ para os caracteres literais.
% Linha de parágrafo que comece por - ! > # @ % = + (ou pareça "Rótulo::") leva um "\\" na frente.
% Linhas começadas por % são comentários.
"""


def _constroi(xml, titulo=None, seletor_id=None, pagina_ini=None, pagina_fim=None, max_car=MAX_CAR,
              notas=False):
    conv, titulo_raiz = eventos_do_tei(xml, seletor_id, notas)
    pagina_inicial = conv.pagina_inicial
    evs = conv.eventos
    if pagina_ini is not None or pagina_fim is not None:
        def dentro(pag):
            v = _int(pag)
            if v is None:
                return False
            return (pagina_ini is None or v >= pagina_ini) and (pagina_fim is None or v <= pagina_fim)
        manter = [isinstance(e, Par) and dentro(e.pag) for e in evs]
        keep = []
        for i, e in enumerate(evs):
            if isinstance(e, Par):
                keep.append(manter[i])
            elif isinstance(e, Sec):
                prox = False
                for j in range(i + 1, len(evs)):
                    if isinstance(evs[j], Sec):
                        break
                    if manter[j]:
                        prox = True
                        break
                keep.append(prox or dentro(e.pag))
            else:  # Ini: guarda se vier parágrafo mantido logo depois
                prox = False
                for j in range(i + 1, len(evs)):
                    if isinstance(evs[j], (Sec, Ini)):
                        break
                    if manter[j]:
                        prox = True
                        break
                keep.append(prox)
        evs = [e for e, k in zip(evs, keep) if k]
    paginas = [e.pag for e in evs if isinstance(e, Par) and e.pag]
    nums = [v for v in (_int(p) for p in paginas) if v is not None]
    if nums:
        ref_capa = f"p. {min(nums)}" if min(nums) == max(nums) else f"pp. {min(nums)}–{max(nums)}"
    else:
        ref_capa = ""
    tit_capa = titulo or titulo_raiz or OBRA
    slides = [Slide("capa", tit_capa, None, [Item("p", r_de(f"{OBRA} — {AUTOR}"))], [])]
    slides[0].ref = ref_capa
    slides[0].pagina = None
    titulo_ctx = None
    for item in _agrupa(evs):
        if item[0] == "sec":
            sc = item[1]
            rot = sc.rotulo.strip()
            tit = sc.titulo.strip()
            if sum(ch.isalpha() for ch in tit) < 3:
                tit = ""
            if sum(ch.isalpha() for ch in rot) < 3:
                rot = ""
            if not (rot or tit):
                continue
            titulo_ctx = tit or rot
            slides.append(Slide("secao", tit or rot, None, [Item("p", r_de(rot))] if (rot and tit) else [], []))
            continue
        _, n, pars = item
        sl = slides_do_grupo(n, pars, titulo_ctx, notas)
        for s in sl:
            slides.extend(pagina_slide(s, max_car))
    # página/ref de cada slide
    cur = conv.tabela[0] if False else None
    pag_cursor = pagina_inicial or next((e.pag for e in evs if isinstance(e, Par) and e.pag), None)
    for sl in slides:
        if sl.tipo in ("capa", "secao"):
            continue
        primeira = None
        for it in sl.corpo:
            pag_cursor, p0 = _varre(it.r, pag_cursor, conv.tabela)
            if primeira is None and p0 is not None:
                primeira = p0
        sl.pagina = primeira if primeira is not None else pag_cursor
        sl.ref = _ref(sl.n, sl.pagina)
    return slides, conv


def tei_para_fonte(xml, *, titulo=None, seletor_id=None, pagina_ini=None, pagina_fim=None,
                   max_car=MAX_CAR, notas=False):
    """TEI (str|bytes) -> fonte dos slides (.slides.txt). Determinística."""
    slides, _ = _constroi(xml, titulo, seletor_id, pagina_ini, pagina_fim, max_car, notas)
    return CABECALHO + "\n" + _escreve_slides(slides)


# =========================================================================== CLI
def _le(caminho):
    if str(caminho) == "-":
        return sys.stdin.buffer.read()
    return Path(caminho).read_bytes()


def _escreve(saida, texto):
    if saida in (None, "-"):
        sys.stdout.write(texto)
    else:
        Path(saida).parent.mkdir(parents=True, exist_ok=True)
        Path(saida).write_text(texto, encoding="utf-8")


def _opts_tei(a):
    return dict(titulo=a.titulo, seletor_id=a.id, pagina_ini=a.de, pagina_fim=a.ate, max_car=a.max_car,
                notas=a.notas)


def _eh_xml(caminho, dados):
    return str(caminho).lower().endswith(".xml") or dados.lstrip()[:1] == b"<"


def _tabela_resumo(fonte):
    slides, _ = _parse(fonte)
    c = Counter(s["tipo"] for s in slides)
    total = len(slides)
    linhas = [f"{'tipo':<12}{'slides':>8}{'%':>8}"]
    for t in TIPOS:
        if c[t]:
            linhas.append(f"{t:<12}{c[t]:>8}{100 * c[t] / total:>7.1f}%")
    linhas.append(f"{'total':<12}{total:>8}")
    corpo = total - c["capa"] - c["secao"]
    if corpo:
        linhas.append(f"fração 'texto' entre os slides de conteúdo: {100 * c['texto'] / corpo:.1f}%")
    return "\n".join(linhas)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def comum(p):
        p.add_argument("--id", help="xml:id do div (ou elemento) a usar")
        p.add_argument("-f", "--de", type=int, help="primeira página impressa")
        p.add_argument("-l", "--ate", type=int, help="última página impressa")
        p.add_argument("--titulo", help="título da capa")
        p.add_argument("--max-car", type=int, default=MAX_CAR, help=f"orçamento de caracteres por slide ({MAX_CAR})")
        p.add_argument("--notas", action="store_true", help="notas de rodapé viram slides observacao/citacao")

    p = sub.add_parser("base", help="TEI -> fonte")
    p.add_argument("entrada")
    p.add_argument("-o", "--saida")
    comum(p)
    p = sub.add_parser("tex", help="fonte -> .tex")
    p.add_argument("entrada")
    p.add_argument("-o", "--saida")
    p.add_argument("--trecho")
    p = sub.add_parser("pdf", help="fonte ou TEI -> PDF")
    p.add_argument("entrada")
    p.add_argument("-o", "--saida")
    p.add_argument("--timeout", type=int, default=180)
    comum(p)
    p = sub.add_parser("valida", help="valida a fonte")
    p.add_argument("entrada")
    p = sub.add_parser("resumo", help="slides por tipo")
    p.add_argument("entrada")
    comum(p)
    a = ap.parse_args(argv)

    try:
        if a.cmd == "base":
            _escreve(a.saida, tei_para_fonte(_le(a.entrada), **_opts_tei(a)))
        elif a.cmd == "tex":
            _escreve(a.saida, fonte_para_tex(_le(a.entrada).decode("utf-8", "replace"), trecho=a.trecho))
        elif a.cmd == "pdf":
            dados = _le(a.entrada)
            fonte = tei_para_fonte(dados, **_opts_tei(a)) if _eh_xml(a.entrada, dados) \
                else dados.decode("utf-8", "replace")
            saida = a.saida or (re.sub(r"(\.slides)?\.(txt|xml)$", "", str(a.entrada)) + ".slides.pdf")
            compilar(fonte_para_tex(fonte), saida, timeout=a.timeout)
            print(saida, file=sys.stderr)
        elif a.cmd == "valida":
            msgs = validar(_le(a.entrada).decode("utf-8", "replace"))
            for m in msgs:
                print(m)
            return 1 if msgs else 0
        elif a.cmd == "resumo":
            print(_tabela_resumo(tei_para_fonte(_le(a.entrada), **_opts_tei(a))))
    except ErroSlides as e:
        print(f"erro: {e.mensagem}", file=sys.stderr)
        if e.log_resumido:
            print(e.log_resumido, file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
