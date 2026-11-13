"""Componente gravura: esquema, ida e volta TEI/HTML, recorte do scan, gravação na 1916, leitura, LaTeX."""
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from lxml import etree

from obra import esquema, exportacao, leitura, tei
from obra.models import Bloco, No

from .test_views_edicao import BaseViews

FIG = ('<figure xml:id="v1.gravura-0002-ab"><graphic url="paginas/0002.png#xywh=10,20,30,40" width="50%"/>'
       '<head>Fig. <hi rend="it">1</hi></head></figure>')
SEM_LEGENDA = '<figure xml:id="v1.gravura-0002-cd"><graphic url="paginas/0002.png#xywh=0,0,5,5"/></figure>'


class EsquemaTest(SimpleTestCase):
    def test_valido(self):
        for x in (FIG, SEM_LEGENDA):
            self.assertEqual(esquema.validar_fragmento(x), [], x)
            self.assertEqual(esquema.tipo_do_fragmento(x), "gravura")

    def test_invalidos(self):
        casos = {
            '<figure><graphic url="paginas/0002.png#xywh=0,0,5,5"/></figure>': "exige xml:id",
            '<figure xml:id="a"><graphic url="paginas/0002.png"/></figure>': "xywh",
            '<figure xml:id="a"><graphic url="../x.png#xywh=0,0,5,5"/></figure>': "xywh",
            '<figure xml:id="a"><graphic url="paginas/0002.png#xywh=0,0,0,5"/></figure>': "zero",
            '<figure xml:id="a"><graphic url="paginas/0002.png#xywh=0,0,5,5" width="150%"/></figure>': "width",
            '<figure xml:id="a"><head>só legenda</head></figure>': "único <graphic>",
            '<figure xml:id="a"><graphic url="paginas/0002.png#xywh=0,0,5,5"/><p>x</p></figure>': "só pode conter",
            '<figure xml:id="a">solto<graphic url="paginas/0002.png#xywh=0,0,5,5"/></figure>': "texto solto",
            ('<figure xml:id="a"><graphic url="paginas/0002.png#xywh=0,0,5,5"/>'
             '<head>a<note place="foot" n="1"><p>n</p></note></head></figure>'): "não é permitido",
        }
        for x, trecho in casos.items():
            erros = " ".join(esquema.validar_fragmento(x))
            self.assertIn(trecho, erros, x)

    def test_gravura_nao_e_inline(self):
        x = '<p>a <figure xml:id="a"><graphic url="paginas/0002.png#xywh=0,0,5,5"/></figure></p>'
        self.assertTrue(esquema.validar_fragmento(x))


class ConversoesTest(SimpleTestCase):
    def test_html_ida_e_volta(self):
        h = tei.fragmento_para_html(FIG)
        self.assertIn('data-tei="figure"', h)
        self.assertIn('src="/gravura/1/0002/10,20,30,40.png"', h)
        self.assertIn("<figcaption>Fig. <i>1</i></figcaption>", h)
        self.assertEqual(tei.html_para_blocos(h)[0]["xml"], FIG)
        h2 = tei.fragmento_para_html(SEM_LEGENDA)
        self.assertEqual(tei.html_para_blocos(h2)[0]["xml"], SEM_LEGENDA)

    def test_legenda_vazia_some(self):
        h = tei.fragmento_para_html(SEM_LEGENDA).replace("<figcaption></figcaption>", "<figcaption>  </figcaption>")
        self.assertEqual(tei.html_para_blocos(h)[0]["xml"], SEM_LEGENDA)

    def test_texto_xml(self):
        self.assertEqual(tei.texto_xml_para_blocos(FIG)[0]["xml"], FIG)

    def test_achatar_e_aninhar(self):
        t = ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div type="volume"><pb n="2" facs="paginas/0002.png"/>'
             '<p>Antes.</p><figure xml:id="gravura-0002-ab"><graphic url="paginas/0002.png#xywh=10,20,30,40" width="50%"/>'
             '<head>Fig. <hi rend="it">1</hi></head></figure><p>Depois.</p></div></body></text></TEI>')
        blocos = tei.achatar(etree.fromstring(t), numero=1)
        self.assertEqual([b.tipo for b in blocos], ["paragrafo", "gravura", "paragrafo"])
        self.assertEqual(blocos[1].xml, FIG)
        raiz = tei.aninhar(blocos, remover_prefixo="v1.")
        self.assertIn('<figure xml:id="gravura-0002-ab"><graphic url=', tei.serializar_tei(raiz))


def _png(caminho, tam=(200, 300)):
    from PIL import Image, ImageDraw
    im = Image.new("L", tam, 255)
    ImageDraw.Draw(im).rectangle((10, 20, 39, 59), fill=0)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    im.save(caminho)


class ComScan(BaseViews):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.dados = Path(self._tmp.name) / "dados"
        _png(self.dados / "vol1" / "paginas" / "0002.png")
        self._ov = override_settings(SINIBALDI_DADOS=self.dados, SINIBALDI_CACHE=Path(self._tmp.name) / "cache")
        self._ov.enable()

    def tearDown(self):
        self._ov.disable()
        self._tmp.cleanup()
        super().tearDown()


class RecorteTest(ComScan):
    def test_recorte(self):
        from PIL import Image
        r = self.client.get(reverse("obra:gravura", args=[1, "0002", "10,20,30,40"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        arq = Path(settings.SINIBALDI_CACHE) / "gravuras" / "v1_0002_10_20_30_40.png"
        with Image.open(arq) as im:
            self.assertEqual(im.size, (30, 40))
            self.assertEqual(im.getpixel((0, 0)), 0)

    def test_caixa_aparada_na_borda(self):
        from PIL import Image
        self.assertEqual(self.client.get(reverse("obra:gravura", args=[1, "0002", "150,250,500,500"])).status_code, 200)
        with Image.open(Path(settings.SINIBALDI_CACHE) / "gravuras" / "v1_0002_150_250_500_500.png") as im:
            self.assertEqual(im.size, (50, 50))

    def test_404(self):
        for args in ([1, "0002", "1,2,3"], [1, "0002", "0,0,0,5"], [1, "9999", "0,0,5,5"], [7, "0002", "0,0,5,5"],
                     [1, "0002", "900,900,5,5"]):
            self.assertEqual(self.client.get(reverse("obra:gravura", args=args)).status_code, 404, args)

    def test_publico(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("obra:gravura", args=[1, "0002", "10,20,30,40"])).status_code, 200)

    def test_tela_de_revisao_tem_dimensoes(self):
        r = self.client.get(self.url_rev(2))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["dados"]["scanDim"], (200, 300))
        self.assertEqual(r.context["dados"]["arquivo"], "0002")
        self.assertContains(r, "data-gravura")


class GravarTest(ComScan):
    def test_insere_gravura_pelo_editor(self):
        bs, ids = self.escopo(2)
        html = tei.blocos_para_html(bs) + "\n" + tei.fragmento_para_html(FIG)
        r = self.post_json(reverse("obra:gravar", args=[1, 2]), {"formato": "html", "conteudo": html, "ids": ids})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["resumo"]["criados"], 1)
        b = Bloco.objects.get(xml__contains="v1.gravura-0002-ab")
        self.assertEqual((b.tipo, b.xml, b.volume, b.pagina), (Bloco.GRAVURA, FIG, self.vol, 2))
        self.assertIn('src="/gravura/1/0002/10,20,30,40.png"', r.json()["html"])

    def test_xml_id_repetido_na_edicao(self):
        bs, ids = self.escopo(2)
        html = tei.blocos_para_html(bs) + "\n" + tei.fragmento_para_html(FIG)
        self.post_json(reverse("obra:gravar", args=[1, 2]), {"formato": "html", "conteudo": html, "ids": ids})
        bs3, ids3 = self.escopo(3)
        html3 = tei.blocos_para_html(bs3) + "\n" + tei.fragmento_para_html(FIG)
        r = self.post_json(reverse("obra:gravar", args=[1, 3]), {"formato": "html", "conteudo": html3, "ids": ids3})
        self.assertEqual(r.status_code, 400)
        self.assertIn("já é usado", " ".join(r.json()["erros"]))

    def _com_gravura(self):
        bs, ids = self.escopo(2)
        partes = []
        for b in bs:  # a gravura logo depois de «Outro parágrafo» (ainda na parte 1)
            partes.append(tei.blocos_para_html([b]))
            if "Outro parágrafo" in b.xml:
                partes.append(tei.fragmento_para_html(FIG))
        r = self.post_json(reverse("obra:gravar", args=[1, 2]), {"formato": "html", "conteudo": "\n".join(partes), "ids": ids})
        self.assertEqual(r.status_code, 200, r.content)
        return No.objects.get(edicao=self.edicao, xml_id="v1.parte-1")

    def test_leitura_e_exportacoes(self):
        no = self._com_gravura()
        r = self.client.get(reverse("obra:no", args=["1916", no.xml_id]))
        self.assertContains(r, 'src="/gravura/1/0002/10,20,30,40.png"')
        self.assertIn("[Gravura: Fig. 1]", exportacao.texto_do_no(no))
        html = exportacao.html_do_no(no)
        self.assertIn('src="data:image/png;base64,', html)
        self.assertIn('<figure data-tei="figure"', html)
        self.assertIn('<figure xml:id="gravura-0002-ab"><graphic url="paginas/0002.png#xywh=10,20,30,40"',
                      exportacao.tei_do_no(no))

    def test_latex(self):
        no = self._com_gravura()
        tex = Path(exportacao.latex_do_no(no)).read_text(encoding="utf-8")
        self.assertIn(r"\gravura{", tex)
        self.assertIn("}{0.50}{Fig. \\emph{1}}", tex)
        caminho = tex.rsplit(r"\gravura{", 1)[1].split("}", 1)[0]  # o último: o do texto, não o do preâmbulo
        self.assertTrue(Path(caminho).is_file(), caminho)
        self.assertIn(r"\newcommand{\gravura}", tex)


class Tei2LatexTest(SimpleTestCase):
    def test_sem_imagem_marca_rever(self):
        t = ('<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div type="volume"><pb n="2"/>'
             '<figure xml:id="g"><graphic url="paginas/0002.png#xywh=1,1,5,5"/><head>Leg.</head></figure>'
             '</div></body></text></TEI>')
        with tempfile.TemporaryDirectory() as d:
            xml = Path(d) / "a.xml"
            xml.write_text(t, encoding="utf-8")
            r = subprocess.run([sys.executable, str(Path(settings.RAIZ_REPO) / "tools" / "tei2latex.py"), str(xml),
                                "--puro", "--dir-gravuras", str(Path(d) / "g")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("gravura indisponível", r.stdout)
        self.assertIn("Leg.", r.stdout)
        self.assertIn("% REVER", r.stdout)
