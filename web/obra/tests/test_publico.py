"""Parte pública: rotas, leitura, busca, fac-símile e downloads."""
import os
import shutil
import tempfile
import uuid
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from lxml import etree

from obra import arvore, leitura
from obra.models import Bloco, Edicao, Revisao

from .base import BaseBanco

TEI_NS = "{http://www.tei-c.org/ns/1.0}"


class PublicoBase(BaseBanco):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # nova edição: cópia dos blocos da 1916 com `origem`
        cls.nova = Edicao.objects.create(slug="nova", titulo="Nova edição", tipo="nova")
        antigos = list(Bloco.objects.filter(edicao=cls.edicao).order_by("ordem"))
        Bloco.objects.bulk_create([
            Bloco(edicao=cls.nova, ordem=b.ordem, tipo=b.tipo, xml=b.xml, volume=b.volume, pagina=b.pagina,
                  origem=b, procedencia=Bloco.ADAPTADO if i == 3 else Bloco.COPIA)
            for i, b in enumerate(antigos)])
        arvore.reconstruir(cls.nova)
        t1 = Bloco.objects.filter(edicao=cls.edicao, xml__contains='xml:id="v1.t1.p1"').first()
        Revisao.objects.create(bloco=t1, edicao=cls.edicao, autor=cls.user, acao=Revisao.EDITAR, lote=uuid.uuid4())
        Revisao.objects.create(bloco=t1, edicao=cls.edicao, autor=None, acao=Revisao.IMPORTAR, lote=uuid.uuid4())

    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cache, True)
        p = mock.patch.dict(os.environ, {"SINIBALDI_CACHE": self.cache})
        p.start()
        self.addCleanup(p.stop)

    def get(self, nome, *args, status=200, **kw):
        r = self.client.get(reverse(f"obra:{nome}", args=args), kw)
        self.assertEqual(r.status_code, status, nome)
        return r


class RotasTest(PublicoBase):
    def test_inicio_e_sobre(self):
        r = self.get("inicio")
        self.assertContains(r, "OCR")
        self.assertContains(r, "Nova edição")
        self.get("sobre")

    def test_sumario(self):
        for slug in ("1916", "nova"):
            r = self.get("edicao", slug)
            self.assertContains(r, "v1.cap-1")
            self.assertContains(r, "<details class=\"teses\">")
        self.get("edicao", "inexistente", status=404)

    def test_sumario_uma_consulta_de_arvore(self):
        with self.assertNumQueries(4):  # edição, nós, páginas, volumes
            self.get("edicao", "1916")

    def test_no_capitulo_e_tese(self):
        r = self.get("no", "1916", "v1.cap-1")
        self.assertContains(r, "IDEA")
        self.assertContains(r, 'class="nref"')        # nota numerada no texto
        self.assertContains(r, 'id="nota-1"')         # e listada no fim
        self.assertContains(r, 'href="#ref-1"')       # com volta
        self.assertNotContains(r, 'data-tei="fw"')    # cabeçalho corrente não aparece
        self.assertContains(r, "Baixar")
        self.assertContains(r, "Contribuíram para este trecho: ")
        self.assertContains(r, "ana")
        self.assertContains(r, "fac-simile/1/2/")     # marca de página linka o fac-símile
        self.get("no", "1916", "v1.t1")
        self.get("no", "1916", "v1.nao-existe", status=404)

    def test_no_nova_procedencia(self):
        r = self.get("no", "nova", "v1.cap-1")
        self.assertContains(r, "proc-copia")
        self.assertContains(r, "/edicao/1916/")       # link ao trecho de origem
        self.assertContains(r, "adaptado")

    def test_no_consultas_limitadas(self):
        with self.assertNumQueries(8):
            self.get("no", "1916", "v1.cap-1")

    def test_busca(self):
        r = self.get("busca", "1916", q="idea")
        self.assertContains(r, "<mark>")
        self.assertContains(r, "encontrado")
        r = self.get("busca", "1916", q="IDÉA simples")  # sem distinguir caixa/acento
        self.assertContains(r, "<mark>")
        r = self.get("busca", "1916", q="zzzzzz")
        self.assertContains(r, "Nada encontrado")
        self.get("busca", "1916")
        self.get("busca", "nova", q="idea")

    def test_busca_ignora_marcacao(self):
        r = self.get("busca", "1916", q="rend")
        self.assertContains(r, "Nada encontrado")

    def test_facsimile(self):
        r = self.get("facsimile", 1, 2)
        self.assertContains(r, "Ler o texto transcrito")
        self.assertContains(r, "Lado a lado")
        r = self.get("facsimile", 1, 2, lado=1)
        self.assertContains(r, "transcricao")
        self.get("facsimile", 1, 999, status=404)
        self.get("facsimile", 9, 1, status=404)


class DownloadTest(PublicoBase):
    def baixar(self, slug, xml_id, formato, status=200):
        r = self.client.get(reverse("obra:baixar", args=[slug, xml_id, formato]))
        self.assertEqual(r.status_code, status, formato)
        return r

    def corpo(self, r):
        return b"".join(r.streaming_content) if r.streaming else r.content

    def test_tei(self):
        r = self.baixar("1916", "v1.cap-1", "xml")
        self.assertIn('filename="sinibaldi-1916-v1-cap-1-idea.xml"', r["Content-Disposition"])
        raiz = etree.fromstring(r.content)
        self.assertEqual(raiz.tag, TEI_NS + "TEI")
        cab = raiz.find(TEI_NS + "teiHeader")
        self.assertIn("IDEA", cab.findtext(f".//{TEI_NS}title"))
        self.assertTrue(cab.findall(f".//{TEI_NS}respStmt"))          # contribuidor
        self.assertEqual(cab.findtext(f".//{TEI_NS}respStmt/{TEI_NS}name"), "ana")
        self.assertTrue(cab.find(f".//{TEI_NS}date").get("when"))
        self.assertTrue(cab.findtext(f".//{TEI_NS}sourceDesc/{TEI_NS}bibl"))
        self.assertIsNotNone(raiz.find(f".//{TEI_NS}div[@type='tese']"))

    def test_txt_html(self):
        r = self.baixar("1916", "v1.t1", "txt")
        txt = r.content.decode()
        self.assertIn("idea", txt)
        self.assertIn("— Notas —", txt)
        r = self.baixar("1916", "v1.t1", "html")
        h = r.content.decode()
        self.assertTrue(h.startswith("<!doctype html>"))
        self.assertIn("<style>", h)
        self.assertIn('id="nota-1"', h)
        self.assertNotIn("<a href=\"/fac-simile", h)
        self.assertIsNotNone(etree.fromstring(h.encode(), etree.HTMLParser()).find(".//body"))

    def test_tex(self):
        r = self.baixar("1916", "v1.cap-1", "tex")
        tex = self.corpo(r).decode()
        self.assertIn("\\begin{document}", tex)
        self.assertIn("\\tese", tex)
        self.assertIn("\\end{document}", tex)

    @override_settings()
    def test_pdf(self):
        if not shutil.which("latexmk"):
            self.skipTest("latexmk ausente")
        r = self.baixar("1916", "v1.t1", "pdf")
        self.assertTrue(self.corpo(r).startswith(b"%PDF"))
        # segunda chamada vem do cache
        with mock.patch("obra.exportacao.subprocess.run", side_effect=AssertionError("recompilou")):
            self.baixar("1916", "v1.t1", "pdf")

    def test_pdf_grande_demais_erro_amigavel(self):
        with mock.patch("obra.exportacao.PDF_MAX_BLOCOS", 0):
            r = self.baixar("1916", "v1.cap-1", "pdf", status=503)
        self.assertContains(r, "grande demais", status_code=503)

    def test_erros(self):
        self.baixar("1916", "v1.cap-1", "zip", status=404)
        self.baixar("1916", "v1.nada", "xml", status=404)
        self.baixar("nada", "v1.cap-1", "xml", status=404)

    def test_nova_e_volume(self):
        r = self.baixar("nova", "v1.t1", "xml")
        etree.fromstring(r.content)
        r = self.client.get(reverse("obra:baixar_volume", args=["1916", 1]))
        self.assertEqual(r.status_code, 200)
        raiz = etree.fromstring(r.content)
        self.assertEqual(len(raiz.findall(f".//{TEI_NS}div[@type='tese']")), 3)
        self.assertEqual(self.client.get(reverse("obra:baixar_volume", args=["1916", 7])).status_code, 404)


class LeituraTest(PublicoBase):
    def test_texto_plano_ignora_marcacao_e_cabecalho(self):
        self.assertEqual(leitura.texto_plano('<p xml:id="a">Um <hi rend="it">dois</hi><fw type="header">X</fw> três</p>'),
                         "Um dois três")

    def test_normalizar_preserva_comprimento(self):
        s = "Ação, Philosophía — ÆTHER ſ"
        self.assertEqual(len(leitura.normalizar(s)), len(s))
        self.assertTrue(leitura.normalizar(s).startswith("acao"))

    def test_arvore_cobrindo(self):
        arv = leitura.Arvore(self.edicao)
        t1 = arv.por_id["v1.t1"]
        self.assertIs(arv.cobrindo(t1.ordem_ini), t1)
        self.assertEqual(arv.cobrindo(t1.ordem_ini).pai_obj.xml_id, "v1.cap-1")
