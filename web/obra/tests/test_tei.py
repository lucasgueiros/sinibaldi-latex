import unittest

from django.conf import settings
from django.test import SimpleTestCase
from lxml import etree

from obra import esquema, tei
from .base import tei_sintetico, texto

NS = "{http://www.tei-c.org/ns/1.0}"


class AchatarTest(SimpleTestCase):
    def setUp(self):
        self.rel = tei.Relatorio()
        self.blocos = tei.achatar(tei_sintetico(), numero=2, relatorio=self.rel)

    def test_tipos_e_ordem(self):
        tipos = [b.tipo for b in self.blocos]
        self.assertEqual(tipos, [
            "paragrafo", "marco", "titulo", "titulo", "marco", "titulo", "titulo", "sumario",
            "marco", "paragrafo", "cabecalho", "marco", "paragrafo", "paragrafo", "marco", "titulo", "titulo",
            "marco", "paragrafo"])

    def test_prefixo_de_ids(self):
        self.assertIn('xml:id="v2.t1"', self.blocos[8].xml)
        self.assertIn('xml:id="v2.t1.p1"', self.blocos[9].xml)
        self.assertIn('xml:id="v2.n1-1"', self.blocos[9].xml)

    def test_paginas(self):
        marco_t3 = self.blocos[-2]
        self.assertEqual(marco_t3.pagina, 3)
        self.assertEqual(self.blocos[0].pagina, 1)
        # parágrafo que começa na pág. 1 e atravessa para a 2 (pb inline): próximo bloco já é pág. 2
        self.assertEqual(self.blocos[9].pagina, 1)
        self.assertEqual(self.blocos[10].pagina, 2)
        self.assertEqual(self.rel.paginas, {1: "0001", 2: "0002", 3: "0003"})

    def test_pb_inline_fica_no_bloco_e_fw_inline_tambem(self):
        x = self.blocos[9].xml
        self.assertIn('<pb n="2" facs="paginas/0002.png"/>', x)
        self.assertIn('<fw type="header">2 CABEC</fw>', x)

    def test_notas_normalizadas(self):
        x = self.blocos[12].xml
        self.assertIn('<note place="foot" n="1" xml:id="v2.n2-1"><p>Nota solta com <hi rend="it">grifo</hi>.</p></note>', x)

    def test_todos_validos(self):
        self.assertEqual(esquema.validar_blocos([b.xml for b in self.blocos]), [])

    def test_desembrulha_e_conta(self):
        raiz = etree.fromstring(
            b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div type="volume">'
            b'<p>a <seg x="1">b <hi rend="underline">c</hi></seg> d</p></div></body></text></TEI>')
        rel = tei.Relatorio()
        b = tei.achatar(raiz, relatorio=rel)
        self.assertEqual(b[0].xml, "<p>a b c d</p>")
        self.assertEqual(rel.desembrulhados["seg"], 1)
        self.assertEqual(rel.desembrulhados["hi"], 1)


class AninharTest(SimpleTestCase):
    def test_ida_e_volta(self):
        original = tei_sintetico()
        blocos = tei.achatar(original)
        nova = tei.aninhar(blocos, arquivos={1: "0001", 2: "0002", 3: "0003"})
        # estrutura de divisões
        divs = [(d.get("type"), d.get(esquema.qname_atributo("xml:id"))) for d in nova.iter(NS + "div")]
        self.assertEqual(divs, [("volume", None), ("parte", "parte-1"), ("capitulo", "cap-1"),
                                ("tese", "t1"), ("tese", "t2"), ("parte", "parte-2"), ("tese", "t3")])
        # texto idêntico (ignorando o cabeçalho) e mesmos pb
        t = lambda r: "".join("".join(r.find(f".//{NS}body").itertext()).split())
        self.assertEqual(t(nova), t(original))
        pbs = lambda r: [p.get("n") for p in r.iter(NS + "pb")]
        self.assertEqual(sorted(set(pbs(nova))), sorted(set(pbs(original))))
        # idempotência: achatar(aninhar(x)) == x
        self.assertEqual([b.xml for b in tei.achatar(nova)], [b.xml for b in blocos])
        self.assertEqual([b.pagina for b in tei.achatar(nova)], [b.pagina for b in blocos])

    def test_marco_fecha_niveis_iguais_ou_inferiores(self):
        blocos = [tei.BlocoDado("marco", f'<milestone unit="{u}" xml:id="{u}{i}"/>', None)
                  for i, u in enumerate(["parte", "capitulo", "tese", "capitulo", "tese", "parte", "tese"])]
        raiz = tei.aninhar(blocos)
        pai = lambda d: d.getparent().get("type") if d.getparent() is not None else None
        res = [(d.get("type"), pai(d)) for d in raiz.iter(NS + "div")]
        self.assertEqual([x[1] for x in res[1:]],
                         ["volume", "parte", "capitulo", "parte", "capitulo", "volume", "parte"])

    def test_remover_prefixo(self):
        b = tei.achatar(tei_sintetico(), numero=2)
        raiz = tei.aninhar(b, remover_prefixo="v2.")
        ids = {e.get(esquema.qname_atributo("xml:id")) for e in raiz.iter() if isinstance(e.tag, str)}
        self.assertIn("t1", ids)
        self.assertNotIn("v2.t1", ids)

    def test_cabecalho_com_autores(self):
        raiz = tei.aninhar([], autores=["Ana"], revisoes=[("2026-01-01", "x")])
        self.assertEqual(raiz.find(f".//{NS}respStmt/{NS}name").text, "Ana")
        self.assertEqual(raiz.find(f".//{NS}change").get("when"), "2026-01-01")


class HtmlTest(SimpleTestCase):
    def test_mapeamento_fixo(self):
        h = tei.fragmento_para_html('<p type="escolio" xml:id="a"><label>1.</label> x <hi rend="it">i</hi>'
                                    '<hi rend="bold">b</hi><hi rend="sc">s</hi><foreign xml:lang="la">l</foreign>'
                                    '<pb n="2" facs="paginas/0002.png"/></p>')
        for trecho in ('<p data-tei="p" data-type="escolio" data-xmlid="a">', '<span data-tei="label">1.</span>',
                       "<i>i</i>", "<b>b</b>", '<span data-tei="hi" data-rend="sc">s</span>',
                       '<span data-tei="foreign" lang="la">l</span>',
                       '<span data-tei="pb" data-n="2" data-facs="paginas/0002.png" contenteditable="false"></span>'):
            self.assertIn(trecho, h)
        self.assertEqual(tei.fragmento_para_html('<milestone unit="tese" n="1" xml:id="t"/>'),
                         '<div data-tei="milestone" data-unit="tese" data-n="1" data-xmlid="t"></div>')
        self.assertEqual(tei.fragmento_para_html('<head type="rotulo">A</head>'),
                         '<h3 data-tei="head" data-type="rotulo">A</h3>')
        self.assertEqual(tei.fragmento_para_html('<fw type="header">A</fw>'), '<p data-tei="fw">A</p>')
        self.assertEqual(tei.fragmento_para_html('<argument><p>A</p></argument>'),
                         '<div data-tei="argument"><p>A</p></div>')
        n = tei.fragmento_para_html('<p>a<note place="foot" n="1" xml:id="n"><p>x</p><p>y</p></note></p>')
        self.assertIn('<span data-tei="note" data-n="1" data-xmlid="n"><span data-tei="note-p">x</span>'
                      '<span data-tei="note-p">y</span></span>', n)

    def test_round_trip_sintetico(self):
        for b in tei.achatar(tei_sintetico()):
            self.assertEqual(tei.html_para_fragmento(tei.fragmento_para_html(b.xml)), b.xml)

    def test_tolerancia(self):
        self.assertEqual(tei.html_para_fragmento("<p>a&nbsp;<em>b</em> <strong>c</strong><u>d</u></p>"),
                         '<p>a <hi rend="it">b</hi> <hi rend="bold">c</hi>d</p>')
        self.assertEqual(tei.html_para_fragmento('<p class="x" style="y" data-tei="p">oi<br>fim</p>'), "<p>oifim</p>")
        self.assertEqual(tei.html_para_fragmento('<div><p>dentro de div</p></div>'), "<p>dentro de div</p>")
        self.assertEqual(tei.html_para_fragmento("texto solto"), "<p>texto solto</p>")
        x = tei.html_para_fragmento('<p data-tei="p" data-type="bobagem">a</p>')
        self.assertEqual(x, "<p>a</p>")
        # nota dentro de nota é desembrulhada
        x = tei.html_para_fragmento('<p>a<span data-tei="note" data-n="1"><span data-tei="note-p">'
                                    'b<span data-tei="note" data-n="2">c</span></span></span></p>')
        self.assertEqual(esquema.validar_fragmento(x), [])

    def test_multiplos_blocos(self):
        r = tei.html_para_blocos('<p data-tei="p" data-bloco="7" data-versao="3">a</p><h3 data-tei="head">B</h3><p></p>')
        self.assertEqual(r, [{"id": 7, "versao": 3, "xml": "<p>a</p>"}, {"id": None, "versao": None, "xml": "<head>B</head>"}])
        with self.assertRaises(ValueError):
            tei.html_para_fragmento('<p>a</p><p>b</p>')

    def test_blocos_para_html_e_volta(self):
        class B:
            def __init__(self, pk, v, xml):
                self.pk, self.versao, self.xml = pk, v, xml
        blocos = [B(5, 2, "<p>um</p>"), B(6, 1, '<milestone unit="tese" n="1" xml:id="t"/>')]
        h = tei.blocos_para_html(blocos)
        self.assertIn('data-bloco="5" data-versao="2"', h)
        self.assertEqual(tei.html_para_blocos(h), [
            {"id": 5, "versao": 2, "xml": "<p>um</p>"},
            {"id": 6, "versao": 1, "xml": '<milestone unit="tese" n="1" xml:id="t"/>'}])


class RoundTripRealTest(unittest.TestCase):
    """Em amostras reais (se os XML existirem): HTML ida-e-volta e achatar/aninhar."""

    def _fonte(self, n):
        for raiz in (settings.SINIBALDI_DADOS, settings.RAIZ_REPO):
            p = raiz / f"vol{n}" / f"vol{n}.corrigido.xml"
            if p.is_file():
                return p
        self.skipTest("TEI real indisponível")

    def test_html_round_trip(self):
        for n in (1, 2):
            blocos = tei.achatar(etree.parse(str(self._fonte(n))), numero=n)
            self.assertGreater(len(blocos), 1000)
            for b in blocos:
                self.assertEqual(esquema.validar_fragmento(b.xml), [], b.xml[:200])
                self.assertEqual(tei.html_para_fragmento(tei.fragmento_para_html(b.xml)), b.xml)

    def test_texto_preservado(self):
        orig = etree.parse(str(self._fonte(2)))
        blocos = tei.achatar(orig, numero=2)
        nova = tei.aninhar(blocos, remover_prefixo="v2.")
        corpo = lambda r: "".join(r.find(f".//{NS}body").itertext())
        self.assertEqual(len(corpo(nova)), len(corpo(orig)))
