#!/usr/bin/env python3
"""Revisão final de um .tex por LLM, uma chamada `claude -p` por página (sem ferramentas, 1 turno).

    python3 tools/revisa_paginas.py ENTRADA.tex --vol vol2 --modelo haiku --saida DIR
    python3 tools/revisa_paginas.py ENTRADA.tex --vol vol2 --modelo haiku --saida DIR --so 421,422
    python3 tools/revisa_paginas.py ENTRADA.tex --vol vol2 --saida DIR --seco      # só mostra os pedaços

Substitui o agente de capítulo inteiro de tools/revisa_trecho.sh, que relia o contexto todo (.tex do
capítulo + imagens + prompt de sistema do Claude Code) a cada um dos 50-170 turnos (um Edit por
correção) e consumia ~3 M tokens de cache por capítulo.  Aqui:

  * o .tex é cortado nos \\pg{N}; cada pedaço vai com as imagens das páginas que ele cobre
    (N até o próximo \\pg, mais as citadas por \\pgn dentro dele: notas que continuam);
  * cada página vai em duas metades (superior/inferior, com sobreposição), cinza, ≤ 1568 px — a
    resolução máxima que a API usa sem reduzir; a nota de rodapé fica legível;
  * as imagens vão embutidas na mensagem (--input-format stream-json), com --tools "" e prompt de
    sistema próprio (tools/prompts/revisao_pagina.md): um único turno, contexto ~5-25 k tokens;
  * o modelo devolve o pedaço inteiro em <tex>…</tex>; se os \\pg mudarem, as chaves desbalancearem
    ou o tamanho variar demais, o pedaço é rejeitado (fica o original) e marcado em resultado.json;
  * cada pedaço é gravado em DIR/paginas/ ao terminar: rodar de novo retoma (--refaz para refazer).

Saída em DIR: revisado.tex, relatorio.md (notas do modelo por pedaço), resultado.json (custo, chamadas,
tokens, falhas; mesmos campos que compara.py lê) e wer.txt (tools/mede_wer.py antes/depois).
"""
import argparse
import base64
import concurrent.futures as cf
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
PROMPT = RAIZ / "tools/prompts/revisao_pagina.md"
LADO_MAX = 1568          # a API reduz qualquer imagem cujo lado maior passe disto
SOBREPOE = 0.06          # fração da altura repetida nas duas metades
MINIMO = 300             # pedaço com menos texto que isto vai junto com o anterior
RE_PG = re.compile(r"\\pg\{(\d+)\}")
RE_PGN = re.compile(r"\\pgn\{(\d+)\}")


# ---------------------------------------------------------------- pedaços

def corta(tex):
    """Lista de (pagina, texto, paginas_das_imagens).  O preâmbulo vai com o primeiro pedaço;
    \\pg repetidos em seguida (pipeline) ficam no mesmo pedaço."""
    ms = list(RE_PG.finditer(tex))
    if not ms:
        sys.exit("o .tex não tem \\pg{N}")
    inicios, nums = [0], [int(ms[0][1])]
    for m in ms[1:]:
        n = int(m[1])
        if n != nums[-1]:
            inicios.append(m.start())
            nums.append(n)
    inicios.append(len(tex))
    # páginas só de nota (o corpo quase não tem texto entre dois \pg): juntam-se ao pedaço anterior,
    # que já traz a nota e as imagens dessas páginas
    i = 1
    while i < len(nums):
        miolo = RE_PG.sub("", tex[inicios[i]:inicios[i + 1]]).strip()
        if len(miolo) < MINIMO:
            del inicios[i], nums[i]
        else:
            i += 1
    pedacos = []
    for i, n in enumerate(nums):
        texto = tex[inicios[i]:inicios[i + 1]]
        prox = nums[i + 1] if i + 1 < len(nums) else n + 1
        pags = set(range(n, prox)) if prox > n else {n}
        pags |= {int(p) for p in RE_PGN.findall(texto)}
        pedacos.append((n, texto, sorted(pags)))
    return pedacos


def notas_e_corpo(texto):
    """(caracteres dentro de \\footnote{…}, caracteres fora), casando chaves."""
    dentro, i = 0, 0
    while (j := texto.find("\\footnote{", i)) >= 0:
        k, nivel = j + len("\\footnote{"), 1
        while k < len(texto) and nivel:
            nivel += {"{": 1, "}": -1}.get(texto[k], 0)
            k += 1
        dentro += k - j
        i = k
    return dentro, len(texto) - dentro


def valida(texto, novo):
    """None se a revisão preserva a estrutura; senão o motivo da recusa."""
    if RE_PG.findall(novo) != RE_PG.findall(texto):
        return f"os \\pg mudaram: {RE_PG.findall(texto)} → {RE_PG.findall(novo)}"
    if RE_PGN.findall(novo) != RE_PGN.findall(texto):
        return f"os \\pgn mudaram: {RE_PGN.findall(texto)} → {RE_PGN.findall(novo)}"
    if novo.count("\\footnote{") != texto.count("\\footnote{"):
        return f"número de \\footnote mudou: {texto.count(chr(92) + 'footnote{')} → {novo.count(chr(92) + 'footnote{')}"
    saldo = lambda s: s.count("{") - s.count("}")
    if saldo(novo) != saldo(texto):
        return f"chaves desbalanceadas: saldo {saldo(texto)} → {saldo(novo)}"
    # Linha reposta (o OCR perde muito a 1ª linha da página) só faz crescer uma parte; texto passado
    # entre corpo e nota faz uma crescer e a outra encolher.  Mudança grande demais também é recusada.
    # só contam as páginas com corpo: as de pura continuação de nota não têm 1ª linha a perder
    paginas = max(1, sum(1 for seg in RE_PG.split(texto)[2::2] if notas_e_corpo(seg)[1] > 100))
    (na, ca), (nb, cb) = notas_e_corpo(texto), notas_e_corpo(novo)
    # uma linha impressa tem ~90 caracteres: o corpo pode ganhar/perder ~1 linha por página; as notas,
    # poucas linhas (um parágrafo duplicado de outra página tem 500+ caracteres)
    for nome, a, b, lim in (("das notas", na, nb, max(0.02 * na, 200)),
                            ("do corpo", ca, cb, max(0.12 * ca, 180 * paginas))):
        if abs(b - a) > lim:
            return f"o texto {nome} mudou demais: de {a} para {b} caracteres (texto duplicado ou perdido?)"
    tol = lambda a: max(0.06 * a, 60)
    dc, dn = cb - ca, nb - na
    if (dc > tol(ca) and dn < -tol(na)) or (dc < -tol(ca) and dn > tol(na)):
        return (f"texto passou entre corpo e nota: corpo {ca} → {cb}, notas {na} → {nb} caracteres")
    return None


# ---------------------------------------------------------------- imagens

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


def mensagem(n, texto, pags, imagens, descricao, aviso=""):
    conteudo = []
    for p in pags:
        png = imagens / f"{p:04d}.png"
        if not png.exists():
            continue
        for nome, dados in zip(("metade superior", "metade inferior"), metades(png)):
            conteudo.append({"type": "text", "text": f"Página {p} — {nome}:"})
            conteudo.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": dados}})
    extra = ""
    if len(pags) > 1:
        extra = (f" As páginas {', '.join(map(str, pags[1:]))} vêm porque o trecho continua nelas "
                 "(nota de rodapé que prossegue, ou páginas só de nota). Delas use apenas o que pertence ao "
                 "trecho: o texto que vem depois do fim do trecho — inclusive notas que COMEÇAM nessas páginas "
                 "— é do trecho seguinte e não deve ser copiado.")
    conteudo.append({"type": "text", "text":
                     f"{descricao}. Trecho que começa na página {n}.{extra} Revise este trecho LaTeX contra as "
                     f"imagens e devolva-o corrigido no formato pedido.{' ' + aviso if aviso else ''}"
                     f"\n\n<entrada>\n{texto}</entrada>"})
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


def processa(ped, args, sistema, cwd, dirp):
    n, texto, pags = ped
    base = dirp / f"{n:04d}"
    js = base.with_suffix(".json")
    if js.exists() and not args.refaz:
        reg = json.loads(js.read_text())
        rej = base.with_suffix(".rejeitado.tex")
        if args.revalida and reg["falha"] and rej.exists():   # critério novo sobre a resposta já paga
            novo = rej.read_text(encoding="utf-8")
            if texto.endswith("\n") and not novo.endswith("\n"):
                novo += "\n"
            reg["falha"] = valida(texto, novo)
            if reg["falha"] is None:
                base.with_suffix(".revisado.tex").write_text(novo, encoding="utf-8")
                rej.unlink()
            js.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  p. {n}: revalidado → {reg['falha'] or 'ok'}", file=sys.stderr)
        return reg
    base.with_suffix(".entrada.tex").write_text(texto, encoding="utf-8")
    for f in (".revisado.tex", ".rejeitado.tex"):
        base.with_suffix(f).unlink(missing_ok=True)
    reg = {"pagina": n, "paginas": pags, "falha": None, "notas": "", "tentativas": [], "total_cost_usd": 0.0,
           "duration_ms": 0, "num_turns": 0, "usage": {}}
    aviso = ""
    for tentativa in range(args.tentativas):
        t0 = time.time()
        msg = mensagem(n, texto, pags, args.imagens, args.descricao, aviso)
        res = chama(msg, args.modelo, sistema, args.effort, cwd)
        resp = res.get("result") or ""
        m = re.search(r"<tex>\n?(.*?)\n?</tex>", resp, re.S)
        notas = re.search(r"<notas>\s*(.*?)\s*</notas>", resp, re.S)
        if res.get("is_error"):
            falha = "erro do claude: " + resp[:300]
        elif not m:
            falha = "resposta sem <tex>…</tex>"
        else:
            novo = m[1]
            if texto.endswith("\n") and not novo.endswith("\n"):
                novo += "\n"
            falha = valida(texto, novo)
        reg["total_cost_usd"] += res.get("total_cost_usd", 0) or 0
        reg["duration_ms"] += res.get("duration_ms") or int((time.time() - t0) * 1000)
        reg["num_turns"] += res.get("num_turns", 0) or 0
        for k, v in (res.get("usage") or {}).items():
            if isinstance(v, int):
                reg["usage"][k] = reg["usage"].get(k, 0) + v
        reg["tentativas"].append({"falha": falha, "notas": notas[1] if notas else "",
                                  "resposta": resp if (falha or not notas) else ""})
        reg["falha"], reg["notas"] = falha, notas[1] if notas else ""
        if falha is None:
            base.with_suffix(".revisado.tex").write_text(novo, encoding="utf-8")
            base.with_suffix(".rejeitado.tex").unlink(missing_ok=True)
            break
        if m:
            base.with_suffix(".rejeitado.tex").write_text(m[1], encoding="utf-8")
        if res.get("is_error") and "limit" in resp.lower():
            break                                 # limite de uso: não adianta repetir
        aviso = (f"ATENÇÃO: uma revisão anterior deste trecho foi recusada porque {falha}. Respeite as regras de "
                 "ESTRUTURA: mesmos \\pg, \\pgn e \\footnote, nos mesmos lugares; não passe texto entre corpo e nota.")
    js.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    u = reg["usage"]
    print(f"  p. {n} ({len(pags)} pp.): {'FALHOU: ' + reg['falha'] if reg['falha'] else 'ok'}"
          f"{' (2ª tentativa)' if len(reg['tentativas']) > 1 and not reg['falha'] else ''}  US$ {reg['total_cost_usd']:.3f}  "
          f"{reg['duration_ms'] / 1000:.0f}s  ent {u.get('input_tokens', 0) + u.get('cache_creation_input_tokens', 0) + u.get('cache_read_input_tokens', 0)}"
          f" saí {u.get('output_tokens', 0)}", file=sys.stderr, flush=True)
    return reg


# ---------------------------------------------------------------- principal

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", type=Path)
    ap.add_argument("--vol", required=True, choices=["vol1", "vol2"])
    ap.add_argument("--modelo", default="haiku")
    ap.add_argument("--saida", type=Path, required=True)
    ap.add_argument("--imagens", type=Path, help="padrão: VOL/paginas do checkout principal")
    ap.add_argument("--so", help="só estes pedaços (páginas iniciais), p. ex. 421,422 ou 421-425")
    ap.add_argument("--paralelo", type=int, default=1)
    ap.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--refaz", action="store_true", help="refaz pedaços já gravados")
    ap.add_argument("--tentativas", type=int, default=2, help="chamadas por pedaço se a revisão for recusada")
    ap.add_argument("--revalida", action="store_true",
                    help="reaplica o validador às respostas recusadas já gravadas (sem chamar o modelo)")
    ap.add_argument("--seco", action="store_true", help="só lista os pedaços, sem chamar o modelo")
    ap.add_argument("--descricao", default="Elementos de Philosophia")
    args = ap.parse_args()

    if args.imagens is None:
        comum = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=RAIZ,
                               capture_output=True, text=True).stdout.strip()
        cands = [RAIZ / args.vol / "paginas"] + ([Path(comum).parent / args.vol / "paginas"] if comum else [])
        args.imagens = next((c for c in cands if any(c.glob("0*.png"))), cands[0])
    args.descricao = f"{args.descricao}, {args.vol}"

    tex = args.entrada.read_text(encoding="utf-8")
    pedacos = corta(tex)
    assert "".join(t for _, t, _ in pedacos) == tex
    escolha = pedacos
    if args.so:
        quero = set()
        for parte in args.so.split(","):
            a, _, b = parte.partition("-")
            quero |= set(range(int(a), int(b or a) + 1))
        escolha = [p for p in pedacos if p[0] in quero]
    if args.seco:
        for n, t, pags in escolha:
            print(f"{n}: {len(t)} car., imagens {pags}")
        return

    args.saida.mkdir(parents=True, exist_ok=True)
    dirp = args.saida / "paginas"
    dirp.mkdir(exist_ok=True)
    (args.saida / "entrada.tex").write_text(tex, encoding="utf-8")
    sistema = PROMPT.read_text(encoding="utf-8")
    print(f">> {args.modelo}: {len(escolha)} pedaço(s) de {args.entrada} (imagens em {args.imagens})", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="revisa_paginas.") as cwd:   # fora do repo: sem CLAUDE.md do projeto
        with cf.ThreadPoolExecutor(args.paralelo) as ex:
            regs = list(ex.map(lambda p: processa(p, args, sistema, cwd, dirp), escolha))

    # junta: revisado onde houver, original no resto
    partes, todos = [], []
    for n, t, _ in pedacos:
        r = dirp / f"{n:04d}.revisado.tex"
        partes.append(r.read_text(encoding="utf-8") if r.exists() else t)
        j = dirp / f"{n:04d}.json"
        if j.exists():
            todos.append(json.loads(j.read_text()))
    (args.saida / "revisado.tex").write_text("".join(partes), encoding="utf-8")

    soma = lambda k: sum((r["usage"].get(k) or 0) for r in todos)
    resumo = {"modelo": args.modelo, "pedacos": len(pedacos), "feitos": len(todos),
              "falhas": {r["pagina"]: r["falha"] for r in todos if r["falha"]},
              "total_cost_usd": round(sum(r["total_cost_usd"] for r in todos), 4),
              "num_turns": sum(r["num_turns"] or 0 for r in todos),
              "duration_ms": sum(r["duration_ms"] for r in todos),
              "usage": {k: soma(k) for k in ("input_tokens", "cache_creation_input_tokens",
                                             "cache_read_input_tokens", "output_tokens")},
              "is_error": len(todos) < len(pedacos)}
    (args.saida / "resultado.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.saida / "relatorio.md").write_text(
        "\n".join(f"- p. {r['pagina']}{' **FALHOU: ' + r['falha'] + '**' if r['falha'] else ''}: {r['notas']}"
                  for r in sorted(todos, key=lambda r: r["pagina"])) + "\n", encoding="utf-8")

    p0, p1 = pedacos[0][0], max(max(p[2]) for p in pedacos)
    wer = []
    for f in ("entrada", "revisado"):
        r = subprocess.run([sys.executable, "tools/mede_wer.py", "--vol", args.vol, "--tex",
                            str((args.saida / f"{f}.tex").resolve()), "-f", str(p0), "-l", str(p1)],
                           cwd=RAIZ, capture_output=True, text=True)
        wer.append(f"== {f}\n{r.stdout}{r.stderr}")
    (args.saida / "wer.txt").write_text("".join(wer), encoding="utf-8")
    print(f">> {resumo['feitos']}/{resumo['pedacos']} pedaços, {len(resumo['falhas'])} falha(s), "
          f"US$ {resumo['total_cost_usd']:.2f}, {resumo['duration_ms'] / 6e4:.1f} min de chamadas; "
          f"tokens {resumo['usage']}", file=sys.stderr)
    print(f">> {args.saida}/revisado.tex  (wer.txt, relatorio.md, resultado.json)", file=sys.stderr)


if __name__ == "__main__":
    main()
