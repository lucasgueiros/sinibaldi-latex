#!/usr/bin/env python3
"""Testes de tools/gera_slides.py.

    python3 -m unittest tools/test_gera_slides.py        # da raiz do repositório
    cd tools && python3 -m unittest test_gera_slides

Cobrem: silogismo, falso positivo de Ora/Logo, definição, divisão, subdivisões, `p type=` explícito,
paginação, escapes (LaTeX e início de linha), determinismo, `validar` e preservação integral do texto.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gera_slides as g  # noqa: E402

NS = 'xmlns="http://www.tei-c.org/ns/1.0"'


def tei(corpo, ns=True):
    return (f'<?xml version="1.0" encoding="UTF-8"?><TEI {NS if ns else ""}><text><body>'
            f'{corpo}</body></text></TEI>')


def tese(n, *ps, extra=""):
    return f'<div type="tese" n="{n}" xml:id="t{n}">' + "".join(ps) + extra + "</div>"


def fonte_de(corpo, **kw):
    return g.tei_para_fonte(tei(corpo), **kw)


def slides_de(corpo, **kw):
    sl, _ = g._constroi(tei(corpo), **kw)
    return sl


def tipos(corpo, **kw):
    return [s.tipo for s in slides_de(corpo, **kw)]


def texto_corpo(sl):
    return " ".join(it.r.plano for it in sl.corpo)


# ---------------------------------------------------------------- referência independente de palavras
def palavras_referencia(xml):
    """palavras dos <p> do corpo (sem notas, fw, argument, label), na ordem; <pb> separa palavras."""
    from lxml import etree
    raiz = etree.fromstring(xml if isinstance(xml, bytes) else xml.encode("utf-8"),
                            etree.XMLParser(huge_tree=True))
    out = []

    def ln(e):
        return e.tag.split("}")[-1] if isinstance(e.tag, str) else None

    def texto(e):
        partes = [e.text or ""]
        for c in e:
            if ln(c) in ("note", "fw", "label"):
                pass
            elif ln(c) == "pb":
                partes.append(" ")
            else:
                partes.append(texto(c))
            partes.append(c.tail or "")
        return "".join(partes)

    corpo = next((e for e in raiz.iter() if ln(e) == "body"), raiz)
    for p in corpo.iter():
        if ln(p) != "p":
            continue
        if any(ln(a) in ("note", "argument") for a in p.iterancestors()):
            continue
        out.extend(re.findall(r"\w+", texto(p)))
    return out


def palavras_geradas(slides):
    corpo, cons = [], []
    for s in slides:
        if s.tipo in ("capa", "secao"):
            continue
        for it in s.corpo:
            corpo.extend(re.findall(r"\w+", it.r.plano))
            if it.kind == "rot":
                pass
        for c in s.consumidos:
            cons.extend(re.findall(r"\w+", c))
    return corpo, cons


def confere_texto(xml, slides):
    """-> lista de problemas (vazia = todas as palavras da referência estão nos slides, em ordem)."""
    ref = palavras_referencia(xml)
    corpo, cons = palavras_geradas(slides)
    from collections import Counter
    pool = Counter(cons)
    i = 0
    perdidas = []
    for w in ref:
        if i < len(corpo) and corpo[i] == w:
            i += 1
        elif pool[w] > 0:
            pool[w] -= 1
        else:
            perdidas.append(w)
    sobras = len(corpo) - i
    prob = []
    if perdidas:
        prob.append(f"perdidas: {perdidas[:15]} (total {len(perdidas)})")
    if sobras:
        prob.append(f"sobraram {sobras} palavras no corpo: {corpo[i:i + 10]}")
    return prob


class Silogismo(unittest.TestCase):
    P = ('<p><label>5.</label> <hi rend="bold">Tese de teste.</hi> — texto inicial.</p>'
         '<p>a) Todo ente composto de partes <hi rend="it">dissolve-se</hi>. Ora a alma não é composta. '
         'Logo a alma não se dissolve.</p>')

    def test_maior_menor_conclusao(self):
        f = fonte_de(tese(5, self.P))
        self.assertIn("=== argumento", f)
        self.assertIn("Maior:: Todo ente composto de partes *dissolve-se*.", f)
        self.assertIn("Menor:: a alma não é composta.", f)
        self.assertIn("Conclusão:: a alma não se dissolve.", f)

    def test_so_logo_vira_premissa(self):
        f = fonte_de(tese(6, '<p><label>6.</label> <hi rend="bold">X.</hi> — y.</p>'
                             '<p>b) A virtude é um habito. Logo a virtude se adquire.</p>'))
        self.assertIn("Premissa:: A virtude é um habito.", f)
        self.assertIn("Conclusão:: a virtude se adquire.", f)

    def test_polissilogismo(self):
        f = fonte_de(tese(7, '<p><label>7.</label> <hi rend="bold">Z.</hi> — w.</p>'
                             '<p>a) A é B. Ora C é A. Logo C é B. Ora D é C. Logo D é B.</p>'))
        self.assertEqual(f.count("Conclusão::"), 2)
        self.assertEqual(f.count("Menor::"), 2)

    def test_ora_logo_no_meio_da_frase_nao_sao_clausulas(self):
        self.assertIsNone(g.silogismo(g.r_de("A alma, ora ativa, ora passiva, existe; e logo se vê.")))
        self.assertIsNone(g.silogismo(g.r_de("Chegou logo que pôde, e foi embora. Hora de partir.")))
        self.assertIsNone(g.silogismo(g.r_de("Logo que o homem pensa, existe.")))
        self.assertIsNone(g.silogismo(g.r_de("Ora, isto basta.")))      # Ora sem Logo

    def test_logo_que_nao_conta(self):
        fr = fonte_de(tese(8, '<p><label>8.</label> <hi rend="bold">Q.</hi> — r.</p>'
                              '<p>a) Quando o sol nasce, as aves cantam. Logo que ele nasce, tudo desperta.</p>'))
        self.assertNotIn("\nConclusão::", fr)


class Classificacao(unittest.TestCase):
    def test_definicao_com_titulo(self):
        sl = slides_de(tese(29, '<p><label>29.</label> <hi rend="bold">Simplicidade da alma.</hi> — '
                                '<hi rend="it">Simplicidade</hi> é a propriedade, pela qual a alma não é composta '
                                'de partes. Outra frase.</p>'))
        d = [s for s in sl if s.tipo == "definicao"]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0].titulo, "29. Simplicidade da alma")
        self.assertEqual(d[0].corpo[0].kind, "!")
        f = g._escreve_slides(d)
        self.assertIn("! **Simplicidade** é a propriedade", f)

    def test_definicao_por_titulo(self):
        self.assertIn("definicao", tipos(tese(1, '<p><label>1.</label> <hi rend="bold">Noção de ser.</hi> — '
                                                 'O ser consiste naquilo que existe, de algum modo.</p>')))

    def test_divisao(self):
        sl = slides_de(tese(30, '<p><label>30.</label> <hi rend="bold">Divisão.</hi> — Divide-se a '
                                '<hi rend="it">simplicidade</hi> em <hi rend="it">absoluta</hi> e '
                                '<hi rend="it">relativa</hi>, segundo exclua toda composição. — A simplicidade '
                                'absoluta pertence só a Deus, que é puro acto — a simplicidade relativa pertence '
                                'à alma humana, composta de essência e existência.</p>'))
        d = [s for s in sl if s.tipo == "divisao"]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0].corpo[0].kind, "!")
        self.assertTrue(any(it.kind == "-" for it in d[0].corpo))

    def test_objecao_resposta_corolario_escolio_observacao(self):
        ps = ('<p><label>9.</label> <hi rend="bold">Tese.</hi> — Algo.</p>'
              '<p>Objecção. Dizem que a alma é material, porque o pensamento depende do cérebro.</p>'
              '<p>Respondemos que o pensamento depende só extrinsecamente do cérebro.</p>'
              '<p>Corollario. A alma é imortal, por ser simples e espiritual.</p>'
              '<p>Escholio. Os antigos já o disseram, e S. Thomás o confirma.</p>'
              '<p>Nota-se que a simplicidade não é perfeição absoluta.</p>')
        t = tipos(tese(9, ps))
        for esperado in ("objecao", "resposta", "corolario", "escolio", "observacao"):
            self.assertIn(esperado, t)

    def test_citacao_latina(self):
        lat = ("Anima humana, quae dicitur intellectus vel mens, est quiddam incorporeum et subsistens, quod "
               "non est corpus nec potest esse.")
        self.assertIn("citacao", tipos(tese(2, f'<p><label>2.</label> <hi rend="bold">T.</hi> — a.</p><p>{lat}</p>')))

    def test_texto_comum_fica_texto(self):
        t = tipos(tese(3, '<p><label>3.</label> <hi rend="bold">T.</hi> — a.</p>'
                          '<p>O gato dorme no sofá da sala durante toda a tarde de domingo.</p>'))
        self.assertIn("texto", t)

    def test_p_type_explicito_manda(self):
        # sem o tipo, esta frase seria `texto`
        base = '<p>O gato dorme no sofá durante a tarde.</p>'
        for tp, esperado in (("definicao", "definicao"), ("divisao", "divisao"), ("objecao", "objecao"),
                             ("resposta", "resposta"), ("escolio", "escolio"), ("corolario", "corolario"),
                             ("observacao", "observacao")):
            xml = tese(4, '<p><label>4.</label> <hi rend="bold">T.</hi> — a.</p>' +
                       base.replace("<p>", f'<p type="{tp}">'))
            self.assertIn(esperado, tipos(xml), tp)
        xml = tese(4, '<p><label>4.</label> <hi rend="bold">T.</hi> — a.</p>' +
                   '<p type="argumento">Todo gato dorme. Ora Tom é gato. Logo Tom dorme.</p>')
        self.assertIn("Conclusão::", g._escreve_slides(slides_de(xml)))

    def test_tese_proposicao(self):
        sl = slides_de(tese(187, '<p><label>187.</label> O <hi rend="bold">sensualismo</hi> é '
                                 '<hi rend="bold">falso</hi>.</p>'
                                 '<p>a) Se a causa é pobre, o efeito é pobre. Ora possuimos noções abstractas. '
                                 'Logo o sensualismo é falso.</p><p>b) Outra prova qualquer, mais curta.</p>'))
        t = [s for s in sl if s.tipo == "tese"][0]
        self.assertEqual(t.titulo, "187. O sensualismo é falso")
        self.assertEqual(t.corpo[0].kind, "!")

    def test_subdivisoes_com_titulo_e_rubrica(self):
        sl = slides_de(tese(10, '<p><label>10.</label> A Logica é <hi rend="bold">arte</hi> e '
                                '<hi rend="bold">sciencia</hi>.</p>'
                                '<p>a) <hi rend="it">É arte</hi> — Por quanto, arte é o conjuncto de regras. '
                                'Ora a Logica é um conjuncto de regras. Logo a Logica é arte.</p>'
                                '<p>b) <hi rend="it">É sciencia</hi> — Por quanto, sciencia é conhecimento certo.</p>'
                                '<p>1.º Primeiro ponto simples e solto.</p>'))
        tits = [s.titulo for s in sl]
        self.assertTrue(any(t.endswith("— a) É arte") for t in tits), tits)
        self.assertTrue(any(t.endswith("— b) É sciencia") for t in tits), tits)
        self.assertTrue(any(t.endswith("— 1.º") for t in tits), tits)
        # a rubrica sai do corpo e vai para o título
        a = [s for s in sl if s.titulo.endswith("a) É arte")][0]
        self.assertNotIn("É arte", texto_corpo(a))

    def test_ocr_do_marcador(self):
        sl = slides_de(tese(10, '<p><label>10.</label> A Logica é <hi rend="bold">arte</hi>.</p>'
                                '<p>a) Primeiro argumento longo o bastante para valer.</p>'
                                '<p>b) Segundo argumento longo o bastante para valer.</p>'
                                '<p>€) Terceiro argumento longo o bastante para valer.</p>'))
        self.assertTrue(any(s.titulo.endswith("— c)") for s in sl), [s.titulo for s in sl])


class Paginacao(unittest.TestCase):
    def test_orcamento_e_continua(self):
        frases = " ".join(f"Esta é a frase número {i} do texto corrido de teste." for i in range(1, 40))
        sl = slides_de(tese(11, f'<p><label>11.</label> <hi rend="bold">Longa.</hi> — {frases}</p>'),
                       max_car=300)
        corpo = [s for s in sl if s.tipo not in ("capa", "secao")]
        self.assertGreater(len(corpo), 3)
        self.assertTrue(all(s.continua for s in corpo[:-1]))
        self.assertFalse(corpo[-1].continua)
        self.assertTrue(all(s.titulo.endswith("(cont.)") for s in corpo[1:]))
        self.assertFalse(corpo[0].titulo.endswith("(cont.)"))
        f = fonte_de(tese(11, f'<p><label>11.</label> <hi rend="bold">Longa.</hi> — {frases}</p>'), max_car=300)
        self.assertGreaterEqual(len(re.findall(r"^\+continua$", f, re.M)), 3)
        tex = g.fonte_para_tex(f)
        self.assertEqual(tex.count("\\continua"), len(re.findall(r"^\+continua$", f, re.M)))
        # nenhum slide ultrapassa o orçamento, salvo frase única maior que ele
        for s in corpo:
            if len(s.corpo) > 1:
                self.assertLessEqual(sum(i.peso() for i in s.corpo), 300 + 120)

    def test_nao_corta_frase(self):
        frases = [f"Frase {i} termina aqui, com bastante texto para ocupar linha e mais linha." for i in range(12)]
        sl = slides_de(tese(12, '<p><label>12.</label> <hi rend="bold">T.</hi> — ' + " ".join(frases) + "</p>"),
                       max_car=250)
        for s in sl:
            for it in s.corpo:
                if it.kind == "-":
                    self.assertTrue(it.r.plano.rstrip().endswith("."), it.r.plano)

    def test_frase_unica_maior_que_o_orcamento_fica_inteira(self):
        longa = "Palavra " * 120 + "fim."
        sl = slides_de(tese(13, '<p><label>13.</label> <hi rend="bold">T.</hi> — ' + longa + "</p>"), max_car=200)
        cont = [s for s in sl if s.tipo not in ("capa", "secao")]
        self.assertEqual(len(cont), 1)

    def test_abreviaturas_nao_quebram_frase(self):
        fr = g.frases(g.r_de("Cf. S. Th., I, q. 2, a. 3. Ora isso é assim. Segundo o n. 5 do Cap. II etc. e tal."))
        self.assertEqual([x.plano for x in fr],
                         ["Cf. S. Th., I, q. 2, a. 3.", "Ora isso é assim.", "Segundo o n. 5 do Cap. II etc. e tal."])


class Escapes(unittest.TestCase):
    PERIGO = r"\input{/etc/passwd} $x$ 100% #1 a_b & {c} ~ ^ \write18 \def\x{y} [z] <a|b> `q`"

    def test_tex_nao_deixa_passar_comandos(self):
        f = "=== texto\n# " + self.PERIGO + "\n@ " + self.PERIGO + "\n" + self.PERIGO + "\n"
        tex = g.fonte_para_tex(f)
        corpo = tex.split("\\begin{document}")[1]
        for ruim in (r"\input", r"\write", r"\def"):
            # só pode aparecer como \textbackslash{}input ...
            self.assertNotRegex(corpo, r"(?<!textbackslash\{\})" + re.escape(ruim) + r"\b".replace("\\b", ""))
        self.assertNotIn("$x$", corpo)
        self.assertIn(r"\$x\$", corpo)
        self.assertIn(r"100\%", corpo)
        self.assertIn(r"\#1", corpo)
        self.assertIn(r"a\_b", corpo)
        self.assertIn(r"\&", corpo)
        self.assertIn(r"\{c\}", corpo)
        self.assertIn("{[}z{]}", corpo)
        self.assertEqual(corpo.count("\\begin{slide}"), 1)
        # o único \input do documento é o do pacote (nenhum vindo da fonte)
        self.assertNotIn("passwd}", corpo.replace(r"\textbackslash{}input\{/etc/passwd\}", ""))

    def test_sem_escape_nao_ha_comando_na_saida(self):
        tex = g.fonte_para_tex("=== texto\n\\input{/etc/passwd}\n")
        self.assertNotRegex(tex.split("\\begin{document}")[1], r"(?<!\{)\\input")

    def test_marcacao_desbalanceada(self):
        tex = g.fonte_para_tex("=== texto\nisto *sem fim e **nada e ^ainda\n")
        corpo = tex.split("\\begin{document}")[1]
        self.assertNotIn("\\textit", corpo)
        self.assertNotIn("\\textbf", corpo)
        self.assertNotIn("\\textsc", corpo)
        self.assertEqual(len(re.findall(r"(?<!\\)\{", corpo)), len(re.findall(r"(?<!\\)\}", corpo)))

    def test_marcacao_cruzada_balanceia(self):
        tex = g.fonte_para_tex("=== texto\n*a **b* c** d ^e*\n")
        corpo = tex.split("\\begin{document}")[1]
        self.assertEqual(len(re.findall(r"(?<!\\)\{", corpo)), len(re.findall(r"(?<!\\)\}", corpo)))

    def test_inline_basico(self):
        self.assertEqual(g.inline_tex("a *b* **c** ^d^ — e \\* \\^ \\\\"),
                         r"a \textit{b} \textbf{c} \textsc{d} --- e * \textasciicircum{} \textbackslash{}")

    def test_ida_e_volta_do_inicio_de_linha(self):
        textos = ["- item", "! forte", "> cita", "# titulo", "@ ref", "% comentario", "=== slide", "+continua",
                  "Maior:: algo", "ab:: x", "\\barra no início", "*itálico* depois", "^sc^ depois",
                  "2 * 3 = 6", "normal", "\\\\duas", "- - -", "= igual", "+ mais"]
        for t in textos:
            r = g.r_de(t)
            linha = g.linha_paragrafo(g.r_para_fonte(r))
            fonte = "=== texto\n" + linha + "\n"
            sl, msgs = g._parse(fonte)
            self.assertEqual(len(sl), 1, (t, fonte))
            self.assertEqual(len(sl[0]["corpo"]), 1, (t, fonte))
            kind, raw = sl[0]["corpo"][0][:2]
            self.assertEqual(kind, "p", (t, fonte))
            self.assertEqual(g.plano(raw), t, (t, fonte))

    def test_ida_e_volta_de_formatacao(self):
        r = g.R("a b c d e", bytearray([0, 0, 1, 1, 1, 0, 2, 3, 4]))
        raw = g.r_para_fonte(r)
        self.assertEqual(g.plano(raw), "a b c d e")
        self.assertEqual(g.inline_tex(raw).count("{"), g.inline_tex(raw).count("}"))

    def test_escape_de_asterisco_literal_na_geracao(self):
        f = fonte_de(tese(1, '<p><label>1.</label> <hi rend="bold">T.</hi> — a*b ^ c \\ d.</p>'))
        self.assertIn("a\\*b \\^ c \\\\ d.", f)
        sl, _ = g._parse(f)
        self.assertEqual(g.validar(f), [])


class Determinismo(unittest.TestCase):
    def test_mesma_entrada_mesma_saida(self):
        xml = tei(tese(5, Silogismo.P) + tese(6, '<p><label>6.</label> O <hi rend="bold">x</hi> é y.</p>'))
        a = g.tei_para_fonte(xml)
        b = g.tei_para_fonte(xml)
        self.assertEqual(a, b)
        self.assertEqual(g.fonte_para_tex(a), g.fonte_para_tex(b))
        self.assertNotRegex(a, r"20\d\d-\d\d-\d\d")

    def test_bytes_e_str_equivalentes(self):
        xml = tei(tese(5, Silogismo.P))
        self.assertEqual(g.tei_para_fonte(xml), g.tei_para_fonte(xml.encode("utf-8")))

    def test_sem_namespace(self):
        xml = tei(tese(5, Silogismo.P), ns=False)
        self.assertIn("Conclusão::", g.tei_para_fonte(xml))


class Validacao(unittest.TestCase):
    def test_fonte_gerada_e_valida(self):
        self.assertEqual(g.validar(fonte_de(tese(5, Silogismo.P))), [])

    def test_mensagens(self):
        fonte = ("% c\nsolto\n=== foo\n# t\n# t2\n@ a\n@ b\n!\n\n=== tese\n\n=== capa\ncorpo\n"
                 "=== texto\n+continua\nmais\n  - filho\n*meio\n")
        m = g.validar(fonte)
        junto = "\n".join(m)
        self.assertIn("linha 2: conteúdo antes do primeiro '==='", junto)
        self.assertIn("linha 3: tipo de slide desconhecido 'foo'", junto)
        self.assertIn("linha 5: '#' repetido", junto)
        self.assertIn("linha 7: '@' repetido", junto)
        self.assertIn("slide vazio", junto)
        self.assertIn("linha 12: slide 'capa' sem título", junto)
        self.assertIn("'+continua'", junto)
        self.assertIn("aninhado sem tópico pai", junto)
        self.assertIn("sem par", junto)
        self.assertTrue(all(re.match(r"linha \d+: ", x) for x in m))

    def test_tipo_desconhecido_vira_texto_e_compila(self):
        tex = g.fonte_para_tex("=== xyz\n# T\ncorpo\n")
        self.assertIn("\\begin{slide}{texto}{T}{}", tex)
        self.assertEqual(g.contar_slides("=== xyz\n=== tese\n=== texto\n"), 3)

    def test_tex_contrato(self):
        f = ("=== capa\n# Título\n@ pp. 1–2\nSub\n=== secao\n# Sec\nArtigo I.\n=== tese\n# 1. T\n@ n. 1 · p. 3\n"
             "! Enunciado *x*\n\n- a\n  - b\n- c\n> citação\nMaior:: m\nConclusão:: c\n+continua\n")
        tex = g.fonte_para_tex(f)
        for trecho in ("\\documentclass[aspectratio=169,11pt]{beamer}", "\\usepackage{academia-slides}",
                       "\\slidesmeta{Elementos de Philosophia}{Thiago Sinibaldi}{Título}",
                       "\\slidecapa{Título}{Sub}{pp. 1--2}", "\\slidesecao{Artigo I.}{Sec}",
                       "\\begin{slide}{tese}{1. T}{n. 1 · p. 3}", "\\begin{enunciado}", "\\begin{topicos}",
                       "\\begin{citacao}", "\\begin{rotulados}", "\\rot{Maior}{m}", "\\continua",
                       "\\end{slide}", "\\end{document}"):
            self.assertIn(trecho, tex)


class PreservacaoDoTexto(unittest.TestCase):
    def _checa(self, xml, **kw):
        sl, _ = g._constroi(xml, **kw)
        self.assertEqual(confere_texto(xml, sl), [])

    def test_texto_integral_sintetico(self):
        xml = tei(tese(29, '<p><label>29.</label> <hi rend="bold">Simplicidade da alma.</hi> — '
                           '<hi rend="it">Simplicidade</hi> é a propriedade, pela qual a alma não é composta de '
                           'partes<note place="foot" n="1"><p>nota que não conta</p></note>. Divide-se<pb n="36"/>a '
                           'simplicidade em <hi rend="it">absoluta</hi> e <hi rend="it">relativa</hi>. — Mais uma '
                           'frase. Cf. S. Th., I, q. 3.</p>'
                           '<p>30. A <hi rend="bold">alma</hi> é <hi rend="bold">simples</hi>.</p>'
                           '<p>a) <hi rend="it">Rubrica</hi> — Se a alma fosse composta, seria divisível. Ora não é '
                           'divisível. Logo é simples. Dizem que não. Respondemos que sim.</p>'
                           '<p>b) Segue um fragmento de linha que se</p><p>completa na linha seguinte, com ge-</p>'
                           '<p>nero e tudo mais. Logo ficou ligado.</p>'
                           '<p>1.º Ponto um — ponto dois — ponto três.</p><p>I. Item romano de teste.</p>'
                           '<p>! |</p>'))
        self._checa(xml)
        self._checa(xml, max_car=150)

    def test_amostras_reais(self):
        pasta = Path("/home/lucas/.claude/jobs/7d86d7ed/tmp/amostras")
        arqs = sorted(pasta.glob("*.xml")) if pasta.exists() else []
        if not arqs:
            self.skipTest("amostras reais não disponíveis")
        for a in arqs:
            xml = a.read_bytes()
            for mc in (g.MAX_CAR, 200):
                sl, _ = g._constroi(xml, max_car=mc)
                self.assertEqual(confere_texto(xml, sl), [], a.name)

    def test_volumes_inteiros(self):
        raiz = Path(__file__).resolve().parent.parent
        import os
        if os.environ.get("SLIDES_VOLUMES") != "1":
            self.skipTest("defina SLIDES_VOLUMES=1 para rodar nos volumes inteiros")
        for v in ("vol1", "vol2"):
            arq = raiz / v / f"{v}.corrigido.xml"
            if not arq.exists():
                continue
            xml = arq.read_bytes()
            sl, _ = g._constroi(xml)
            self.assertEqual(confere_texto(xml, sl), [], v)


class Seletores(unittest.TestCase):
    XML = tei('<div type="capitulo" xml:id="cap-1"><head type="rotulo">CAPITULO I</head><head>Titulo cap</head>'
              '<pb n="10"/><div type="artigo" xml:id="art-1"><head type="rotulo">Artigo I.</head>'
              + tese(1, '<p><label>1.</label> <hi rend="bold">Um.</hi> — Primeira frase da tese um.</p>')
              + '<pb n="11"/>' + tese(2, '<p><label>2.</label> <hi rend="bold">Dois.</hi> — Segunda frase da tese dois.</p>')
              + "</div></div>")

    def test_id(self):
        f = g.tei_para_fonte(self.XML, seletor_id="t2")
        self.assertIn("2. Dois", f)
        self.assertNotIn("1. Um", f)
        self.assertIn("p. 11", f)

    def test_id_inexistente(self):
        with self.assertRaises(ValueError):
            g.tei_para_fonte(self.XML, seletor_id="nao-existe")

    def test_faixa_de_paginas(self):
        f = g.tei_para_fonte(self.XML, pagina_ini=11, pagina_fim=11)
        self.assertIn("2. Dois", f)
        self.assertNotIn("1. Um", f)

    def test_secoes(self):
        f = g.tei_para_fonte(self.XML)
        self.assertIn("=== secao\n# Titulo cap\nCAPITULO I", f)
        self.assertIn("=== secao\n# Artigo I.", f)

    def test_xml_estranho_nao_quebra(self):
        for corpo in ("", "<p/>", "<p>   </p>", "<p><hi rend='x'>?</hi></p>", "<div><p>sem tipo</p></div>",
                      tese(1, "<p>1.</p>"), tese(2, "<p><label>2.</label></p>"),
                      '<p type="enunciado"></p><p type="definicao">...</p>',
                      "<p>Ora. Logo. Ora Logo Ora Logo</p>", "<p>«« »» ((( )))</p>"):
            g.tei_para_fonte(tei(corpo))


class Notas(unittest.TestCase):
    def test_notas_viram_slides_so_com_flag(self):
        xml = tei(tese(1, '<p><label>1.</label> <hi rend="bold">T.</hi> — Corpo do texto aqui '
                          '<note place="foot" n="1"><p>Texto da nota de rodapé.</p></note>mais corpo.</p>'))
        self.assertNotIn("Texto da nota", g.tei_para_fonte(xml))
        f = g.tei_para_fonte(xml, notas=True)
        self.assertIn("Texto da nota de rodapé.", f)
        self.assertIn("— nota 1", f)


if __name__ == "__main__":
    unittest.main()
