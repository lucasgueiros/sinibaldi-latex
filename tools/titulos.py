#!/usr/bin/env python3
"""Detecta os titulos de um volume e PROPOE o estrutura.tsv (plano: titulos-e-estrutura.md).

    python3 tools/titulos.py vol2                    # -> vol2/estrutura.proposta.tsv + .alertas.tsv
    python3 tools/titulos.py vol2 --diff             # + diff contra vol2/estrutura.tsv (revisado)
    python3 tools/titulos.py vol2 --mede             # precisao/revocacao da proposta contra o revisado

Entrada: volN/paginas/manifesto.tsv, <id>.tsv (tesseract) e <id>.fmt.tsv (formatacao medida).
Saida: uma linha por titulo/tese, em ordem do livro:

    pag  ancora  nivel  rotulo  titulo  id  fonte

O estrutura.tsv revisado nunca e sobrescrito.  Linhas `fonte=revisado` mandam: a deteccao so
alerta se discorda delas.

Regras (o OCR erra os numerais e o cabecalho corrente; o que e medido na imagem e confiavel):
  * rotulo (PARTE/SECCAO/CAPITULO/ARTIGO + ordinal) = linha CENTRADA; a 1a linha da pagina so e
    cabecalho corrente se parece cabecalho (numero na ponta ou travessao, letra pequena);
  * o titulo e o bloco de linhas centradas seguintes (1-3 linhas, sem vao grande);
  * tese = "N. enunciado — texto" com N em sequencia (rend bold confirma);
  * numerais conferidos em sequencia (artigo recomeca por capitulo; capitulo por secao/parte);
  * cabecalho corrente votado em janela de paginas: capitulo-esperado / capitulo-fantasma /
    nome-diverge;  aparato final (Synopse, Indice) fica fora.
"""
import argparse
import csv
import difflib
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estruturar_tei import (ABRE, FECHA, ORDINAIS, TESE, TESE_TITULO, SUMARIO, coluna, le_linhas,  # noqa: E402
                            le_manifesto, norm, sem_marcas)

NIVEIS = {"parte": 1, "seccao": 2, "capitulo": 3, "artigo": 4}
ROTULO_NIVEL = {"PARTE": "parte", "SECCAO": "seccao", "CAPITULO": "capitulo", "ARTIGO": "artigo"}
NOME_NIVEL = {"parte": "Parte", "seccao": "Secção", "capitulo": "Capitulo", "artigo": "Artigo"}
ORD_N = {"PRIMEIRO": 1, "PRIMEIRA": 1, "UNICO": 1, "UNICA": 1, "SEGUNDO": 2, "SEGUNDA": 2,
         "TERCEIRO": 3, "TERCEIRA": 3, "QUARTO": 4, "QUARTA": 4, "QUINTO": 5, "QUINTA": 5,
         "SEXTO": 6, "SEXTA": 6, "SETIMO": 7, "SETIMA": 7, "OITAVO": 8, "OITAVA": 8,
         "NONO": 9, "NONA": 9, "DECIMO": 10, "DECIMA": 10}
ROMANOS = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
FEM = {"PRIMEIRO": "Primeiro", "SEGUNDO": "Segundo", "TERCEIRO": "Terceiro", "QUARTO": "Quarto"}
COLUNAS = ["pag", "ancora", "nivel", "rotulo", "titulo", "id", "fonte"]
APARATO = re.compile(r"SYNOPSE|INDICE DAS|INDICE GERAL")


# ------------------------------------------------------------------ numerais
def romano(tok):
    """valor de um numeral romano mal lido ('1I', '11', 'l|', 'IL', '|' ...) ou None."""
    s = re.sub(r"[.,;:\s]", "", tok).translate(str.maketrans("l|1!JjiLÍ", "IIIIIIIII"))
    if not s or not re.fullmatch(r"[IVX]+", s):
        return None
    v = {"I": 1, "V": 5, "X": 10}
    n = sum(-v[c] if i + 1 < len(s) and v[c] < v[s[i + 1]] else v[c] for i, c in enumerate(s))
    return n if 0 < n <= 39 else None


def para_romano(n):
    s = ""
    for v, r in ROMANOS:
        while n >= v:
            s, n = s + r, n - v
    return s


def numeral(tok):
    """(valor, palavra-normalizada) de 'PRIMEIRO', 'SEGUNDA', 'II', '11' ...; (None, None) se nao e."""
    t = norm(tok.strip(".,;:"))
    if t in ORD_N:
        return ORD_N[t], t
    if len(t) >= 5:
        c = difflib.get_close_matches(t, ORD_N, n=1, cutoff=0.78)
        if c:
            return ORD_N[c[0]], c[0]
    v = romano(tok)
    return (v, None) if v else (None, None)


def reconhece_rotulo(texto):
    """(nivel, valor, palavra, resto) para 'CAPITULO SEGUNDO', 'ARTIGO II. Titulo'; senao None."""
    t = texto.strip()
    if len(t) > 140:
        return None
    m = re.match(r"^(\S+)\s+([^\s.:,;]+)[\s.:,;—–-]*(.*)$", t)
    if not m:
        return None
    a = norm(m.group(1))
    if a.startswith("SEC") and len(a) <= 8:
        kw = "SECCAO"
    elif a.startswith("ART") and len(a) <= 7:
        kw = "ARTIGO"
    elif a.startswith("CAP") or a.startswith("CAF"):
        kw = "CAPITULO" if 6 <= len(a) <= 10 else None
    else:
        c = difflib.get_close_matches(a, ["PARTE", "CAPITULO", "ARTIGO"], n=1, cutoff=0.8) if len(a) >= 5 else []
        kw = c[0] if c else None
    if not kw:
        return None
    valor, palavra = numeral(m.group(2))
    if valor is None:
        return None
    resto = m.group(3).strip()
    nivel = ROTULO_NIVEL[kw]
    if resto and not (resto.isupper() or nivel == "artigo"):
        return None                       # "Parte segunda é a..." em texto corrente
    return nivel, valor, palavra, resto


def rotulo_canonico(nivel, valor, palavra):
    if nivel == "artigo":
        return f"Artigo {para_romano(valor)}"
    if palavra:
        return f"{NOME_NIVEL[nivel]} {palavra.capitalize()}"
    return f"{NOME_NIVEL[nivel]} {para_romano(valor)}"


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", norm(s).lower()).strip("-")
    return "-".join(s.split("-")[:5])


# ------------------------------------------------------------------ paginas
class Pagina:
    def __init__(self, imp, linhas, largura):
        self.imp, self.linhas, self.largura = imp, linhas, largura
        col = coluna(linhas)
        self.col = col
        longas = [l.y1 - l.y0 for l in linhas if len(l.texto) > 25]
        self.alt = statistics.median(longas) if longas else None      # altura do corpo
        self.cab = None                                               # texto do cabecalho corrente
        self.corpo = self._separa_cabecalho()

    def centrada(self, l):
        if not self.col:
            return False
        esq, dir_ = self.col
        larg = dir_ - esq
        w = (l.x1 - l.x0) / larg
        tol = 0.09 if w < 0.8 else 0.04             # linha larga: so centro quase exato (recuo de paragrafo ~7%)
        return abs((l.x0 - esq) - (dir_ - l.x1)) <= tol * larg and w < 0.96

    def _parece_cabecalho(self, l):
        t = l.texto.strip()
        if len(t) > 95 or (self.alt and (l.y1 - l.y0) >= 1.3 * self.alt):
            return False                          # letra grande: titulo, nao cabecalho
        if not (re.search(r"\W\d{1,4}\W*$", t) or re.match(r"^\W*\d{1,4}\W", t) or "—" in t):
            return False
        letras = [c for c in t if c.isalpha()]
        return len(letras) >= 5 and sum(c.isupper() for c in letras) / len(letras) > 0.6

    def _separa_cabecalho(self):
        ls = list(self.linhas)
        for i in range(min(2, len(ls))):
            if self._parece_cabecalho(ls[i]):
                self.cab = ls[i].texto.strip()
                return ls[:i] + ls[i + 1:]
        return ls


def frac_rend(marc, rend="bold"):
    """fracao das letras do texto marcado que estao dentro de <rend>."""
    dentro, n, tot = False, 0, 0
    for c in marc:
        if c == ABRE[rend]:
            dentro = True
        elif c == FECHA[rend]:
            dentro = False
        elif c.isalpha():
            tot += 1
            n += dentro
    return n / tot if tot else 0.0


# ------------------------------------------------------------------ cabecalho corrente
def le_cabecalho(t):
    """{'parte','secao','cap'} -> (valor) e 'nome' de um cabecalho corrente; so o que le."""
    u = norm(t.replace("—", " — "))
    out = {}
    m = re.search(r"\bPARTE (\w+)", u)
    if m:
        out["parte"] = numeral(m.group(1))[0]
    m = re.search(r"\bSEC\w* ([\w|]+)", u)
    if m:
        out["secao"] = numeral(m.group(1))[0]
    m = re.search(r"\bCAP\w* ([\w|]+)", u)
    if m:
        out["cap"] = numeral(m.group(1))[0]
    nome = re.split(r"[—–]", t)[-1] if re.search(r"[—–]", t) else ""
    out["nome"] = re.sub(r"[\d\W]+$|^[\d\W]+", "", nome).strip()
    return out


# ------------------------------------------------------------------ teses
def dist1(a, b):
    """True se as cadeias diferem em no maximo uma troca, insercao ou remocao."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    a, b = (a, b) if len(a) < len(b) else (b, a)
    return any(a == b[:i] + b[i + 1:] for i in range(len(b)))


def _resolve_segmento(achados, alerta, salto=40):
    """fica com a maior sequencia crescente de teses (as teses sao 1, 2, 3 ... pelo volume);
    candidatas fora dela sao corrigidas por 1 digito, se couberem num buraco, ou descartadas."""
    ix = [k for k, a in enumerate(achados) if a["nivel"] == "tese"]
    m = len(ix)
    if not m:
        return achados
    v = [achados[k]["valor"] for k in ix]
    melhor = [(1, 0, -1)] * m                      # (quantidade, -soma dos saltos, anterior)
    for i in range(m):
        for j in range(i):
            if v[j] < v[i] <= v[j] + salto:
                c = (melhor[j][0] + 1, melhor[j][1] - (v[i] - v[j] - 1), j)
                if c[:2] > melhor[i][:2]:
                    melhor[i] = c
    fim = max(range(m), key=lambda i: melhor[i][:2])
    cadeia = []
    while fim != -1:
        cadeia.append(fim)
        fim = melhor[fim][2]
    cadeia.reverse()
    dentro = set(cadeia)
    usados = {v[i] for i in cadeia}
    descartar = set()
    for i in range(m):
        if i in dentro:
            continue
        a = achados[ix[i]]
        ant = max((v[c] for c in cadeia if c < i), default=0)
        pos = min((v[c] for c in cadeia if c > i), default=10 ** 6)
        cand = [x for x in range(ant + 1, min(pos, ant + salto + 1)) if x not in usados and dist1(str(x), str(v[i]))]
        if cand:
            x = min(cand, key=lambda x: abs(x - v[i]))
            alerta(a["pag"], "numero-corrigido", f"tese “{a['lido'][:40]}”: lida {v[i]}, esperada {x}")
            a["valor"] = x
            usados.add(x)
        else:
            descartar.add(ix[i])
            if a.get("negrito"):
                alerta(a["pag"], "tese-descartada", f"“{a['lido'][:40]}”: {v[i]} fora da sequência ({ant}…{pos})")
    achados = [a for k, a in enumerate(achados) if k not in descartar]
    vistos = sorted(a["valor"] for a in achados if a["nivel"] == "tese")
    por_valor = {a["valor"]: a for a in achados if a["nivel"] == "tese"}
    for a_, b_ in zip(vistos, vistos[1:]):
        if b_ - a_ > 1:
            alerta(por_valor[b_]["pag"], "tese-pulada", f"faltam as teses {a_ + 1}–{b_ - 1} antes da {b_}")
    return achados


def resolve_teses(achados, alerta):
    """a numeracao das teses recomeca em cada PARTE: resolve cada segmento por si."""
    seg, out = [], []
    for a in achados:
        if a["nivel"] == "parte" and seg:
            out += _resolve_segmento(seg, alerta)
            seg = []
        seg.append(a)
    return out + _resolve_segmento(seg, alerta)


# ------------------------------------------------------------------ deteccao
def detecta(paginas, alerta):
    """lista de dicts (pag, ancora, nivel, valor, rotulo, titulo, resto-do-id) em ordem do livro."""
    achados, aparato = [], None
    for pg in paginas:
        if aparato is None and any(APARATO.search(norm(l.texto)) for l in pg.linhas[:3]):
            aparato = pg.imp
        if aparato is not None:
            continue
        ls, i, usadas = pg.corpo, 0, set()
        while i < len(ls):
            l = ls[i]
            r = reconhece_rotulo(l.texto) if pg.centrada(l) or not pg.col else None
            if r and r[0] != "artigo" and r[3] and re.search(r"[—–]|\s-+\s", l.texto):
                pg.cab = pg.cab or l.texto.strip()      # "CAPITULO IV — ATTRIBUTOS ..." e cabecalho corrente
                i += 1
                continue
            if r and not SUMARIO.match(l.texto):
                nivel, valor, palavra, resto = r
                partes, j = ([resto] if resto else []), i + 1
                while j < len(ls) and len(partes) < 4:
                    n = ls[j]
                    if len(n.texto.strip()) <= 3 or (pg.alt and n.y1 - n.y0 < 0.6 * pg.alt):
                        j += 1                    # ruido (ornamento, filete) entre rotulo e titulo
                        continue
                    if not pg.centrada(n) or reconhece_rotulo(n.texto) or SUMARIO.match(n.texto) \
                            or re.match(r"^\d{1,3}\s*[.,]\s", n.texto) or n.texto.strip().startswith("—"):
                        break
                    if pg.alt and n.y0 - ls[j - 1].y1 > (3.6 if not partes else 1.0) * pg.alt:
                        break
                    partes.append(n.texto.strip())
                    j += 1
                if re.fullmatch(r"[\W\d_]*", " ".join(partes)):
                    partes = []
                achados.append(dict(pag=pg.imp, ancora=l.texto.strip()[:30], nivel=nivel, valor=valor,
                                    palavra=palavra, titulo=" ".join(partes).strip(), lido=l.texto.strip()))
                i = j
                continue
            m = TESE.match(l.texto + " " + " ".join(x.texto for x in ls[i + 1:i + 3])) or TESE_TITULO.match(l.texto)
            if m and not pg.centrada(l):
                tit = (m.groupdict().get("t") or m.group(2)).strip()
                achados.append(dict(pag=pg.imp, ancora=l.texto.strip()[:30], nivel="tese", valor=int(m.group(1)),
                                    palavra=None, titulo=sem_marcas(tit), lido=l.texto.strip(),
                                    negrito=frac_rend(l.marc) >= 0.3))
            i += 1
    return achados, aparato


def numera(achados, alerta):
    """confere os numerais em sequencia, monta rotulos e ids; devolve as linhas do TSV."""
    prox = defaultdict(int)         # (pai) -> ultimo numero visto
    pilha = {}                      # nivel -> id
    nome_pai = {}
    linhas, usados = [], Counter()
    for a in achados:
        nv = a["nivel"]
        if nv == "tese":
            ident = f"t{a['valor']}"
            linhas.append([a["pag"], a["ancora"], "tese", str(a["valor"]), a["titulo"], ident, "auto"])
            continue
        lv = NIVEIS[nv]
        pai = next((pilha[k] for k, v in sorted(NIVEIS.items(), key=lambda kv: -kv[1])
                    if v < lv and k in pilha), "")
        for k in [k for k, v in NIVEIS.items() if v >= lv]:
            pilha.pop(k, None)
        chave = (nv, pai)
        esperado = prox[chave] + 1
        lido = a["valor"]
        if nv == "parte":                  # Metaphysica e Ethica numeram as suas partes cada uma
            valor = lido
        elif lido == esperado:
            valor = lido
        elif lido > esperado and lido <= esperado + 2:
            valor = lido
            alerta(a["pag"], f"{nv}-pulado", f"“{a['lido'][:40]}”: esperado {esperado}, lido {lido} (faltou um?)")
        else:
            valor = esperado
            alerta(a["pag"], "numero-corrigido", f"“{a['lido'][:40]}”: {nv} lido {lido}, esperado {esperado}")
        prox[chave] = valor
        for k in [k for k, v in NIVEIS.items() if v > lv]:      # filhos recomecam
            for ch in [c for c in prox if c[0] == k]:
                prox.pop(ch)
        palavra = a["palavra"] if lido == valor else None
        rot = rotulo_canonico(nv, valor, palavra)
        if nv == "artigo":
            base = f"{pai}.a{valor}" if pai else f"a{valor}"
        else:
            nome = slug(a["titulo"]) or {"parte": "parte", "seccao": "sec", "capitulo": "cap"}[nv] + str(valor)
            base = f"{pai}.{nome}" if pai else nome
        usados[base] += 1
        ident = base if usados[base] == 1 else f"{base}-{usados[base]}"
        if usados[base] > 1:
            alerta(a["pag"], "id-repetido", f"{base} já existe; usado {ident}")
        pilha[nv] = ident
        titulo = a["titulo"] or "-"
        if titulo == "-" and nv != "artigo":
            alerta(a["pag"], "sem-titulo", f"{rot}: bloco de título não encontrado")
        linhas.append([a["pag"], a["ancora"], nv, rot, titulo, ident, "auto"])
    return linhas


# ------------------------------------------------------------------ conferencia pelo cabecalho
def suaviza(votos, chaves, limites):
    """dentro de uma parte, (secao, capitulo) so cresce: a maior subsequencia nao decrescente fica,
    e o numeral mal lido (II por III) herda a chave vizinha."""
    seg = [sum(v[0] >= b for b in limites) for v in votos]
    out = list(chaves)
    for g in set(seg):
        ix = [i for i, x in enumerate(seg) if x == g]
        k = [(chaves[i][0] or 0, chaves[i][1]) for i in ix]
        m = len(ix)
        dp, ant = [1] * m, [-1] * m
        for i in range(m):
            for j in range(i):
                if k[j] <= k[i] and dp[j] + 1 > dp[i]:
                    dp[i], ant[i] = dp[j] + 1, j
        fim = max(range(m), key=lambda i: dp[i])
        cadeia = set()
        while fim != -1:
            cadeia.add(fim)
            fim = ant[fim]
        atual = None
        for n in range(m):
            if n in cadeia:
                atual = chaves[ix[n]]
            elif atual is not None:
                out[ix[n]] = atual
        prim = next((chaves[ix[n]] for n in range(m) if n in cadeia), None)
        for n in range(m):                       # votos antes do 1o da cadeia
            if n in cadeia:
                break
            out[ix[n]] = prim
    return out


def confere_cabecalhos(paginas, linhas, aparato, alerta):
    """cabecalho corrente votado por EXECUCOES de paginas (sem deslocar fronteiras): cada mudanca de
    (secao, capitulo) cai entre a ultima pagina com o cabecalho antigo (lo) e a primeira com o novo
    (hi); a pagina de abertura do capitulo nao tem cabecalho, entao o capitulo esta em [lo, hi]."""
    votos, sec = [], None
    for pg in paginas:
        if pg.cab and (aparato is None or pg.imp < aparato):
            h = le_cabecalho(pg.cab)
            if h.get("cap"):
                sec = h.get("secao") or sec
                votos.append((pg.imp, sec, h["cap"], norm(h["nome"])))
    if len(votos) < 5:
        return
    chaves = [(v[1], v[2]) for v in votos]
    liso = suaviza(votos, chaves, sorted(int(l[0]) for l in linhas if l[2] == "parte"))
    runs, ini = [], 0                                   # (lo, hi, chave, nome)
    for i in range(1, len(votos) + 1):
        if i == len(votos) or liso[i] != liso[i - 1]:
            nomes = Counter(v[3] for v in votos[ini:i] if len(v[3]) > 4)
            runs.append((votos[ini - 1][0] if ini else 0, votos[ini][0], liso[ini],
                         nomes.most_common(1)[0][0] if nomes else ""))
            ini = i
    caps = [l for l in linhas if l[2] == "capitulo"]
    for lo, hi, ch, nome in runs[1:]:
        if not any(lo - 2 <= int(c[0]) <= hi + 1 for c in caps):
            alerta(hi, "capitulo-esperado",
                   f"o cabeçalho passa a (secção {ch[0]}, cap. {ch[1]}) “{nome}” entre as pp. {lo}–{hi} "
                   f"e o TSV não tem capítulo aí")
    fronteiras = [(lo, hi, nome) for lo, hi, _, nome in runs[1:]]
    vm = votos[0][0], votos[-1][0]
    for c in caps:
        p = int(c[0])
        if vm[0] < p < vm[1] and not any(lo - 2 <= p <= hi + 1 for lo, hi, _ in fronteiras):
            alerta(p, "capitulo-fantasma", f"{c[3]} “{c[4]}”: o cabeçalho corrente não muda aqui")
            continue
        for lo, hi, nome in fronteiras:
            if lo <= p <= hi and nome and difflib.SequenceMatcher(None, norm(c[4]), nome).ratio() < 0.6:
                alerta(p, "nome-diverge", f"{c[3]}: título “{c[4]}”; o cabeçalho diz “{nome}” (sugestão)")


# ------------------------------------------------------------------ E/S
def le_tsv(caminho):
    if not Path(caminho).exists():
        return []
    with open(caminho, encoding="utf-8") as f:
        return [l.rstrip("\n").split("\t") for l in f if l.strip() and not l.startswith("#")]


def grava(caminho, linhas, cabeca=True):
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("# " + "\t".join(COLUNAS) + "\n")
        for l in linhas:
            f.write("\t".join(str(x) for x in l) + "\n")


def chave(l):
    return (str(l[0]), l[2], l[3])


def mede(prop, ouro):
    ouro = [l for l in ouro if len(l) >= 4]
    for nv in ("parte", "seccao", "capitulo", "artigo", "tese"):
        p = {chave(l) for l in prop if l[2] == nv}
        o = {chave(l) for l in ouro if l[2] == nv}
        tp = len(p & o)
        print(f"{nv:9s} proposta {len(p):4d}  ouro {len(o):4d}  acertos {tp:4d}  "
              f"precisão {tp / len(p) if p else 0:6.1%}  revocação {tp / len(o) if o else 0:6.1%}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vol", help="pasta do volume (vol1, vol2)")
    ap.add_argument("-f", "--de", type=int)
    ap.add_argument("-l", "--ate", type=int)
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--mede", action="store_true")
    a = ap.parse_args()

    vol = Path(a.vol)
    pasta = vol / "paginas"
    paginas = []
    for pid, imp, *_ in le_manifesto(pasta):
        imp = int(imp)
        if (a.de and imp < a.de) or (a.ate and imp > a.ate) or not (pasta / f"{pid}.tsv").exists():
            continue
        ls, larg = le_linhas(pasta / f"{pid}.tsv")
        paginas.append(Pagina(imp, ls, larg))
    alertas = []
    alerta = lambda p, t, m: alertas.append((p, t, m))

    achados, aparato = detecta(paginas, alerta)
    achados = resolve_teses(achados, alerta)
    linhas = numera(achados, alerta)
    confere_cabecalhos(paginas, linhas, aparato, alerta)
    alertas.sort(key=lambda x: (int(x[0]), x[1]))

    prop = vol / "estrutura.proposta.tsv"
    grava(prop, linhas)
    with open(vol / "estrutura.alertas.tsv", "w", encoding="utf-8") as f:
        f.write("pagina\ttipo\tmensagem\n")
        for p, t, m in alertas:
            f.write(f"{p}\t{t}\t{m}\n")
    c = Counter(l[2] for l in linhas)
    print(f"{prop}: {dict(c)}; aparato a partir da p. {aparato}; {len(alertas)} alertas "
          f"{dict(Counter(t for _, t, _ in alertas))}", file=sys.stderr)

    rev = le_tsv(vol / "estrutura.tsv")
    rev = [l for l in rev if len(l) >= 7]            # o formato antigo (caminho pág pág) nao conta
    if a.mede:
        mede(linhas, rev) if rev else print("sem estrutura.tsv revisado para medir", file=sys.stderr)
    if a.diff:
        antes, agora = {chave(l) for l in rev}, {chave(l) for l in linhas}
        with open(vol / "estrutura.diff.tsv", "w", encoding="utf-8") as f:
            for k in sorted(agora - antes, key=lambda k: int(k[0])):
                f.write("+\t" + "\t".join(k) + "\n")
            for k in sorted(antes - agora, key=lambda k: int(k[0])):
                f.write("-\t" + "\t".join(k) + "\n")


if __name__ == "__main__":
    main()
