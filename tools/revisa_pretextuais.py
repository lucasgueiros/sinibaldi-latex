#!/usr/bin/env python3
"""Transcreve e formata os elementos PRÉ-TEXTUAIS de um volume com um LLM (Sonnet ou Haiku), página a página.

    python3 tools/revisa_pretextuais.py --vol vol1 [--modelo sonnet|haiku] [--paralelo 1]
    python3 tools/revisa_pretextuais.py --vol vol2 --so f003,f004 --refaz
    python3 tools/revisa_pretextuais.py --vol vol1 --seco          # só lista as páginas e o prompt

Uma chamada `claude -p` por página (sem ferramentas, 1 turno): imagens (duas metades) + texto bruto do OCR
(`volN/paginas/<id>.txt`, só rascunho) + a peça aberta até ali.  O modelo devolve a página como blocos
`<p type="…">` do dialeto do site (`web/obra/esquema.py`: `titulo-obra`, `centro`, `enderecamento`,
`saudacao`, `data-local`, `fecho`) e marca onde cada peça (rosto, imprimatur, prefácio, carta…) começa
(`<abre tipo titulo/>`).  Cada bloco passa por `esquema.validar_fragmento`; recusado, há 2ª chamada com o motivo.

Saída (versionada): `volN/pretextuais/paginas/<id>.{xml,json}` (resposta de cada página: retoma de onde parou) e
`volN/pretextuais.json` — as peças, prontas para `manage.py aplicar_pretextuais`.  Ver docs/11-pretextuais.md.
"""
import argparse
import concurrent.futures as cf
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

from lxml import etree

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))
sys.path.insert(0, str(RAIZ / "web"))
import revisa_paginas as rp                      # noqa: E402  (metades, chama: mesma chamada do `claude -p`)
from obra import esquema                          # noqa: E402

PROMPT = RAIZ / "tools/prompts/pretextuais.md"
ATE = {"vol1": 0, "vol2": 4}                      # última página impressa do pré-textual (docs/11)
XML_ID = esquema.qname_atributo("xml:id")
TIPOS_BLOCO_OK = {"p"}


def paginas_do_volume(vol, ate):
    """[(id do arquivo, página impressa)] do começo do volume até a página impressa `ate`."""
    with open(RAIZ / vol / "paginas" / "manifesto.tsv", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f, delimiter="\t"))
    return [(r["id"], int(r["impressa"])) for r in linhas if int(r["impressa"]) <= ate]


def le_resposta(resp):
    """Resposta do modelo -> (itens, notas, erros).  itens: ('abre', {tipo,titulo}) | ('p', Element) | ('vazia', motivo)."""
    m = re.search(r"<pagina>(.*?)</pagina>", resp, re.S)
    nc = re.search(r"<nota-continua>.*?</nota-continua>", resp, re.S)
    sem = re.search(r"<sem-texto\b[^>]*/>", resp)
    notas = re.search(r"<notas>\s*(.*?)\s*</notas>", resp, re.S)
    notas = notas[1] if notas else ""
    if not m:
        if sem:
            motivo = re.search(r'motivo="([^"]*)"', sem[0])
            return [("vazia", motivo[1] if motivo else "")], notas, []
        return [], notas, ["resposta sem <pagina>…</pagina> nem <sem-texto/>"]
    try:
        raiz = etree.fromstring(f"<pagina>{m[1]}</pagina>".encode("utf-8"))
    except etree.XMLSyntaxError as e:
        return [], notas, [f"XML malformado: {e}"]
    itens, erros = [], []
    for el in raiz:
        if not isinstance(el.tag, str):
            continue
        if el.tag == "abre":
            tipo, titulo = el.get("tipo", ""), " ".join((el.get("titulo") or "").split())
            if tipo not in esquema.PRETEXTUAIS:
                erros.append(f"<abre tipo={tipo!r}>: tipos aceitos {', '.join(esquema.PRETEXTUAIS)}")
            if not titulo:
                erros.append("<abre> sem titulo")
            itens.append(("abre", {"tipo": tipo, "titulo": titulo}))
        elif el.tag in TIPOS_BLOCO_OK:
            itens.append(("p", el))
        else:
            erros.append(f"elemento <{el.tag}> fora do formato (só <abre/> e <p>)")
    if raiz.text and raiz.text.strip():
        erros.append("texto solto fora de <p>")
    if nc:
        try:
            itens.append(("nota", etree.fromstring(nc[0].encode("utf-8"))))
        except etree.XMLSyntaxError as e:
            erros.append(f"<nota-continua> malformada: {e}")
    if not any(k == "p" for k, _ in itens):
        erros.append("página sem nenhum <p> (se não há texto impresso, responda <sem-texto/>)")
    return itens, notas, erros


def valida_blocos(itens):
    erros = []
    for k, el in itens:
        if k not in ("p", "nota"):
            continue
        for c in ([el] if k == "p" else list(el)):
            c = etree.fromstring(etree.tostring(c))
            c.attrib.pop("continua", None)
            xml = etree.tostring(c, encoding="unicode", with_tail=False)
            if k == "nota":      # as <p> da nota são validadas dentro de uma <note>
                xml = f'<p><note place="foot" n="1">{xml}</note></p>'
            for e in esquema.validar_fragmento(xml):
                erros.append(f"{xml[:60]}…: {e}")
    return erros


def normaliza_hi(el):
    """Desfaz `hi` dentro de `hi` do mesmo `rend` (prefácio todo em itálico): \\emph dentro de \\emph viraria romano."""
    for h in list(el.iter("hi")):
        pai = h.getparent()
        if pai is not None and not (h.text or len(h)):       # <hi/> vazio: some, o texto depois fica
            i, cauda = pai.index(h), h.tail or ""
            pai.remove(h)
            if i:
                pai[i - 1].tail = (pai[i - 1].tail or "") + cauda
            else:
                pai.text = (pai.text or "") + cauda
            continue
        if pai is None or not any(a.tag == "hi" and a.get("rend") == h.get("rend") for a in h.iterancestors()):
            continue
        i, texto, cauda, filhos = pai.index(h), h.text or "", h.tail or "", list(h)
        if i:
            pai[i - 1].tail = (pai[i - 1].tail or "") + texto
        else:
            pai.text = (pai.text or "") + texto
        pai.remove(h)
        for k, f in enumerate(filhos):
            pai.insert(i + k, f)
        if filhos:
            filhos[-1].tail = (filhos[-1].tail or "") + cauda
        elif i:
            pai[i - 1].tail = (pai[i - 1].tail or "") + cauda
        else:
            pai.text = (pai.text or "") + cauda
    return el


def xml_de(el):
    el = normaliza_hi(etree.fromstring(etree.tostring(el)))
    el.attrib.pop("continua", None)
    return etree.tostring(el, encoding="unicode", with_tail=False)


def serializa(k, el, rotulo):
    if k == "abre":
        return {"abre": el}
    if k == "vazia":
        return {"vazia": el}
    if k == "nota":
        return {"nota": [{"continua": c.get("continua") == "1", "xml": xml_de(c)} for c in el]}
    return {"rotulo": rotulo, "continua": el.get("continua") or "", "xml": xml_de(el)}


def abertos(reg):
    """Blocos da página anterior que podem continuar na seguinte: [(rótulo, começo, fim)] dos que não fecham frase."""
    out = []
    for it in (reg or {}).get("itens", []):
        if "xml" not in it:
            continue
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", it["xml"])).strip()
        if t and not re.search(r"[.!?:;»”)]$", t):
            out.append((it["rotulo"], t[:50], t[-70:]))
    return out


def mensagem(pid, impressa, imagens, texto_ocr, aberta, anterior, aviso=""):
    conteudo = []
    png = imagens / f"{pid}.png"
    for nome, dados in zip(("metade superior", "metade inferior"), rp.metades(png)):
        conteudo.append({"type": "text", "text": f"Página {impressa} (arquivo {pid}) — {nome}:"})
        conteudo.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": dados}})
    estado = (f"Peça aberta até aqui: {aberta['tipo']} — {aberta['titulo']}." if aberta
              else "Nenhuma peça aberta até aqui (esta página começa uma peça, ou é capa/guarda).")
    ab = abertos(anterior)
    estado += ("\n\nBlocos em aberto da página anterior (rótulo: começo … fim):\n"
               + "\n".join(f"  {r}: {a} … {b}" for r, a, b in ab)) if ab else "\n\nNenhum bloco em aberto da página anterior."
    conteudo.append({"type": "text", "text":
                     f"{estado}\n\nTexto bruto do OCR desta página (rascunho, com muitos erros):\n<ocr>\n{texto_ocr.strip()}\n"
                     f"</ocr>\n\nTranscreva a página no formato pedido.{chr(10) * 2 + aviso if aviso else ''}"})
    return {"type": "user", "message": {"role": "user", "content": conteudo}}


def processa(pid, impressa, aberta, anterior, args, sistema):
    base = args.saida / "paginas" / pid
    base.parent.mkdir(parents=True, exist_ok=True)
    js = base.with_suffix(".json")
    if js.exists() and not args.refaz:
        return json.loads(js.read_text(encoding="utf-8"))
    ocr_txt = (RAIZ / args.vol / "paginas" / f"{pid}.txt")
    texto_ocr = ocr_txt.read_text(encoding="utf-8", errors="replace") if ocr_txt.exists() else ""
    reg = {"id": pid, "pagina": impressa, "modelo": args.modelo, "falha": None, "notas": "", "tentativas": [],
           "custo_usd": 0.0}
    aviso = ""
    for tentativa in range(args.tentativas):
        t0 = time.time()
        res = rp.chama(mensagem(pid, impressa, args.imagens, texto_ocr, aberta, anterior, aviso), args.modelo, sistema,
                       args.effort, RAIZ)
        resp = res.get("result") or ""
        reg["custo_usd"] += float(res.get("total_cost_usd") or 0)
        if res.get("is_error"):
            erros, notas, itens = ["erro do claude: " + resp[:300]], "", []
        else:
            itens, notas, erros = le_resposta(resp)
            if not erros:
                erros = valida_blocos(itens)
        reg["tentativas"].append({"segundos": round(time.time() - t0, 1), "erros": erros})
        base.with_suffix(f".resp{tentativa + 1}.txt").write_text(resp, encoding="utf-8")
        if not erros:
            reg["notas"] = notas
            n = 0
            reg["itens"] = []
            for k, el in itens:
                n += k == "p"
                reg["itens"].append(serializa(k, el, f"{pid}.{n}"))
            break
        aviso = "Sua resposta anterior foi recusada: " + "; ".join(erros[:5]) + ". Corrija e responda de novo."
    else:
        reg["falha"] = "; ".join(erros[:5])
    js.parent.mkdir(parents=True, exist_ok=True)
    js.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    return reg


def _interno(el):
    s = etree.tostring(el, encoding="unicode", with_tail=False)
    m = re.match(r"<p\b[^>]*>(.*)</p>$", s, re.S)
    return m[1] if m else ""


def _abertura(el):
    return re.match(r"<p\b[^>]*?(?=/?>)", etree.tostring(el, encoding="unicode", with_tail=False))[0] + ">"


def junta(ant, novo, pb):
    """`novo` (<p>) continua `ant` (<p>) na página seguinte: um só <p> com o <pb/> no ponto da quebra.
    Palavra hifenizada no fim da página ('intelli-' + 'gentes') é refeita; senão entra um espaço."""
    a, b = _interno(ant), _interno(novo)
    hif = re.search(r"([A-Za-zÀ-ÿ])-((?:</hi>)*)$", a)
    ini = re.match(r"((?:<hi[^>]*>)*)([a-zà-ÿ])", b)
    if hif and ini:
        a, sep = a[:hif.start()] + hif[1] + hif[2], ""
    else:
        sep = "" if a.endswith(" ") or b.startswith(" ") else " "
    marca = etree.tostring(pb, encoding="unicode", with_tail=False) if pb is not None else ""
    return etree.fromstring(_abertura(ant) + a + sep + marca + b + "</p>")


def _pb(impressa, pid):
    pb = etree.Element("pb")
    pb.set("n", str(impressa))
    pb.set("facs", f"paginas/{pid}.png")
    return pb


def com_pb(el, pb):
    """`<p>` com o <pb/> no começo."""
    return etree.fromstring(_abertura(el) + etree.tostring(pb, encoding="unicode", with_tail=False) + _interno(el) + "</p>")


def junta_nota(peca, itens_nota, pb, avisos, pid, impressa):
    """Continuação de nota de rodapé (<nota-continua>): vai para a última <note> da peça."""
    for i in range(len(peca["blocos"]) - 1, -1, -1):
        bloco = etree.fromstring(peca["blocos"][i])
        notas = list(bloco.iter("note"))
        if notas:
            nota = notas[-1]
            break
    else:
        avisos.append(f"{pid}: <nota-continua> sem nota aberta na peça {peca['xml_id']}; entrou como parágrafo")
        for k, c in enumerate(itens_nota):
            el = etree.fromstring(c["xml"])
            peca["blocos"].append(etree.tostring(el, encoding="unicode"))
            peca["pag_blocos"].append(impressa)
        return
    for k, c in enumerate(itens_nota):
        el = normaliza_hi(etree.fromstring(c["xml"]))
        marca = pb if k == 0 else None
        ps = nota.findall("p")
        if k == 0 and c["continua"] and ps:
            novo = junta(ps[-1], el, marca)
            nota.replace(ps[-1], novo)
        else:
            nota.append(com_pb(el, marca) if marca is not None else el)
    peca["blocos"][i] = etree.tostring(bloco, encoding="unicode", with_tail=False)


def monta(vol, paginas, regs):
    """Registros por página (em ordem) -> (peças [{tipo, titulo, xml_id, paginas, blocos:[xml]}], avisos)."""
    n = int(vol[3:])
    pecas, usados, avisos, onde = [], {}, [], {}
    atual = None

    def nova_peca(tipo, titulo):
        nonlocal atual
        usados[tipo] = usados.get(tipo, 0) + 1
        xml_id = f"v{n}.pre-{tipo}" + (f"-{usados[tipo]}" if usados[tipo] > 1 else "")
        atual = {"tipo": tipo, "titulo": titulo, "xml_id": xml_id, "blocos": [], "pag_blocos": [], "paginas": []}
        pecas.append(atual)

    for (pid, impressa), reg in zip(paginas, regs):
        if reg.get("falha") or "itens" not in reg:
            continue
        primeiro = True
        for it in reg["itens"]:
            if "vazia" in it:
                continue
            if "abre" in it:
                nova_peca(it["abre"]["tipo"], it["abre"]["titulo"])
                continue
            if atual is None:                         # sem <abre> e sem peça aberta
                nova_peca("outro", "PEÇA PRÉ-TEXTUAL")
                avisos.append(f"{pid}: texto sem peça aberta; criada a peça {atual['xml_id']}")
            if "nota" in it:
                junta_nota(atual, it["nota"], _pb(impressa, pid), avisos, pid, impressa)
                primeiro = False
                continue
            el = normaliza_hi(etree.fromstring(it["xml"]))
            pb = _pb(impressa, pid)                   # só entra se o bloco atravessar a página
            alvo = onde.get(it["continua"]) if it["continua"] else None
            if it["continua"] and alvo is None:
                avisos.append(f"{pid}: continua={it['continua']!r} não existe; bloco entrou como novo")
            if alvo is not None:
                peca, i = alvo
                peca["blocos"][i] = etree.tostring(junta(etree.fromstring(peca["blocos"][i]), el, pb), encoding="unicode")
                onde[it["rotulo"]] = alvo
                dono = peca
            else:
                atual["blocos"].append(etree.tostring(el, encoding="unicode"))
                atual["pag_blocos"].append(impressa)
                onde[it["rotulo"]] = (atual, len(atual["blocos"]) - 1)
                dono = atual
            primeiro = False
            if impressa not in dono["paginas"]:
                dono["paginas"].append(impressa)
    return pecas, avisos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vol", required=True, choices=sorted(ATE))
    ap.add_argument("--modelo", default="sonnet", help="sonnet (padrão) ou haiku")
    ap.add_argument("--effort", default=None)
    ap.add_argument("--ate", type=int, help="última página impressa (padrão: %s)" % ATE)
    ap.add_argument("--so", help="ids de arquivo separados por vírgula (f003,0004)")
    ap.add_argument("--refaz", action="store_true")
    ap.add_argument("--seco", action="store_true")
    ap.add_argument("--tentativas", type=int, default=2)
    ap.add_argument("--saida", type=Path)
    ap.add_argument("--imagens", type=Path)
    ap.add_argument("--montar", action="store_true", help="só remonta volN/pretextuais.json das respostas já gravadas")
    args = ap.parse_args()
    args.saida = args.saida or RAIZ / args.vol / "pretextuais"
    dados = Path(os.environ.get("SINIBALDI_DADOS", RAIZ))
    args.imagens = args.imagens or dados / args.vol / "paginas"
    paginas = paginas_do_volume(args.vol, args.ate if args.ate is not None else ATE[args.vol])
    if args.seco:
        print(f"{len(paginas)} páginas, imagens em {args.imagens}")
        for pid, imp in paginas:
            print(f"  {pid}  p. {imp}  png={'ok' if (args.imagens / f'{pid}.png').exists() else 'FALTA'}")
        return
    sistema = PROMPT.read_text(encoding="utf-8")
    ids_so = set(args.so.split(",")) if args.so else None
    regs, aberta = [], None
    for pid, imp in paginas:                                # em ordem: cada página precisa da peça aberta
        if args.montar or (ids_so is not None and pid not in ids_so):
            js = args.saida / "paginas" / f"{pid}.json"
            reg = json.loads(js.read_text(encoding="utf-8")) if js.exists() else {"id": pid, "falha": "não rodada"}
        else:
            reg = processa(pid, imp, aberta, regs[-1] if regs else None, args, sistema)
            print(f"  {pid} (p. {imp}): {'FALHA ' + reg['falha'] if reg['falha'] else 'ok'}  ${reg['custo_usd']:.3f}",
                  file=sys.stderr)
        regs.append(reg)
        for it in reg.get("itens", []):
            if "abre" in it:
                aberta = it["abre"]
    pecas, avisos = monta(args.vol, paginas, regs)
    ate = args.ate if args.ate is not None else ATE[args.vol]
    extra = RAIZ / args.vol / "pretextuais.extra.json"      # peças curadas à mão (o modelo não as vê)
    if extra.exists():
        for p in json.loads(extra.read_text(encoding="utf-8"))["pecas"]:
            pecas.append(p)
            ate = max(ate, *p["pag_blocos"])
    saida = RAIZ / args.vol / "pretextuais.json"
    saida.write_text(json.dumps({"volume": int(args.vol[3:]), "modelo": args.modelo, "pecas": pecas, "avisos": avisos, "ate": ate,
                                 "falhas": [r["id"] for r in regs if r.get("falha")]},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(pecas)} peça(s) → {saida.relative_to(RAIZ)}; custo ${sum(r.get('custo_usd', 0) for r in regs):.3f}",
          file=sys.stderr)
    for a in avisos:
        print("  AVISO:", a, file=sys.stderr)
    for p in pecas:
        print(f"  {p['xml_id']:<24} {p['titulo']}  ({len(p['blocos'])} blocos, pp. {p['paginas']})", file=sys.stderr)


if __name__ == "__main__":
    main()
