#!/usr/bin/env python3
"""Formatação tipográfica por palavra, medida na IMAGEM: itálico, versalete e negrito.

    python3 tools/formatacao.py vol2/paginas                      # todas as páginas (paralelo)
    python3 tools/formatacao.py vol2/paginas -f 421 -l 442        # um trecho
    python3 tools/formatacao.py vol2/paginas --remede             # ignora o cache das medições
    python3 tools/formatacao.py vol2/paginas --treina-versalete   # gabaritos a partir do ouro

O tesseract (LSTM) não informa estilo, mas a caixa de cada palavra está no <id>.tsv e a imagem
no <id>.png (tools/extrai_paginas.py).  Por palavra mede-se:

  ang   inclinação dos traços: o ângulo de cisalhamento que mais "afina" a projeção vertical da
        tinta (soma dos quadrados do histograma de colunas).  Romano ≈ 0°, itálico ≈ 12–16°.
        Relativo à mediana da página (compensa scan torto).
  swr   espessura do traço (comprimento médio das corridas horizontais de tinta) relativa à
        mediana das palavras romanas da mesma linha-tipo (corpo × notas).  Negrito ≈ 1,4; o
        itálico deste livro é mais fino (≈ 0,8).
  vsc   versalete: para palavras da família "Deus/Dei/Deum" (o OCR lê DEUS versalete como
        "Dzvs", "Drus", "DEus"…), similaridade do recorte após a inicial com o gabarito
        versalete menos a com o gabarito minúsculo (tools/dados/versalete.json, treinado no
        padrão-ouro pp. 421-442 e reajustado por 2-médias em cada volume).  Fora dessa família:
        palavra que o OCR leu em maiúsculas no meio de linha minúscula e cujas letras após a
        inicial são baixas (≤ 0,82 da inicial).

Decisão: itálico por Viterbi de 2 estados na ordem de leitura da página, com a evidência de cada
palavra pesada pelo número de letras (palavra curta, "e", "o", "de", herda dos vizinhos só se a
evidência própria não contradiz); negrito e versalete por limiar.  Saída por página:
<id>.fmt.tsv (block par line word texto ang swr vsc rend), lida por tools/estruturar_tei.py.
Medição contra o padrão-ouro: tools/mede_formatacao.py.
"""
import argparse
import concurrent.futures as cf
import csv
import json
import os
import pickle
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

DADOS = Path(__file__).resolve().parent / "dados"
GABARITO = DADOS / "versalete.json"
TAN = np.tan(np.radians(np.arange(-12, 31, 1.0)))
I0 = 12                                   # indice do angulo 0
LETRA = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
NUCLEO = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ](?:.*[A-Za-zÀ-ÖØ-öø-ÿ])?")
ACENTO = re.compile("[áàâãéêíóôõúÁÀÂÃÉÊÍÓÔÕÚ]")
FAMILIA_DEUS = {"deus", "dei", "deum", "deo"}
CAMPOS = ("block", "par", "line", "word", "texto", "ang", "swr", "vsc", "rend")

# --- parametros da decisao (ajustados no padrao-ouro com tools/mede_formatacao.py)
# Medido em 2026-11-11 (vol2, pp. 421-442, 8807 palavras rotuladas): a logistica separa 99,85% das
# palavras de >= 4 letras; com o Viterbi, F1 do italico 97,9% / 95,4% em validacao cruzada
# (parametros escolhidos nas paginas impares e testados nas pares, e vice-versa).
P = dict(
    # logito do italico = w0 + w1*ang + w2*swr + w3*ang*swr  (ang em graus, swr relativo)
    logit=(45.2978, -3.6674, -57.712, 5.3169),
    logit_max=6.0,     # corta o logito (uma palavra nao decide sozinha a corrida)
    escala=2.0,        # logito / escala = evidencia
    peso=(0.3, 0.6, 0.3, 0.7, 1.0),   # peso da evidencia por n. de letras (1, 2, 3, 4, >=5)
    acento=0.0,        # palavra de 1-2 letras com acento (é, à, só): o acento inclinado engana
    troca=0.3,         # custo de mudar de estado (romano <-> italico) entre palavras
    vies=0.4,          # custo fixo do estado italico (o romano e o padrao)
    bold_sw=1.32,      # negrito: espessura relativa minima (>= 4 letras; romano p99,8 = 1,26)
    bold_sw_curta=1.42,  # palavra de 2-3 letras: mais grossa E vizinha de negrito longo
    bold_ang=4.0,      # e inclinacao maxima
    vsc_limiar=0.0,
)


# ------------------------------------------------------------------ medicao na imagem
def otsu(a):
    h = np.bincount(a.ravel(), minlength=256).astype(float)
    p = h / h.sum()
    w = np.cumsum(p)
    m = np.cumsum(p * np.arange(256))
    s = (m[-1] * w - m) ** 2 / (w * (1 - w) + 1e-12)
    return int(np.argmax(s))


def le_palavras(tsv):
    with open(tsv, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["level"] == "5" and r["text"].strip() and float(r["conf"]) >= 0:
                yield r


def inclinacao(ink):
    ys, xs = np.nonzero(ink)
    if len(xs) < 30:
        return float("nan")
    yu = ys.max() - ys
    melhor, im = -1.0, I0
    for i, t in enumerate(TAN):
        xp = np.round(xs - yu * t).astype(np.int64)
        c = np.bincount(xp - xp.min())
        s = float(np.dot(c, c))
        if s > melhor:
            melhor, im = s, i
    return float(np.degrees(np.arctan(TAN[im])))


def espessura(ink):
    corr = np.count_nonzero(ink[:, 1:] & ~ink[:, :-1]) + np.count_nonzero(ink[:, 0])
    return ink.sum() / corr if corr else float("nan")


def colunas_letras(ink, txt):
    """(c0, c1) das colunas com tinta, sem a pontuacao final."""
    cols = np.nonzero(ink.any(0))[0]
    if len(cols) < 8:
        return None
    c0, c1 = int(cols[0]), int(cols[-1])
    m = NUCLEO.search(txt)
    if m and m.end() < len(txt):
        vazias = [c for c in range(c0, c1) if not ink[:, c].any()]
        if vazias:
            c1 = max(c for c in range(c0, vazias[-1] + 1) if ink[:, c].any())
    return c0, c1


def vetor_versalete(ink, txt):
    """recorte apos a inicial, da altura da inicial, reamostrado a 30x14 (0..1)."""
    cc = colunas_letras(ink, txt)
    if cc is None:
        return None
    c0, c1 = cc
    L = c1 - c0 + 1
    n = len(NUCLEO.search(txt).group()) if NUCLEO.search(txt) else 1
    q = c0 + max(3, L // (n + 1))
    rc = np.nonzero(ink[:, c0:q].sum(1) >= 2)[0]
    if len(rc) < 5:
        return None
    sub = ink[rc[0]:rc[-1] + 1, c0 + int(0.28 * L):c1 + 1].astype(np.uint8) * 255
    if sub.size == 0:
        return None
    return np.asarray(Image.fromarray(sub).resize((30, 14), Image.BILINEAR), float).ravel() / 255


def baixas_apos_inicial(ink, txt):
    """altura do miolo das letras apos a inicial / altura da inicial (versalete ≈ 0,7)."""
    cc = colunas_letras(ink, txt)
    if cc is None:
        return None
    c0, c1 = cc
    L = c1 - c0 + 1
    n = max(1, len(txt))
    q = c0 + max(3, L // (n + 1))
    rc = np.nonzero(ink[:, c0:q].sum(1) >= 2)[0]
    resto = ink[:, q + 2:c1 + 1]
    if len(rc) < 5 or resto.shape[1] < 4:
        return None
    pr = resto.sum(1)
    on = np.nonzero(pr >= 0.3 * pr.max())[0]
    return (on[-1] - on[0] + 1) / (rc[-1] - rc[0] + 1)


def familia_deus(txt):
    t = re.sub(r"[^A-Za-zÀ-ÿ]", "", txt)
    if not t or t[0] != "D" or not 3 <= len(t) <= 4:
        return False
    tl = t.lower()
    if tl in FAMILIA_DEUS:
        return True
    # uma troca do OCR em "deus" (Dzvs tem duas: aceita 2 se as pontas batem)
    dif = sum(a != b for a, b in zip(tl, "deus")) + abs(len(tl) - 4)
    return len(tl) == 4 and (dif <= 1 or (dif == 2 and tl[-1] == "s")) and tl not in {"dous", "deve", "dahi", "dias", "dito", "diga", "dura", "dava"}


def mede_pagina(png, tsv):
    """lista de dicts (uma por palavra do .tsv) com caixa, texto e tracos brutos."""
    g = np.asarray(Image.open(png).convert("L"))
    th = otsu(g)
    out = []
    for r in le_palavras(tsv):
        x, y, w, h = (int(r[k]) for k in ("left", "top", "width", "height"))
        ink = g[y:y + h, x:x + w] < th
        txt = r["text"]
        d = dict(block=r["block_num"], par=r["par_num"], line=r["line_num"], word=r["word_num"],
                 texto=txt, x=x, y=y, w=w, h=h, letras=len(LETRA.findall(txt)))
        d["ang"] = inclinacao(ink) if d["letras"] else float("nan")
        d["sw"] = espessura(ink) if d["letras"] else float("nan")
        d["vec"] = vetor_versalete(ink, txt) if familia_deus(txt) else None
        d["baixas"] = None
        letras = re.sub(r"[^A-Za-zÀ-ÿ]", "", txt)
        if len(letras) >= 3 and letras[0].isupper() and sum(c.isupper() for c in letras[1:]) >= 2:
            d["baixas"] = baixas_apos_inicial(ink, txt)
        out.append(d)
    return out


# ------------------------------------------------------------------ decisao
def _mediana(v, padrao):
    v = [x for x in v if x == x]
    return float(np.median(v)) if v else padrao


def normaliza(ws):
    """ang relativo a mediana da pagina; sw relativo as romanas da mesma linha-tipo."""
    ang0 = _mediana([d["ang"] for d in ws if d["letras"] >= 4], 0.0)
    for d in ws:
        d["ang_r"] = d["ang"] - ang0 if d["ang"] == d["ang"] else float("nan")
    # linha-tipo: altura da caixa das palavras (corpo ~ notas) -> 2 grupos pelo corte da mediana
    rom = [d for d in ws if d["letras"] >= 4 and d["ang_r"] == d["ang_r"] and d["ang_r"] < 4]
    hs = sorted(d["h"] for d in rom)
    corte = None
    if len(hs) > 40:
        lo, hi = hs[len(hs) // 5], hs[4 * len(hs) // 5]
        if hi - lo >= 4:
            corte = (lo + hi) / 2
    grupos = {}
    for d in rom:
        grupos.setdefault(corte is not None and d["h"] >= corte, []).append(d["sw"])
    ref = {k: _mediana(v, 1.0) for k, v in grupos.items()}
    geral = _mediana([d["sw"] for d in rom], 1.0)
    for d in ws:
        k = corte is not None and d["h"] >= corte
        d["swr"] = d["sw"] / ref.get(k, geral) if d["sw"] == d["sw"] else float("nan")


def evidencia(d):
    """(e, peso): e > 0 favorece italico."""
    if not d["letras"] or d["ang_r"] != d["ang_r"] or d["swr"] != d["swr"]:
        return 0.0, 0.0
    a, sw = float(np.clip(d["ang_r"], -6, 22)), float(np.clip(d["swr"], 0.5, 1.6))
    w0, w1, w2, w3 = P["logit"]
    e = float(np.clip(w0 + w1 * a + w2 * sw + w3 * a * sw, -P["logit_max"], P["logit_max"])) / P["escala"]
    n = d["letras"]
    peso = P["peso"][min(n, 5) - 1]
    if n <= 2 and ACENTO.search(d["texto"]):
        peso *= P["acento"]
    return e, peso


def viterbi(ws):
    """estado (0 romano, 1 italico) por palavra, na ordem dada."""
    n = len(ws)
    if not n:
        return []
    custo = np.zeros((n, 2))
    for i, d in enumerate(ws):
        e, p = evidencia(d)
        custo[i, 0] = p * e
        custo[i, 1] = -p * e + P["vies"]
    acc = custo[0].copy()
    trás = np.zeros((n, 2), int)
    for i in range(1, n):
        novo = np.empty(2)
        for s in (0, 1):
            fica, muda = acc[s], acc[1 - s] + P["troca"]
            trás[i, s] = s if fica <= muda else 1 - s
            novo[s] = min(fica, muda) + custo[i, s]
        acc = novo
    s = int(np.argmin(acc))
    est = [0] * n
    for i in range(n - 1, -1, -1):
        est[i] = s
        s = trás[i, s]
    return est


def carrega_gabarito():
    if GABARITO.exists():
        g = json.loads(GABARITO.read_text())
        return np.array(g["sc"]), np.array(g["rom"])
    return None


def ajusta_gabarito(vetores, gab):
    """2-medias semeado pelo gabarito: adapta ao volume (outra impressao, outra tinta)."""
    if gab is None or len(vetores) < 20:
        return gab
    V = np.array(vetores)
    cs, cr = gab
    for _ in range(8):
        m = V @ (cs - cr) - (cs @ cs - cr @ cr) / 2 > 0
        if m.sum() < 5 or (~m).sum() < 5:
            break
        cs, cr = V[m].mean(0), V[~m].mean(0)
    return cs, cr


def decide(ws, gab):
    normaliza(ws)
    est = viterbi(ws)
    def grossa(d, limiar):
        return d["swr"] == d["swr"] and d["swr"] >= limiar and (d["ang_r"] != d["ang_r"] or d["ang_r"] < P["bold_ang"])
    longa = [d["letras"] >= 4 and grossa(d, P["bold_sw"]) for d in ws]
    for i, (d, s) in enumerate(zip(ws, est)):
        rend = ""
        if d["letras"]:
            if s:
                rend = "it"
            if longa[i] or (2 <= d["letras"] <= 3 and grossa(d, P["bold_sw_curta"])
                            and ((i and longa[i - 1]) or (i + 1 < len(ws) and longa[i + 1]))):
                rend = "bold"
        d["vsc"] = float("nan")
        if d.get("vec") is not None and gab is not None:
            cs, cr = gab
            v = d["vec"]
            d["vsc"] = float(-np.sum((v - cs) ** 2) + np.sum((v - cr) ** 2))
            inclinada = d["ang_r"] == d["ang_r"] and d["ang_r"] >= 8      # *Dei Filius*: italico
            if d["vsc"] > P["vsc_limiar"] and rend != "bold" and not inclinada:
                rend = "sc"
        elif d.get("baixas") is not None and d["baixas"] <= 0.82 and rend == "":
            d["vsc"] = 1.0 - d["baixas"]
            rend = "sc"
        d["rend"] = rend
    # versalete fora da familia "Deus" so vale em linha minuscula (titulos em caixa alta nao)
    linhas = {}
    for d in ws:
        linhas.setdefault((d["block"], d["par"], d["line"]), []).append(d)
    for ls in linhas.values():
        minus = sum(1 for d in ls if d["letras"] >= 3 and d["texto"][:1].islower())
        if minus < max(2, len(ls) // 3):
            for d in ls:
                if d["rend"] == "sc" and d.get("vec") is None:
                    d["rend"] = ""
    return ws


# ------------------------------------------------------------------ E/S
def grava(caminho, ws):
    tmp = caminho.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\t".join(CAMPOS) + "\n")
        for d in ws:
            vals = []
            for c in CAMPOS:
                v = d.get(c, "")
                if isinstance(v, float):
                    v = "" if v != v else f"{v:.3f}"
                vals.append(str(v).replace("\t", " "))
            f.write("\t".join(vals) + "\n")
    tmp.rename(caminho)


def le_fmt(caminho):
    """{(block, par, line, word): rend} de um <id>.fmt.tsv (vazio se nao existe)."""
    out = {}
    if not Path(caminho).exists():
        return out
    with open(caminho, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["rend"]:
                out[(r["block"], r["par"], r["line"], r["word"])] = r["rend"]
    return out


def _trabalho(args):
    """medidas de uma pagina, do cache <id>.medidas.pkl (git-ignored) se mais novo que png e tsv."""
    png, tsv, cache, remede = args
    if not remede and cache.exists() and cache.stat().st_mtime >= max(png.stat().st_mtime, tsv.stat().st_mtime):
        with open(cache, "rb") as f:
            return pickle.load(f)
    ws = mede_pagina(png, tsv)
    for d in ws:                        # o vetor vai junto (para o 2-medias do volume)
        if d["vec"] is not None:
            d["vec"] = d["vec"].astype(np.float32)
    tmp = cache.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(ws, f)
    tmp.rename(cache)
    return ws


def mede(pasta, imgs, pags, jobs=1, remede=False, quieto=False):
    """{pid: [medidas]} das paginas, em paralelo."""
    medidas = {}
    args = {pid: (imgs / f"{pid}.png", pasta / f"{pid}.tsv", pasta / f"{pid}.medidas.pkl", remede) for pid, _ in pags}
    with cf.ProcessPoolExecutor(jobs) as ex:
        futs = {ex.submit(_trabalho, x): pid for pid, x in args.items()}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            medidas[futs[fut]] = fut.result()
            if not quieto and (i % 100 == 0 or i == len(futs)):
                print(f"  {i}/{len(futs)} páginas medidas", file=sys.stderr)
    return medidas


def paginas(pasta, de, ate):
    with open(pasta / "manifesto.tsv", encoding="utf-8") as f:
        next(f)
        for l in f:
            pid, imp = l.split("\t")[:2]
            imp = int(imp)
            if (de and imp < de) or (ate and imp > ate):
                continue
            if (pasta / f"{pid}.tsv").exists():
                yield pid, imp


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pasta", help="volN/paginas (manifesto.tsv + <id>.tsv)")
    ap.add_argument("--imagens", help="onde estão os <id>.png (padrão: a própria pasta)")
    ap.add_argument("-f", "--de", type=int)
    ap.add_argument("-l", "--ate", type=int)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--remede", action="store_true", help="refaz as medições mesmo com cache")
    ap.add_argument("--treina-versalete", action="store_true",
                    help="aprende tools/dados/versalete.json no padrão-ouro (vol2, pp. 421-442)")
    ap.add_argument("--ouro", default="vol2/02_parte_theodicea/01_cap_existencia-de-deus.tex")
    a = ap.parse_args()
    pasta = Path(a.pasta)
    imgs = Path(a.imagens) if a.imagens else pasta
    if a.treina_versalete:
        a.de, a.ate = a.de or 421, a.ate or 442
    pags = [(pid, imp) for pid, imp in paginas(pasta, a.de, a.ate)]
    falta = [pid for pid, _ in pags if not (imgs / f"{pid}.png").exists()]
    if falta:
        sys.exit(f"faltam {len(falta)} imagens em {imgs} (ex.: {falta[:3]}); rode tools/extrai_paginas.py")
    medidas = mede(pasta, imgs, pags, a.jobs, a.remede)
    if a.treina_versalete:
        treina(pasta, pags, medidas, a.ouro)
        return
    gab = carrega_gabarito()
    vetores = [d["vec"] for ws in medidas.values() for d in ws if d["vec"] is not None]
    gab = ajusta_gabarito(vetores, gab)
    from collections import Counter
    tot = Counter()
    for pid, _ in pags:
        ws = decide(medidas[pid], gab)
        tot.update(d["rend"] for d in ws if d["rend"])
        grava(pasta / f"{pid}.fmt.tsv", ws)
    print(f"{len(pags)} páginas → <id>.fmt.tsv; palavras marcadas: {dict(tot)}", file=sys.stderr)


def treina(pasta, pags, medidas, ouro):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mede_formatacao as mf
    rot = mf.rotula(ouro, pasta, min(i for _, i in pags), max(i for _, i in pags))
    sc, rom = [], []
    for pid, imp in pags:
        for d in medidas[pid]:
            if d["vec"] is None:
                continue
            l = rot.get((imp, (d["block"], d["par"], d["line"], d["word"])))
            if l == "sc":
                sc.append(d["vec"])
            elif l == "rom":
                rom.append(d["vec"])
    if len(sc) < 10 or len(rom) < 10:
        sys.exit(f"exemplos insuficientes: {len(sc)} versalete, {len(rom)} romano")
    DADOS.mkdir(exist_ok=True)
    GABARITO.write_text(json.dumps({
        "fonte": f"{ouro} (rotulos), {len(sc)} versalete / {len(rom)} romano; recorte 30x14 apos a inicial",
        "sc": [round(float(x), 4) for x in np.mean(sc, 0)],
        "rom": [round(float(x), 4) for x in np.mean(rom, 0)]}))
    print(f"{GABARITO}: {len(sc)} versalete, {len(rom)} romano", file=sys.stderr)


if __name__ == "__main__":
    main()
