#!/usr/bin/env python3
"""Correção automática do OCR sobre o TEI estruturado (antes da revisão F6).

    python3 tools/corrige_ocr.py vol2/vol2.estruturado.xml -o vol2/vol2.corrigido.xml
    python3 tools/corrige_ocr.py vol2/vol2.estruturado.xml -o /tmp/c.xml --sem lexico,a-grave
    python3 tools/mede_wer.py --corrige                       # portão: WER no padrão-ouro

Plano: .claude/plans/edicao-renovada/correcao-automatica.md §2-3.  Roda nos nós de texto do TEI
(fora de <fw>, <label> e de elementos xml:lang="la"/"fr") e grava, ao lado da saída,
correcoes.tsv: página, xml:id, antes, depois, regra.  Cada troca é auditável e reversível por
regra (--sem REGRA).  Três mecanismos, em ordem:

1. REGRAS de sequências impossíveis na grafia de 1916 (baratas, auditáveis, pegam o grosso):
   ao (-ào/-áo -> -ão), cao (-cáo -> -ção), oe (-óe -> -õe, só se a forma nova existe),
   a-grave (à -> á, às -> ás, À -> A), digito (6 -> é, 4 -> á entre palavras), deus
   (D??s -> Deus: versalete; a marcação sc vem de tools/formatacao.py), h-italico (pAysica -> physica),
   w (nowmeno -> noumeno), i-inicial (éntelligencia), acento-i (possível -> possivel), cedilha
   (forca -> força), enclitico (Provamolo -> Provamol-o), of (Of. -> Cf.), romano (IIT -> III),
   junta (in ferior -> inferior).
2. LEXICO: frequência do corpus (≈910 mil palavras, sem o padrão-ouro) + tabela de confusões
   genérica (c/e/o, acentos, u/n, i/t/í, s/z, A->h, w->u).  Troca quando o candidato é >= 10x mais
   frequente.  Nunca troca forma aceita pelo dicionário (pt_PT, fr: tools/dados/validas.tsv),
   nem palavra curta protegida, nem trecho que parece latim ou francês.
3. MARCA: palavra de confiança < 60 no .tsv do OCR, sem correção e fora do léxico: não muda,
   vai para correcoes.tsv com regra "marca" (dica para a F6).

O que fica deliberadamente para a F6 (precisa da imagem): a/á, E/E', e/o isolados, dígitos,
versalete e itálico duvidosos (a marcação automática vem de tools/formatacao.py, ver docs/06).
"""
import argparse
import csv
import re
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lexico  # noqa: E402
from corrige_w import NOMES_COM_W  # noqa: E402

TEI = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
TOKEN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+|\d+")
REGRAS = ("ao", "cao", "oe", "a-grave", "digito", "deus", "h-italico", "w", "i-inicial", "acento-i",
          "cedilha", "enclitico", "of", "romano", "junta", "lexico", "marca")
VOGAIS = "aeiouáéíóúâêôãõàè"

# confusoes do OCR (letra lida -> letras possiveis); genericas, nao aprendidas do padrao-ouro
CONF = {"à": "áâãa", "á": "àãâa", "a": "áàãâ", "ã": "áàa", "ä": "ãá", "è": "éêe", "é": "eêèi",
        "e": "cooéê", "c": "eoç", "o": "eóôõc", "ó": "oôõi", "ò": "óo", "í": "iì", "ì": "íi",
        "i": "íl", "t": "i", "l": "it", "ü": "ãu", "u": "nüú", "n": "uñ", "A": "h", "z": "s", "s": "z",
        "ç": "c", "f": "t", "r": "t", "x": "e", "w": "u"}
# formas curtas validas e ambiguas (o par minimo e comum): nunca pelo lexico
PROT = set("seria séria esta está estás este será serão e é ser sêr pôr por pela pelo pêlo cá ca "
           "nós nos vós vos dê de dá da só so então mas mais pois quae quão posto peste fé no elle "
           "elie formula".split())
LATIM = set("est et quod non in ad ut sed quae qui quam enim autem cum sicut ergo esse per vel ab "
            "ex sunt etiam nisi quia id hoc ipsa ipse ejus eius inter nam unde tamen dicitur potest "
            "omnis omne omnia sit ita aut atque nihil vero eo ea eorum quid ens entis secundum "
            "deo dei deum".split())
FRANCES = set("le les des du une dans pour pas sont nous cette il au aux ce qui est et sur avec "
              "par ne plus".split())
LATIM_FIM = re.compile(r"(orum|arum|ibus|tur|ntur|um|ae|que)$")


def sem_acento(w):
    return unicodedata.normalize("NFD", w.lower()).encode("ascii", "ignore").decode()


def estrangeiros(toks):
    """índices dos tokens em trecho latino/francês: >= 2 marcadores numa janela de +-5 palavras."""
    marca = []
    for t in toks:
        lw = t.lower()
        marca.append(lw in LATIM or lw in FRANCES or (len(lw) > 4 and LATIM_FIM.search(lw) is not None
                                                      and not lexico.valida(t)))
    out = set()
    for i in range(len(toks)):
        if sum(marca[max(0, i - 5):i + 6]) >= 2 and any(marca[max(0, i - 2):i + 3]):
            out.add(i)
    return out


class Corretor:
    def __init__(self, ativas=REGRAS, excluir_teste=True):
        self.ativas = set(ativas)
        self.freq = lexico.frequencias(excluir_teste)
        self.cache = {}

    def existe(self, w, minimo=5):
        return lexico.valida(w) or self.freq[w.lower()] >= minimo

    # --- 1. regras
    def regras(self, w):
        """(nova_forma, [regras]) para uma palavra."""
        feitas = []
        a = self.ativas
        if "cao" in a:                  # antes de "ao": -cáo -> -ção, nao -cão
            n = re.sub(r"(?<=[a-zà-ÿ])c[àá]o(s?)$", r"ção\1", w)
            n = re.sub(r"(?<=[a-zà-ÿ])c[óò]es$", "ções", n)
            if n != w and not lexico.valida(w):
                w, feitas = n, feitas + ["cao"]
            else:                       # -cão/-cões sem cedilha: so se a forma com cedilha existe
                n = re.sub(r"(?<=[a-zà-ÿ]{2})c(ão|ões)$", r"ç\1", w)
                if n != w and not lexico.valida(w) and self.existe(n):
                    w, feitas = n, feitas + ["cao"]
        if "ao" in a:
            n = re.sub(r"(?<=[a-zç])[àá]o(s?)$", r"ão\1", w)
            if n != w and not lexico.valida(w):
                w, feitas = n, feitas + ["ao"]
        if "oe" in a:                   # dóe/móe/róe sao validos em 1916: so se a forma nova existe
            n = re.sub(r"(?<=[a-z])[óò]e([sm]?)$", r"õe\1", w)
            if n != w and not lexico.valida(w) and self.existe(n):
                w, feitas = n, feitas + ["oe"]
        if "a-grave" in a and w in ("à", "às", "À"):
            w, feitas = {"à": "á", "às": "ás", "À": "A"}[w], feitas + ["a-grave"]
        # so o dicionario pt protege: "drus" (pl. de "dru") e valido em fr e bloqueava 655 Drus no vol. 2
        if "deus" in a and re.fullmatch(r"D[A-Za-z]{2}[sS]", w) and w not in ("Deus", "Deos") \
                and "pt" not in lexico.validas().get(w.lower(), ""):
            w, feitas = "Deus", feitas + ["deus"]
        if "h-italico" in a and re.search(r"(?<=[a-z])A(?=[a-z])", w):
            n = re.sub(r"(?<=[a-z])A(?=[a-z])", "h", w)
            if self.existe(n):
                w, feitas = n, feitas + ["h-italico"]
        if "w" in a and len(w) > 1 and "w" in w.lower() and not any(n.lower() in w.lower() for n in NOMES_COM_W):
            n = w.replace("w", "u").replace("W", "U")     # fora do latim: nowmeno, swbjectivos
            if lexico.valida(n) or self.freq[n.lower()] >= 30:   # ewtrinseca é extrinseca, não eutrinseca
                w, feitas = n, feitas + ["w"]
        if "i-inicial" in a and len(w) >= 5 and not lexico.valida(w):
            # i inicial em itálico lido como ó/é/z/t...: ómmanentismo, zncredulos, éimperfeitas
            lw = w.lower()
            for n in (("i" + w[1:]) if lw[0] in "óéúzítl" else None,
                      w[1:] if lw[0] in "óéz" and lw[1] == "i" else None):
                if n and self.freq[n.lower()] >= 5 and self.freq[n.lower()] >= 10 * max(self.freq[lw], 1):
                    w, feitas = (n[:1].upper() + n[1:]) if w[:1].isupper() else n, feitas + ["i-inicial"]
                    break
        if "acento-i" in a and re.search("[íú]", w):
            # í/ú que a grafia de 1916 não tem (possível, explícito, sabía): só se a forma sem acento
            # domina o corpus; í em hiato (país, saída) fica
            n = w.replace("í", "i").replace("ú", "u")
            lw = w.lower()
            hiato = re.search(f"[{VOGAIS}][íú]", lw) and not re.search("ía(s|m)?$", lw)
            if not hiato and self.freq[n.lower()] >= 10 and self.freq[n.lower()] >= 3 * max(self.freq[lw], 1):
                w, feitas = n, feitas + ["acento-i"]
        if "cedilha" in a and re.search("(?<=.)c[aou]", w):
            # c por ç (forca, mudanca, maconica): ç nunca é inicial; vale mesmo se a forma lida é
            # palavra (forca = patíbulo) quando a forma com ç é >= 10x mais frequente
            lw = w.lower()
            melhor = max((w[:m.start()] + "ç" + w[m.start() + 1:]
                          for m in re.finditer("(?<=.)c(?=[aou])", w)),
                         key=lambda c: self.freq[c.lower()], default=None)
            if melhor and self.freq[melhor.lower()] >= 30 \
                    and self.freq[melhor.lower()] >= 10 * max(self.freq[lw], 1):
                w, feitas = melhor, feitas + ["cedilha"]
        if "enclitico" in a and re.fullmatch(r"[A-Za-zà-ÿ]+[aeio]mol[oa]s?", w) \
                and not lexico.valida(w) and self.freq[w.lower()] < 3:
            w, feitas = re.sub(r"(mol)([oa]s?)$", r"\1-\2", w), feitas + ["enclitico"]    # Provamol-o
        return w, feitas

    # --- 2. lexico
    def candidatos(self, w):
        """[candidatos a 1 troca, candidatos a 2 trocas] pela tabela de confusões."""
        def um(xs):
            return {x[:i] + r + x[i + 1:] for x in xs for i, ch in enumerate(x) for r in CONF.get(ch, "")}
        c1 = um({w}) - {w}
        c2 = um(c1) - c1 - {w}
        return [c1, c2]

    def lexico(self, w):
        if w in self.cache:
            return self.cache[w]
        r = w
        lw = w.lower()
        c0 = self.freq[lw]
        if len(w) >= 3 and lw not in PROT and not lexico.valida(w) and not (w.isupper() and len(w) > 1):
            # palavra curta e frequente (eausa, 59x) só cede a candidato >= 20x mais frequente; forma
            # longa aceita candidato de 10 ocorrências (verifiear -> verificar)
            razao = 20 if (c0 >= 40 and len(w) < 8) else 10
            piso = 10 if len(w) >= 8 else 30
            # menos trocas primeiro: so passa a 2 trocas se nenhuma de 1 serve (ontro -> outro, nao entre)
            best = None
            for grupo in self.candidatos(w):
                b = max(grupo, key=lambda c: (self.freq[c.lower()], c), default=None)
                if b and self.freq[b.lower()] >= piso and self.freq[b.lower()] >= razao * max(c0, 1):
                    best = b
                    break
            difs = sum(x != y for x, y in zip(w, best)) if best else 0
            if best and c0 >= 10 and (
                    (sem_acento(w) == sem_acento(best) and not re.search("[àèìòù]", w))
                    or difs >= 2):
                # forma recorrente que difere so no acento (fórma/forma, áquella/aquella, tém/têm:
                # distincao da grafia antiga, decide a F6) ou em 2 letras (ceu -> con): nao troca
                best = None
            if best and self.freq[best.lower()] >= piso and self.freq[best.lower()] >= razao * max(c0, 1):
                r = best                     # os candidatos herdam a caixa da forma lida
                if w[:1].isupper() and not r[:1].isupper():
                    r = r[:1].upper() + r[1:]
        self.cache[w] = r
        return r

    # --- texto
    def fragmento(self, x):
        return not lexico.valida(x) and self.freq[x.lower()] < 20

    def pre(self, s, registra):
        """regras sobre o texto, antes das palavras: Of. -> Cf., romanos (IIT, 1I), palavra partida."""
        a = self.ativas
        if "of" in a:
            s = re.sub(r"\bOf\.", lambda m: (registra("Of.", "Cf.", "of"), "Cf.")[1], s)
        if "romano" in a:
            def romano(m):
                n = m.group(1) + "I" if m.group(1) else "I" + m.group(2)
                registra(m.group(), n, "romano")
                return n
            s = re.sub(r"(?<![\w.])([IVX]+I)T(?![\w])|(?<![\w.])1(I+)(?![\w])", romano, s)
        if "junta" in a:
            def junta(m):
                x, y = m.group(1), m.group(2)
                if x == "n" and y == "o":
                    n = "não"
                elif (self.fragmento(x) or self.fragmento(y)) and len(x) + len(y) >= 6 \
                        and self.freq[(x + y).lower()] >= 10:
                    n = x + y
                else:
                    return m.group()
                registra(m.group(), n, "junta")
                return n
            s = re.sub(r"(?<![A-Za-zÀ-ÿ])([A-Za-zÀ-ÿ]+) ([A-Za-zÀ-ÿ]+)(?![A-Za-zÀ-ÿ])", junta, s)
        return s

    def corrige(self, s, registra, baixa=frozenset(), antes="", depois=""):
        """antes/depois: texto vizinho em outros nós da mesma corrida (fronteira de <hi>), só
        como contexto: entra na janela do latim/francês e na regra digito, não é corrigido."""
        s = self.pre(s, registra)
        ext, d = antes + s + depois, len(antes)
        tx = list(TOKEN.finditer(ext))
        fora_x = estrangeiros([m.group() for m in tx])
        toks, fora = [], set()
        for j, m in enumerate(tx):
            if d <= m.start() and m.end() <= d + len(s):
                if j in fora_x:
                    fora.add(len(toks))
                toks.append(re.compile(re.escape(m.group())).match(s, m.start() - d))
        partes, pos = [], 0
        for i, m in enumerate(toks):
            w = m.group()
            novo, regras = w, []
            if i in fora:
                pass
            elif w.isdigit():
                if "digito" in self.ativas and w in ("6", "4") \
                        and re.search(r"[a-zà-ÿ,] $", ext[max(0, d + m.start() - 2):d + m.start()]) \
                        and re.match(r" [a-zà-ÿ]", ext[d + m.end():d + m.end() + 2]):
                    novo, regras = {"6": "é", "4": "á"}[w], ["digito"]
            else:
                novo, regras = self.regras(w)
                if "lexico" in self.ativas:
                    n2 = self.lexico(novo)
                    if n2 != novo:
                        novo, regras = n2, regras + ["lexico"]
                if not regras and "marca" in self.ativas and w in baixa and not self.existe(w, 3):
                    registra(w, w, "marca")
            if regras:
                registra(w, novo, "+".join(regras))
            partes.append(s[pos:m.start()])
            partes.append(novo)
            pos = m.end()
        partes.append(s[pos:])
        return "".join(partes)


def baixa_confianca(tsv, limiar=60):
    """formas de confiança < limiar numa página (do .tsv do tesseract)."""
    out = set()
    if not tsv.exists():
        return out
    with open(tsv, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["level"] == "5" and r["text"] and 0 <= float(r["conf"]) < limiar:
                for w in TOKEN.findall(r["text"]):
                    if sum(c.isalpha() for c in w) >= 3:
                        out.add(w)
    return out


def corridas(bloco, n=80):
    """{(no, "text"|"tail"): (antes, depois)} dos segmentos de texto de `bloco` ligados só por
    fronteiras de <hi> (formatação): o texto de um <hi> e o que o cerca são uma frase só.  Qualquer
    outro filho (<pb>, <note>, <fw>, <label>...) corta a corrida, como antes da formatação."""
    runs, atual = [], []

    def dentro(e):                      # e e um <hi>: seu texto, seus <hi> filhos e as caudas
        atual.append((e, "text"))
        for c in e:
            if c.tag == TEI + "hi":
                dentro(c)
            else:
                corta()
            atual.append((c, "tail"))

    def corta():
        nonlocal atual
        if atual:
            runs.append(atual)
        atual = []
    atual.append((bloco, "text"))
    for c in bloco:
        if isinstance(c.tag, str) and c.tag == TEI + "hi":
            dentro(c)
        else:
            corta()
        atual.append((c, "tail"))
    corta()
    out = {}
    for run in runs:
        if len(run) < 2:
            continue
        txt = [(getattr(e, campo) or "") for e, campo in run]
        for i, (e, campo) in enumerate(run):
            out[(e, campo)] = ("".join(txt[:i])[-n:], "".join(txt[i + 1:])[:n])
    return out


def corrige_arquivo(xml, saida, tsv_saida, quieto=False, ativas=REGRAS, excluir_teste=True):
    arv = etree.parse(str(xml))
    raiz = arv.getroot()
    cor = Corretor(ativas, excluir_teste)
    linhas, estado = [], {"pag": None, "baixa": frozenset()}
    base = Path(xml).resolve().parent

    def walk(el, pula, ident):
        if not isinstance(el.tag, str):
            return
        tag = el.tag
        if tag == TEI + "pb":
            estado["pag"] = el.get("n")
            facs = el.get("facs")
            estado["baixa"] = frozenset(baixa_confianca((base / facs).with_suffix(".tsv"))) \
                if facs and "marca" in cor.ativas else frozenset()
        ident = el.get(XML + "id") or ident
        pula = pula or tag in (TEI + "fw", TEI + "label", TEI + "teiHeader") or el.get(XML + "lang") in ("la", "fr")

        def reg(a, d, r):
            linhas.append((estado["pag"], ident, a, d, r))

        if tag != TEI + "hi":
            contexto.update(corridas(el))

        def ctx(e, campo):
            return contexto.get((e, campo), ("", ""))
        if el.text and not pula:
            el.text = cor.corrige(el.text, reg, estado["baixa"], *ctx(el, "text"))
        for c in el:
            walk(c, pula, ident)
            if c.tail and not pula:
                c.tail = cor.corrige(c.tail, reg, estado["baixa"], *ctx(c, "tail"))

    contexto = {}
    walk(raiz, False, None)
    rev = raiz.find(f"{TEI}teiHeader/{TEI}revisionDesc")
    if rev is not None:
        ch = etree.SubElement(rev, TEI + "change", when=date.today().isoformat())
        ch.text = f"Correção automática do OCR por tools/corrige_ocr.py (regras: {', '.join(sorted(cor.ativas))})."
    arv.write(str(saida), encoding="UTF-8", xml_declaration=True)
    if tsv_saida:
        with open(tsv_saida, "w", encoding="utf-8") as f:
            f.write("pagina\txml:id\tantes\tdepois\tregra\n")
            for l in linhas:
                f.write("\t".join(str(x or "") for x in l) + "\n")
    if not quieto:
        por = Counter(r for *_, r in linhas)
        trocas = sum(n for r, n in por.items() if r != "marca")
        print(f"{saida}: {trocas} trocas, {por.get('marca', 0)} marcas → {tsv_saida}", file=sys.stderr)
        print("  " + ", ".join(f"{r}: {n}" for r, n in por.most_common()), file=sys.stderr)
    return linhas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xml")
    ap.add_argument("-o", "--saida", required=True)
    ap.add_argument("--tsv", help="lista de trocas (padrão: correcoes.tsv ao lado da saída)")
    ap.add_argument("--sem", default="", help=f"regras a desligar, separadas por vírgula ({', '.join(REGRAS)})")
    ap.add_argument("--com-teste", action="store_true",
                    help="inclui as páginas dos padrões-ouro (lexico.TESTE) no léxico (não usar para medir)")
    a = ap.parse_args()
    sem = {x for x in a.sem.split(",") if x}
    if sem - set(REGRAS):
        sys.exit(f"regra desconhecida: {sem - set(REGRAS)}")
    saida = Path(a.saida)
    tsv = Path(a.tsv) if a.tsv else saida.parent / "correcoes.tsv"
    corrige_arquivo(Path(a.xml), saida, tsv, ativas=[r for r in REGRAS if r not in sem],
                    excluir_teste=not a.com_teste)


if __name__ == "__main__":
    main()
