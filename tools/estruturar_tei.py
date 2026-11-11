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

Formatacao: se existe <id>.fmt.tsv ao lado do <id>.tsv (tools/formatacao.py: italico, versalete e
negrito medidos na imagem), cada palavra marcada vira <hi rend="it|sc|bold">.  A marca viaja como
caractere de uso privado (ABRE/FECHA) so no texto dos paragrafos (Linha.marc); as heuristicas de
estrutura continuam lendo o texto limpo (Linha.texto) e um passe final (aplica_marcas) troca os
marcadores por elementos.  Titulos, <fw>, <label> e enunciado da tese ficam sem marca.
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
# chamada de nota no corpo: o OCR le "(1)" como "(l)", "(|)", "(!)" e, no vol. 1, "(*)" / "(?)"
CHAMADA = re.compile(r"\(\s*(\d{1,2}|[lI|!*?])\s*\)")
# inicio de nota; ate 3 caracteres de sujeira antes (o OCR le ". (1)", "| (2)", "' (1)"; no vol. 1 o filete vira "- (1)")
NOTA = re.compile(r"^[.,:;'‘’|!\s\-–—]{0,3}\(\s*(\d{1,2}|[lI|])\s*\)\s*")
# marcas de formatacao no texto (uso privado): abre / fecha, por estilo
ABRE = {"it": "\ue010", "sc": "\ue011", "bold": "\ue012"}
FECHA = {"it": "\ue020", "sc": "\ue021", "bold": "\ue022"}
REND = {**{v: k for k, v in ABRE.items()}, **{v: k for k, v in FECHA.items()}}
MARCA = re.compile("[\ue010-\ue012\ue020-\ue022]")
M_ = "[\ue010-\ue012\ue020-\ue022]*"            # marcas opcionais num regex
NUCLEO_PAL = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ](?:.*[A-Za-zÀ-ÖØ-öø-ÿ])?")
FIM_FRASE = re.compile(r"[.!?:;»”]\s*$")
ORDINAIS = {"PRIMEIRO", "PRIMEIRA", "SEGUNDO", "SEGUNDA", "TERCEIRO", "TERCEIRA", "QUARTO",
            "QUARTA", "QUINTO", "QUINTA", "SEXTO", "SEXTA", "SETIMO", "SETIMA", "OITAVO",
            "OITAVA", "NONO", "NONA", "DECIMO", "DECIMA", "UNICO", "UNICA", "PRELIMINAR"}
ROMANO = re.compile(r"^[IVXLC1l|]{1,6}$")
NIVEL = {"parte": 1, "seccao": 2, "capitulo": 3, "artigo": 4}


def num_chamada(g):
    """numero que o glifo representa: digitos, "l I | !" = 1, "* ?" = desconhecido (None)."""
    if g.isdigit():
        return g
    return "1" if g in "lI|!" else None


def T(n):
    return f"{{{TEI}}}{n}"


# ------------------------------------------------------------------ leitura do .tsv
class Linha:
    __slots__ = ("x0", "y0", "x1", "y1", "texto", "h", "conf", "marc")

    def __init__(self, x0, y0, x1, y1, texto, h=None, conf=100.0, marc=None):
        self.x0, self.y0, self.x1, self.y1, self.texto, self.h, self.conf = x0, y0, x1, y1, texto, h, conf
        self.marc = texto if marc is None else marc     # texto com marcas de formatacao


def sem_marcas(s):
    return MARCA.sub("", s) if s else s


def marca_palavra(t, rend):
    """envolve o nucleo (1a a ultima letra) da palavra; pontuacao e chamada "(n)" ficam fora."""
    if rend not in ABRE:
        return t
    c = CHAMADA.search(t)                 # "mesma.(I)": a chamada (lida como letra) fica fora
    if c:
        return marca_palavra(t[:c.start()], rend) + c.group() + marca_palavra(t[c.end():], rend)
    m = NUCLEO_PAL.search(t)
    if not m:
        return t
    return t[:m.start()] + ABRE[rend] + m.group() + FECHA[rend] + t[m.end():]


_L = "A-Za-zÀ-ÖØ-öø-ÿ"
_FECHA_NO_MEIO = re.compile(f"(?<=[{_L}])([-])([{_L}]+)")
_ABRE_NO_MEIO = re.compile(f"([{_L}]+)([-])(?=[{_L}])")


def junta_marcas(s):
    """funde corridas vizinhas do mesmo estilo: FECHA_x [espacos] ABRE_x -> [espacos]; e estende
    ate a palavra inteira um estilo que comeca/acaba no meio dela (dehifenizacao de "ultraphe-" em
    italico + "nomenico" lido como romano)."""
    for r in ABRE:
        s = re.sub(FECHA[r] + r"(\s*)" + ABRE[r], r"\1", s)
    if MARCA.search(s):
        s = _FECHA_NO_MEIO.sub(r"\2\1", s)
        s = _ABRE_NO_MEIO.sub(r"\2\1", s)
        for r in ABRE:
            s = re.sub(FECHA[r] + r"(\s*)" + ABRE[r], r"\1", s)
    return s


def pos_marcada(s, k):
    """indice em `s` (com marcas) do k-esimo caractere do texto limpo (marcas antes dele incluidas)."""
    n = 0
    for i, c in enumerate(s):
        if MARCA.match(c):
            continue
        if n == k:
            j = i
            while j > 0 and MARCA.match(s[j - 1]) and s[j - 1] in ABRE.values():
                j -= 1
            return j
        n += 1
    return len(s)


def le_fmt(tsv):
    """{(block, par, line, word): rend} do <id>.fmt.tsv ao lado do <id>.tsv (vazio se nao ha)."""
    f = Path(tsv).with_suffix(".fmt.tsv")
    out = {}
    if f.exists():
        with open(f, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                if r["rend"]:
                    out[(r["block"], r["par"], r["line"], r["word"])] = r["rend"]
    return out


def le_linhas(tsv, fmt=None):
    """linhas nao vazias de uma pagina, em ordem de leitura; (linhas, largura_da_pagina)."""
    fmt = le_fmt(tsv) if fmt is None else fmt
    linhas, largura = {}, 0
    with open(tsv, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            lv = int(r["level"])
            if lv == 1:
                largura = int(r["width"])
            k = (r["block_num"], r["par_num"], r["line_num"])
            if lv == 4:
                x, y, w, h = (int(r[c]) for c in ("left", "top", "width", "height"))
                linhas[k] = [x, y, x + w, y + h, [], [], []]
            elif lv == 5 and k in linhas:
                t = CTRL.sub("", r["text"]).strip()
                if t and float(r["conf"]) >= 0:
                    linhas[k][4].append(t)
                    linhas[k][5].append(float(r["conf"]) * len(t))
                    linhas[k][6].append(marca_palavra(t, fmt.get((*k, r["word_num"]))))
    out = []
    for x0, y0, x1, y1, ws, cs, ms in linhas.values():
        if ws:
            l = Linha(x0, y0, x1, y1, " ".join(ws), marc=junta_marcas(" ".join(ms)))
            l.conf = sum(cs) / max(1, sum(len(w) for w in ws))    # confianca media por caractere
            out.append(l)
    out = limpa_ruido(out)
    mede_tamanho(out)
    out.sort(key=lambda l: (l.y0, l.x0))
    return out, largura


def coluna(out):
    """(esquerda, direita) da coluna de texto, pelas linhas longas; None se a pagina tem poucas."""
    longas = [l for l in out if len(l.texto) > 25]
    if len(longas) < 3:
        return None
    direita = Counter(l.x1 // 10 for l in longas)
    # a moda e as faixas vizinhas (a justificacao oscila poucos px)
    faixa = max(direita, key=lambda b: direita[b] + direita[b - 1] + direita[b + 1])
    x0s = sorted(l.x0 for l in longas)
    return x0s[len(x0s) // 4], faixa * 10 + 5


def limpa_ruido(out):
    """descarta (1) ruido de margem: linha que fica toda fora da coluna (sujeira da borda do scan,
    da pagina vizinha: "o —" em x0 = 1752 na p. 6 do vol. 2 quebrava o paragrafo); (2) ornamento:
    linhas de confianca media < 60 ACIMA da 1a linha de texto confiavel (vinheta do inicio de
    parte, lida como "tel ole Sub").  Texto ruim no meio da pagina (grego, latim) fica."""
    col = coluna(out)
    if col:
        esq, dir_ = col
        out = [l for l in out if l.x1 > esq + 30 and l.x0 < dir_ - 30]
    out.sort(key=lambda l: (l.y0, l.x0))
    # so linhas curtas e sem numero: o enunciado de tese em negrito tambem tem confianca baixa
    i = next((i for i, l in enumerate(out)
              if l.conf >= 75 and sum(c.isalpha() for c in l.texto) >= 6), 0)
    return [l for j, l in enumerate(out)
            if j >= i or l.conf >= 60 or len(l.texto) >= 20 or re.match(r"\W*\d", l.texto)]


def mede_tamanho(out):
    """tamanho da letra = largura por caractere, so em linhas "cheias" (justificadas): corpo ~21.5 px,
    corpo menor/notas ~17.5 px a 300 ppi.  A altura da palavra foi descartada: oscila demais.

    Linha cheia = termina na margem direita da coluna (moda dos x1, em faixas de 10 px) e comeca na
    margem esquerda ou num recuo de paragrafo.  A margem direita nao e o maior x1: o OCR cola ruido
    da margem do scan ao fim de algumas linhas (x1 ate a borda), e essas linhas dariam medida falsa;
    medir pela largura maxima (como antes) deixava sem medida quase todas as linhas da pagina."""
    col = coluna(out)
    if not col:
        return
    esq, xd = col
    for l in out:
        if len(l.texto) > 25 and abs(l.x1 - xd) <= 25 and -25 <= l.x0 - esq <= 140:
            l.h = (l.x1 - l.x0) / len(l.texto)


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


LIMIAR_CORTE = 3.0          # escore minimo para aceitar uma area de notas
LIMIAR_REPARO = 0.5         # idem, quando o corpo tem chamada "(n)" sem nota (reparo por chamadas)


def escore_corte(linhas, k, corpo, nota, limiar_h, aberta, margem, limiar_recuo):
    """(escore, motivos) de "a area de notas comeca na linha k" (0 < k < n).

    Soma de votos, nenhum com poder de veto: o tamanho da letra e fragil (falta em linhas curtas,
    o OCR cola ruido no fim da linha), a entrelinha falha em notas de 1-2 linhas, o vao falha
    quando o filete fica perto do texto.  Juntos, um compensa o outro."""
    l, n = linhas[k], len(linhas)
    e, por = 0.0, []

    def voto(v, motivo):
        nonlocal e
        e += v
        if v:
            por.append(f"{motivo}{v:+g}")

    # 1. marcador: "(n)" (recuado, de preferencia) ou continuacao de nota aberta sem recuo
    recuo = l.x0 - margem
    marca = NOTA.match(l.texto) is not None
    if marca:
        voto(2.0 if recuo >= limiar_recuo / 2 else 1.5, "(n)")
    elif aberta and recuo < limiar_recuo:
        voto(1.5, "continua")
        if CHAMADA.search(l.texto):
            voto(-2.0, "chamada-na-linha")         # linha com chamada "(n)" e de corpo
    else:
        return None, []                    # sem marcador nao ha onde comecar nota
    # 2. vao antes (o filete fica ali).  Linhas minusculas logo antes ("m", "R55") sao o proprio
    # filete lido pelo OCR: o vao conta a partir da linha de texto anterior a elas.
    j = k - 1
    while j > 0 and len(linhas[j].texto) <= 4:
        j -= 1
    vao = (l.y0 - linhas[j].y0) / corpo
    # sem vao, a continuacao (sem marcador) fica quase vetada; com "(n)" e so um voto contra:
    # no vol. 1 a nota segue um escolio em corpo menor com pouco espaco antes do filete
    falta = -1.0 if marca else -3.0
    voto(2.0 if vao >= 1.9 else 1.0 if vao >= 1.3 else -1.0 if vao >= 1.1 else falta, "vao")
    # 3. entrelinha da cauda: a das notas (calibrada) contra a do corpo
    difs = [b.y0 - a.y0 for a, b in zip(linhas[k:], linhas[k + 1:])]
    difs_norm = [d for d in difs if d < 1.25 * corpo]           # vaos de paragrafo nao contam
    if nota and len(difs_norm) >= 2:
        med = statistics.median(difs_norm)
        meio = (corpo + nota) / 2
        voto(1.5 if med < meio - 2 else -1.5 if med > meio + 2 else 0, "entrelinha")
        # linhas de corpo no meio da cauda: o corte esta cedo demais (a mediana sozinha nao ve
        # 10 linhas de corpo seguidas de 30 de nota)
        grandes = sum(d > meio + 3 for d in difs_norm) / len(difs_norm)
        if grandes > 0.12:
            voto(round(-5.0 * grandes, 1), "cauda-grande")
    # 4. tamanho da letra, quando medido: voto, nao veto
    if limiar_h:
        cauda = [x.h for x in linhas[k:] if x.h]
        if cauda:
            m = statistics.median(cauda)
            voto(1.0 if m < limiar_h - 0.5 else -1.0 if m > limiar_h + 0.5 else 0, "letra")
            fg = sum(h > limiar_h + 0.5 for h in cauda) / len(cauda)
            if len(cauda) >= 4 and fg > 0.2:
                voto(round(-3.0 * fg, 1), "letra-grande-na-cauda")
            # a fronteira e local: as 1as linhas medidas logo apos o corte tem de ser pequenas
            # (a mediana da cauda inteira nao ve 5 linhas de corpo antes de 30 de nota)
            ini = [x.h for x in linhas[k:k + 4] if x.h][:2]
            if ini:
                voto(-2.5 if max(ini) > limiar_h + 0.5 else 0.5 if max(ini) < limiar_h - 0.5 else 0,
                     "letra-no-corte")
        cabeca = [x.h for x in linhas[max(0, k - 6):k] if x.h]
        if cabeca and cauda:
            mc = statistics.median(cabeca)
            voto(0.5 if mc > limiar_h + 0.5 else 0, "letra-corpo")
    return e, por


def inicio_notas(linhas, corpo, limiar_h, aberta, margem=0, limiar_recuo=40, nota=None,
                 detalhe=None):
    """indice da 1a linha da area de notas, ou len(linhas) se a pagina nao tem notas.

    Uma pagina tem no maximo UMA fronteira corpo->notas: avalia cada corte k (ver escore_corte) e
    fica com o de maior escore, se passar de LIMIAR_CORTE; senao, "sem notas".  Reparo por
    chamadas: se o corpo antes do corte tem chamada "(n)" e o vencedor e "sem notas", aceita o
    melhor corte que comece em "(n)" com escore >= LIMIAR_REPARO (o caso da p. 5 do vol. 2).
    `detalhe` (lista) recebe (k, escore, motivos) do vencedor, para os alertas."""
    n = len(linhas)
    if n < 2:
        return n
    cands = []
    for k in range(1, n):
        e, por = escore_corte(linhas, k, corpo, nota, limiar_h, aberta, margem, limiar_recuo)
        if e is not None:
            cands.append((e, -k, k, por))
    if not cands:
        return n
    # continuacao (sem "(n)") so pode abrir a area de notas: depois de um "(n)" aceitavel, nao
    primeiro_n = min((c[2] for c in cands if c[0] >= LIMIAR_CORTE and NOTA.match(linhas[c[2]].texto)),
                     default=n)
    passam = [c for c in cands if c[0] >= LIMIAR_CORTE
              and (c[2] <= primeiro_n or NOTA.match(linhas[c[2]].texto))]
    if passam:
        # entre "(n)": quase-empate fica com o mais cedo (a 2a nota da pagina repete os sinais da
        # 1a, com cauda mais limpa).  Continuacao so ganha se superar o melhor "(n)".
        nn = [c for c in passam if NOTA.match(linhas[c[2]].texto)]
        cc = [c for c in passam if not NOTA.match(linhas[c[2]].texto)]
        pn = min((c for c in nn if c[0] >= max(x[0] for x in nn) - 1.0), key=lambda c: c[2]) if nn else None
        pc = max(cc) if cc else None
        e, _, k, por = pc if pc and (pn is None or pc[0] > pn[0]) else pn
        escolhido = (k, e, por)
    else:
        rep = [c for c in cands if NOTA.match(linhas[c[2]].texto) and c[0] >= LIMIAR_REPARO
               and any(CHAMADA.search(x.texto) for x in linhas[:c[2]])]
        if not rep:
            return n
        e, _, k, por = max(rep)
        escolhido = (k, e, por + ["reparo-chamada"])
    if detalhe is not None:
        detalhe.append(escolhido)
    return escolhido[0]


PALAVRA_FIM = re.compile(r"([A-Za-zÀ-ÖØ-öø-ÿ]+)-$")
PALAVRA_INI = re.compile(r"^([A-Za-zÀ-ÖØ-öø-ÿ]+)")


def _lexico():
    try:
        import lexico
        return lexico
    except ImportError:
        return None


def conhecida(w):
    lx = _lexico()
    return lx is not None and (lx.valida(w) or lx.frequencias()[w.lower()] >= 3)


def enclise(a, b):
    """"a-" + "b" no fim de linha e verbo + pronome encliticos (chamam-se, dizê-lo, dei-o)?
    A frequencia do corpus conta fragmentos de hifenizacao (supre-, repu-) e o pt_PT aceita alguns
    como prefixo: por isso a forma do verbo tem de casar com o pronome."""
    lx = _lexico()
    if lx is None or len(a) < 3:
        return False
    f = lx.frequencias()[a.lower()]
    verbo = (a.endswith("r") and f >= 5) or (a.endswith("ndo") and f >= 3) or \
        (lx.valida(a) and f >= 15) or f >= 50
    b = b.lower()
    vogal = a[-1].lower() in "aeiouáéíóúâêô"
    if b in ("se", "lhe", "lhes", "nos", "vos", "me", "te", "hia", "hiam", "ha", "hei", "hão", "emos", "ia", "iam"):
        return verbo
    if b in ("lo", "la", "los", "las"):
        return verbo and vogal
    if b in ("o", "a", "os", "as"):
        return verbo and vogal and f >= 30
    if b in ("no", "na", "nas"):
        return verbo and (a.endswith("m") or a.endswith("ão") or a.endswith("õe"))
    return False


def fim_palavra(s):
    """fim da 1a palavra de s (com marcas de formatacao e hifen de enclise): ate o 1o espaco ou
    pontuacao."""
    return re.match(r"\S*?(?=[\s.,;:!?)»]|$)", s).end()


def hifen(u, texto):
    """`u` termina em "-" (fim de linha): devolve o que vem DEPOIS de u[:-1] para juntar `texto`,
    ou None para juntar com espaco (sem dehifenizar).

      * enclise ("chamam-" + "se", ver enclise()): mantem o hifen ("chamam-se"), salvo se a juncao
        e palavra conhecida ("es-" + "se" = "esse");
      * 2a parte maiuscula por erro do OCR ("redu-" + "Zir-se"): junta em minuscula se a juncao e
        conhecida ("reduzir-se");
      * senao, 2a parte minuscula: junta (hifenizacao silabica, o caso comum)."""
    us, ts = sem_marcas(u), sem_marcas(texto)     # decide no texto limpo; devolve o marcado
    if not u.endswith("-") or not ts:
        return None
    ma, mb = PALAVRA_FIM.search(us), PALAVRA_INI.match(ts)
    if not ma or not mb:
        return texto if ts[:1].islower() else None
    a, b = ma.group(1), mb.group(1)
    if b.islower() and enclise(a, b) and not conhecida(a + b):
        return "-" + texto        # enclise: mantem o hifen
    if b[:1].isupper() and not b.isupper() and conhecida(a + b.lower()):
        i = next(j for j, c in enumerate(texto) if not MARCA.match(c))
        return texto[:i] + texto[i].lower() + texto[i + 1:]
    return texto if ts[:1].islower() else None


class Par:
    """paragrafo/nota em construcao: pecas = str | ('pb', n) | ('nota', Nota)."""

    def __init__(self, texto, pag, recuado):
        self.pecas, self.pag, self.recuado = [texto], pag, recuado

    def texto(self):
        return "".join(p for p in self.pecas if isinstance(p, str))

    def anexa(self, texto, pb=None):
        """junta linha seguinte, desfazendo hifenizacao de fim de linha.  Com `pb` (a linha e a 1a
        da pagina seguinte), o <pb> fica entre as duas, depois da palavra hifenizada inteira."""
        u = self.pecas[-1] if self.pecas and isinstance(self.pecas[-1], str) else None
        h = hifen(u, texto) if u is not None else None
        if pb is not None:
            k = fim_palavra(h) if h is not None else 0
            if h is not None:
                self.pecas[-1] = u[:-1] + h[:k]
            self.pecas.append(pb)
            resto = h[k:] if h is not None else texto
            if resto:
                self.pecas.append(resto)
        elif h is not None:
            self.pecas[-1] = u[:-1] + h
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
            pars.append(Par(l.marc, None, recuado))
        else:
            pars[-1].anexa(l.marc)
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
    pendentes = []                   # chamadas da pagina anterior que ficaram sem nota: (Par, glifo, pag)
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

        # 1. cabecalho (um fragmento de 1-3 caracteres acima dele, sujeira do scan, e descartado)
        if len(linhas) >= 2 and len(linhas[0].texto) <= 3 and eh_cabecalho(linhas[1].texto) \
                and not eh_cabecalho(linhas[0].texto):
            linhas = linhas[1:]
        if eh_cabecalho(linhas[0].texto) and (len(linhas) < 2 or linhas[1].y0 - linhas[0].y0 < 3 * corpo):
            fluxo.append(("fw", linhas[0].texto))
            linhas = linhas[1:]
            if not linhas:
                continue
        # 2. corpo x notas
        # nota aberta: a pagina anterior teve area de notas, OU deixou chamada sem nota (o corte
        # dela falhou: a continuacao aqui e a nota daquela chamada)
        aberta = (nota_aberta is not None and pag_anterior_com_notas) or bool(pendentes)
        det = []
        k = inicio_notas(linhas, corpo, limiar_h, aberta, margem, limiar, nota, det)
        if det and "reparo-chamada" in det[0][2]:
            alerta(imp, "corte-por-chamada", f"notas a partir da linha {k} só pela chamada no corpo "
                   f"(escore {det[0][1]:g}: {' '.join(det[0][2][:-1])})")
        elif det and det[0][1] < LIMIAR_CORTE + 1:
            alerta(imp, "corte-incerto", f"notas a partir da linha {k}, escore {det[0][1]:g} "
                   f"({' '.join(det[0][2])})")
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
        recuperada, orfa = None, None
        if cont and pendentes:
            # a pagina anterior deixou chamada sem nota: esta continuacao e a nota dela (o comeco
            # da nota ficou no corpo da pagina anterior: conferir)
            par_c, glifo, pag_c = pendentes.pop(0)
            recuperada = nt = Nota(num_chamada(glifo) or "1", pag_c, cont)
            cont[0].pecas.insert(0, ("pb", imp))
            if insere_chamada(par_c, glifo, nt):
                alerta(imp, "nota-recuperada", f"continuação ligada à chamada ({glifo}) da p. {pag_c}, "
                       f"que ficou sem nota: o começo de {nt.id} deve estar no corpo da p. {pag_c}")
            else:
                par_c.pecas.append(("nota", nt))
                alerta(imp, "nota-recuperada", f"continuação sem chamada localizável: {nt.id} no fim do parágrafo")
        elif cont:
            if nota_aberta is None:
                # o texto nao pode sumir: vira nota sem numero no fim do ultimo paragrafo
                alerta(imp, "continuacao-sem-nota", "área de notas começa sem “(n)” e não há nota aberta; "
                       "anexada como nota “?” ao último parágrafo")
                recuperada = orfa = Nota("?", imp, cont)
            else:
                if FIM_FRASE.search(sem_marcas(nota_aberta.pars[-1].texto())):
                    alerta(imp, "continuacao-duvidosa", f"nota {nota_aberta.id} parecia terminada, mas continua")
                primeiro = cont[0]
                if primeiro.recuado:
                    nota_aberta.pars[-1].pecas.append(("pb", imp))
                    nota_aberta.pars.append(primeiro)
                else:
                    nota_aberta.pars[-1].anexa(primeiro.texto(), ("pb", imp))
                nota_aberta.pars.extend(cont[1:])
        if novas:
            nota_aberta = novas[-1]
        elif recuperada is not None:
            nota_aberta = recuperada
        pag_anterior_com_notas = bool(novas or cont)

        # 4. continuacao de paragrafo do corpo
        if pars and ultima_par is not None and not pars[0].recuado and \
                not FIM_FRASE.search(sem_marcas(ultima_par.texto())) and not re.match(r"^\d{1,3}\.\s", sem_marcas(pars[0].texto())):
            cabeca = pars.pop(0)
            lig = [cabeca]
        else:
            lig = []
        # 5. liga notas as chamadas (por ordem; o numero confirma)
        corpo_pars = lig + pars
        pendentes = [(p_, g_, imp) for p_, g_ in liga_notas(corpo_pars, novas, imp, alerta)]
        if orfa is not None:
            destino = ultima_par if ultima_par is not None else (corpo_pars[-1] if corpo_pars else None)
            if destino is not None:
                destino.pecas.append(("nota", orfa))
                orfa.chamada = True
        if lig:
            u = ultima_par
            c0 = lig[0].pecas
            # notas sem chamada anexadas ao fim do paragrafo (ver liga_notas) depois de um hifen de
            # fim de pagina sairiam no meio da palavra ("desconve-<nota/>niencia"): saem da frente
            # do hifen e voltam depois da palavra completa
            soltas = []
            while len(u.pecas) > 1 and isinstance(u.pecas[-1], tuple) and u.pecas[-1][0] == "nota" \
                    and any(isinstance(x, str) for x in u.pecas[:-1]):
                soltas.insert(0, u.pecas.pop())
            h = hifen(u.pecas[-1], c0[0]) if isinstance(u.pecas[-1], str) and isinstance(c0[0], str) else None
            if h is not None:                                # hifen de fim de pagina
                k = fim_palavra(h)                           # palavra inteira antes do <pb>
                u.pecas[-1] = u.pecas[-1][:-1] + h[:k]
                c0[0] = h[k:]
            elif isinstance(c0[0], str):
                c0[0] = " " + c0[0]
            u.pecas.extend(soltas)
            u.pecas.append(("pb", imp))
            # o <pb> desta pagina passa a ficar DENTRO do paragrafo (nao no fluxo), e o <fw> da
            # pagina vai junto dele (antes ficava solto depois do </p>)
            i_pb = fluxo.index(("pb", imp, pid))
            if i_pb + 1 < len(fluxo) and fluxo[i_pb + 1][0] == "fw":
                u.pecas.append(fluxo.pop(i_pb + 1))
            fluxo.remove(("pb", imp, pid))
            u.pecas.extend(x for x in c0 if x != "")
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
    if len(chamadas) == len(novas):
        pares = list(zip(chamadas, novas))              # por ordem; o numero impresso so confirma
    else:                                               # por numero impresso, quando legivel
        por_num = {}
        for c in chamadas:
            k = num_chamada(c[2].group(1))
            if k is not None:
                por_num.setdefault(k, c)
        pares = [(por_num[n.num], n) for n in novas if n.num in por_num]
        feitos = {id(c[0]) * 1000 + c[2].start() for c, _ in pares}
        # glifos ilegiveis ("(*)"): casa por ordem as chamadas e notas que sobraram
        sobra_c = [c for c in chamadas if id(c[0]) * 1000 + c[2].start() not in feitos]
        sobra_n = [n for n in novas if n not in [x[1] for x in pares]]
        pares += list(zip(sobra_c, sobra_n))
    usados = set()
    por_peca = {}
    for (p, i, m), nt in pares:
        k = num_chamada(m.group(1))
        if k is not None and k != nt.num:
            alerta(pag, "numero-diverge", f"chamada ({m.group(1)}) ligada à nota ({nt.num})")
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
    feitas = {id(c[2]) for c, _ in pares}
    return [(p, m.group(1)) for p, i, m in chamadas if id(m) not in feitas]


def insere_chamada(par, glifo, nt):
    """troca a 1a chamada "(glifo)" ainda em texto do paragrafo pela nota nt; False se nao achou."""
    for i, pc in enumerate(par.pecas):
        if isinstance(pc, str):
            for m in CHAMADA.finditer(pc):
                if m.group(1) == glifo:
                    par.pecas[i:i + 1] = [x for x in (pc[:m.start()], ("nota", nt), pc[m.end():]) if x != ""]
                    nt.chamada = True
                    return True
    return False


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
        elif pc[0] == "fw":
            etree.SubElement(el, T("fw"), type="header").text = pc[1]
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
SUMARIO = re.compile(r"^\s*" + M_ + r"summ?ario" + M_ + r"\s*[:.]?", re.I)


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
        t1 = sem_marcas(texto)             # titulos, cabecalhos e rotulos: sem formatacao
        if eh_cabecalho_corrente(t1):
            self.fw(t1)
            return
        # Summario (+ "ARTIGO I" colado no fim)
        if SUMARIO.match(texto):
            m = re.search(r"\s+" + M_ + r"(ARTIGO\s+[IVXL1l|]{1,5}\.?)" + M_ + r"\s*$", texto)
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
        if self.sumario is not None and not reconhece_titulo(t1) and not TESE.match(t1):
            ap, ult = self.sumario
            if not FIM_FRASE.search("".join(ap.itertext())):     # Summario com recuo suspenso: continua
                m2 = re.search(r"\s+" + M_ + r"(ARTIGO\s+[IVXL1l|]{1,5}\.?)" + M_ + r"\s*$", texto)
                tit2 = reconhece_titulo(m2.group(1)) if m2 else None
                resto_s = texto[:m2.start()] if m2 else texto
                poe_texto(ap, " " + resto_s.strip())
                if tit2:
                    self.sumario = None
                    self.titulo_reconhecido(tit2)
                return
        self.sumario = None
        tit = reconhece_titulo(t1) if all(isinstance(x, str) for x in p.pecas) else None
        if tit and len(p.pecas) == 1:
            self.titulo_reconhecido(tit)
            return
        # titulo (caixa alta) logo apos um rotulo recem aberto
        if self.ultimo_titulo is not None:
            d = self.ultimo_titulo
            heads = d.findall(T("head"))
            if len(heads) == 1 and all(isinstance(x, str) for x in p.pecas) and not TESE.match(t1) and len(t1) <= 110 \
                    and (t1.isupper() or (d.get("type") == "artigo" and t1.endswith("."))):
                h = etree.SubElement(d, T("head"))
                h.text = t1
                self.flush_pb_antes(h) if self.pb_pend else None
                self.ultimo_titulo = None
                return
            self.ultimo_titulo = None
        m = TESE.match(t1) or TESE_TITULO.match(t1)       # no texto limpo (marcas contam caracteres)
        m = m if len(p.pecas) >= 1 and isinstance(p.pecas[0], str) else None
        so_titulo = m is not None and m.re is TESE_TITULO
        n = self.resolve_numero(int(m.group(1)), sem_marcas(m.group(2)).strip(), so_titulo) if m else None
        if n is not None:
            self.nova_tese(n, p, m)
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
        rot, resto = sem_marcas(rot), sem_marcas(resto)
        d = self.abre(nivel, rot)
        if resto:
            h = etree.SubElement(d, T("head"))
            h.text = resto
            self.ultimo_titulo = None

    def resolve_numero(self, n, titulo, so_titulo):
        """numero da tese (corrigido se o OCR trocou 1 digito) ou None se nao parece a proxima tese."""
        e = self.ultima_tese + 1
        if n == e or self.ultima_tese == 0:             # 1a tese do trecho: qualquer numero
            return n
        if n == self.ultima_tese:
            self.alerta(self.pag, "tese-fora-de-sequencia", f"tese {n} repetida")
            return n
        # o OCR perde teses inteiras: salto para frente em janela curta e confiavel (forma estrita)
        if e < n <= e + (3 if so_titulo else 30) and titulo[:1].isupper():
            self.alerta(self.pag, "tese-fora-de-sequencia", f"tese {n} depois da {self.ultima_tese}")
            return n
        # nao e a proxima nem cabe na janela (voltaria atras / salto enorme): so serve se for a
        # proxima com UM digito trocado pelo OCR (905 por 205, 13 por 73)
        a, b = str(n), str(e)
        if len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1 and titulo[:1].isupper():
            self.alerta(self.pag, "numero-corrigido", f"tese lida como {n}, esperado {e}: assumido {e}")
            return e
        return None

    def nova_tese(self, n, p, m):
        # reparte as pecas no 1o " — " apos o enunciado
        s0 = p.pecas[0]
        so_titulo = m.re is TESE_TITULO
        enun, resto0 = m.group(2).strip(), ("" if so_titulo else s0[pos_marcada(s0, m.start(3)):])
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


def _corridas(s):
    """[(texto, rend|None)] de um segmento com marcas, tolerante a marca sem par."""
    out, atual, buf = [], None, []
    for c in s:
        r = REND.get(c)
        if r is None:
            buf.append(c)
            continue
        if buf:
            out.append(("".join(buf), atual))
            buf = []
        atual = r if c == ABRE[r] else (None if atual == r else atual)
    if buf:
        out.append(("".join(buf), atual))
    return out, atual


def aplica_marcas(raiz):
    """troca os marcadores de formatacao por <hi rend>.  Uma corrida aberta atravessa os <pb/>,
    <fw> e <note> do mesmo elemento (fecha antes e reabre depois).  Em <fw>, <label>, <head> e
    no enunciado em negrito da tese as marcas so somem."""
    so_limpa = {T("fw"), T("label"), T("head")}
    for el in list(raiz.iter()):
        if not isinstance(el.tag, str):
            continue
        if el.tag in so_limpa:
            for c in el.iter():
                c.text = sem_marcas(c.text)
                if c is not el:
                    c.tail = sem_marcas(c.tail)
            continue
        if el.tag == T("hi"):            # <hi> ja existente (enunciado da tese): sem marcas dentro
            el.text = sem_marcas(el.text)
            continue
        em_bold = any(a.tag == T("hi") and a.get("rend") == "bold" for a in el.iterancestors())
        estado = None
        for dono in [None] + list(el):
            s = el.text if dono is None else dono.tail
            if not s or (estado is None and not MARCA.search(s)):
                continue
            s = junta_marcas((ABRE[estado] if estado else "") + s)
            pecas, estado = _corridas(s)
            texto0, novos = "", []
            for txt, rend in pecas:
                if rend is None or (em_bold and rend == "bold"):
                    if novos:
                        novos[-1].tail = (novos[-1].tail or "") + txt
                    else:
                        texto0 += txt
                else:
                    h = etree.Element(T("hi"), rend=rend)
                    h.text = txt
                    novos.append(h)
            if dono is None:
                el.text = texto0
                pos = 0
            else:
                dono.tail = texto0
                pos = el.index(dono) + 1
            for i, h in enumerate(novos):
                el.insert(pos + i, h)
    return raiz


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
    aplica_marcas(tei)
    alerta[:] = [(pg, tp, sem_marcas(msg)) for pg, tp, msg in alerta]
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
    rends = Counter(h.get("rend") for h in tei.iter(T("hi")))
    print("formatação (<hi rend>):", dict(rends), file=sys.stderr)
    div = Counter(d.get("type") for d in tei.iter(T("div")))
    print("divisões:", dict(div), file=sys.stderr)
    print(f"{len(alerta)} alertas ({dict(tipos)}) → {alt}", file=sys.stderr)


if __name__ == "__main__":
    main()
