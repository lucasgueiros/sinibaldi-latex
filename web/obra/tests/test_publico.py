"""Parte pública: rotas, leitura, busca, fac-símile e downloads."""
import os
import subprocess
import re
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
        with self.assertNumQueries(6):  # edição, nós, páginas, volumes, volumes com texto, menu de edições
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

    def test_no_botao_editar(self):
        from django.contrib.auth.models import Group
        r = self.get("no", "1916", "v1.cap-1")                       # anônimo: sem botão
        self.assertNotContains(r, ">Editar")
        self.client.force_login(self.user2)                           # logado sem permissão: sem botão
        self.assertNotContains(self.get("no", "1916", "v1.cap-1"), ">Editar")
        self.user2.groups.add(Group.objects.get(name="editores"))
        self.client.force_login(self.user2)
        r = self.get("no", "1916", "v1.t2")                           # 1916: revisão da página onde começa
        self.assertContains(r, 'href="%s"' % reverse("obra:revisar", args=[1, 2]))
        self.assertContains(r, "Editar (p. 2)")
        r = self.get("no", "nova", "v1.cap-1")                        # nova: editor do próprio nó
        self.assertContains(r, 'href="%s"' % reverse("obra:nova_no", args=["nova", "v1.cap-1"]))

    def test_no_consultas_limitadas(self):
        with self.assertNumQueries(8):  # +1: menu de edições do cabeçalho
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

    def test_pdf_demorado_mostra_preparando(self):
        import threading
        liberado = threading.Event()
        pdf = os.path.join(tempfile.mkdtemp(), "x.pdf")
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4 falso")

        def compila(tex, timeout):
            liberado.wait(10)
            return pdf

        with mock.patch("obra.exportacao.pdf_disponivel", return_value=True), \
                mock.patch("obra.exportacao.compilar_pdf", side_effect=compila), \
                mock.patch("obra.exportacao.ESPERA_PADRAO", 0.05):
            r = self.baixar("1916", "v1.cap-1", "pdf", status=202)
            self.assertContains(r, "Preparando", status_code=202)
            self.assertContains(r, 'http-equiv="refresh"', status_code=202)
            self.assertEqual(r["Retry-After"], "15")
            liberado.set()
            with mock.patch("obra.exportacao.ESPERA_PADRAO", 5):
                r = self.baixar("1916", "v1.cap-1", "pdf")
        self.assertEqual(self.corpo(r), b"%PDF-1.4 falso")
        self.assertIn(".pdf", r["Content-Disposition"])

    def test_pdf_erro_amigavel(self):
        from obra.exportacao import ErroExportacao
        with mock.patch("obra.exportacao.pdf_disponivel", return_value=True), \
                mock.patch("obra.exportacao.compilar_pdf", side_effect=ErroExportacao("falhou de propósito")):
            r = self.baixar("1916", "v1.cap-1", "pdf", status=503)
        self.assertContains(r, "falhou de propósito", status_code=503)
        self.assertContains(r, "Voltar ao trecho", status_code=503)

    def test_pdf_volume(self):
        pdf = os.path.join(tempfile.mkdtemp(), "v.pdf")
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4 volume")
        with mock.patch("obra.exportacao.pdf_disponivel", return_value=True), \
                mock.patch("obra.exportacao.compilar_pdf", return_value=pdf) as comp:
            r = self.client.get(reverse("obra:baixar_volume_pdf", args=["1916", 1]))
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="sinibaldi-1916-vol1.pdf"', r["Content-Disposition"])
        tex = comp.call_args[0][0].read_text(encoding="utf-8")   # LaTeX do volume inteiro
        self.assertIn("\\begin{document}", tex)
        self.assertIn("IDEA", tex)                               # parte 1…
        self.assertIn("COSMOLOGIA", tex)                         # …e parte 2
        self.assertEqual(self.client.get(reverse("obra:baixar_volume_pdf", args=["1916", 7])).status_code, 404)

    def test_pdf_por_formato_de_notas(self):
        """?notas= escolhe a diagramação (tex/formatos/); desconhecida -> 404; sem ela, o PDF padrão."""
        pdf = os.path.join(tempfile.mkdtemp(), "x.pdf")
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4 falso")
        with mock.patch("obra.exportacao.pdf_disponivel", return_value=True), \
                mock.patch("obra.exportacao.compilar_pdf_formato", return_value=pdf) as comp:
            for k in ("sem-notas", "1col", "2col", "corpo"):
                r = self.client.get(reverse("obra:baixar", args=["1916", "v1.cap-1", "pdf"]), {"notas": k})
                self.assertEqual(r.status_code, 200)
                self.assertIn(f"-{k}.pdf", r["Content-Disposition"])
                self.assertEqual(comp.call_args[0][1], k)
            r = self.client.get(reverse("obra:baixar_volume_pdf", args=["1916", 1]), {"notas": "2col"})
            self.assertIn("vol1-2col.pdf", r["Content-Disposition"])
            r = self.client.get(reverse("obra:baixar", args=["1916", "v1.cap-1", "pdf"]), {"notas": "x"})
            self.assertEqual(r.status_code, 404)

    def test_pdf_formatos_compilam(self):
        if not shutil.which("latexmk"):
            self.skipTest("latexmk ausente")
        for k, papel in (("sem-notas", 453), ("2col", 595)):
            r = self.client.get(reverse("obra:baixar", args=["1916", "v1.t1", "pdf"]), {"notas": k})
            corpo = self.corpo(r)
            self.assertTrue(corpo.startswith(b"%PDF"), k)
            arq = os.path.join(tempfile.mkdtemp(), "f.pdf")
            with open(arq, "wb") as f:
                f.write(corpo)
            info = subprocess.run(["pdfinfo", arq], capture_output=True, text=True).stdout
            m = re.search(r"Page size:\s+(\d+)", info)
            self.assertTrue(m and abs(int(m.group(1)) - papel) <= 1, (k, info))

    def test_painel_baixar_tem_formato_e_notas(self):
        with mock.patch("obra.exportacao.pdf_disponivel", return_value=True), \
                override_settings(SINIBALDI_DADOS=tempfile.mkdtemp()):
            r = self.get("edicao", "1916")
        self.assertContains(r, 'name="formato"')
        for rotulo in ("Sem notas", "Notas de rodapé, 1 coluna", "Notas de rodapé, 2 colunas", "A4",
                       "Notas no corpo do texto"):
            self.assertContains(r, rotulo)

    def test_sumario_oferece_pdf_do_trecho_e_do_volume(self):
        with mock.patch("obra.exportacao.pdf_disponivel", return_value=True), \
                override_settings(SINIBALDI_DADOS=tempfile.mkdtemp()):
            r = self.get("edicao", "1916")
        self.assertContains(r, reverse("obra:baixar", args=["1916", "v1.cap-1", "pdf"]))
        self.assertContains(r, reverse("obra:baixar_volume_pdf", args=["1916", 1]))
        self.assertContains(r, reverse("obra:baixar_volume", args=["1916", 1]))
        self.assertNotContains(r, "Fac-símile (scan")    # sem o scan original nesta instalação

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


class FacSimileTest(PublicoBase):
    """Scan 2-up sintético: folha 1 = páginas 1 (esquerda, preta) e 2 (direita, branca); folha 2 = 3 e 4."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not shutil.which("mutool"):
            raise __import__("unittest").SkipTest("mutool ausente")
        from PIL import Image, ImageDraw
        cls.dados = tempfile.mkdtemp()
        cls.cache = tempfile.mkdtemp()
        d = os.path.join(cls.dados, "vol1", "paginas")
        os.makedirs(d)
        folhas = []
        for tons in ((0, 255), (255, 0)):
            im = Image.new("L", (400, 280), 255)
            ImageDraw.Draw(im).rectangle((0, 0, 199, 279), fill=tons[0])
            ImageDraw.Draw(im).rectangle((200, 0, 399, 279), fill=tons[1])
            folhas.append(im)
        folhas[0].save(os.path.join(cls.dados, "vol1", "vol1.pdf"), save_all=True, append_images=folhas[1:])
        with open(os.path.join(d, "manifesto.tsv"), "w") as f:
            f.write("id\timpressa\tfolha\tmetade\tpdf_idx\n")
            for i in range(1, 5):
                f.write(f"{i:04d}\t{i}\t{(i + 1) // 2}\t{'ED'[(i + 1) % 2]}\t{i}\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dados, ignore_errors=True)
        shutil.rmtree(cls.cache, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.amb = override_settings(SINIBALDI_DADOS=self.dados, SINIBALDI_CACHE=self.cache)
        self.amb.enable()
        self.env = mock.patch.dict(os.environ, {"SINIBALDI_CACHE": self.cache})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.amb.disable()
        super().tearDown()

    def corpo(self, r):
        return b"".join(r.streaming_content) if r.streaming else r.content

    def tons(self, pdf_bytes):
        """Brilho médio de cada página do PDF (0 = preta, 255 = branca)."""
        import subprocess
        from PIL import Image, ImageStat
        tmp = tempfile.mkdtemp()
        try:
            arq = os.path.join(tmp, "x.pdf")
            with open(arq, "wb") as f:
                f.write(pdf_bytes)
            r = subprocess.run(["mutool", "draw", "-q", "-r", "10", "-o", os.path.join(tmp, "p%d.png"), arq],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            n = len([x for x in os.listdir(tmp) if x.endswith(".png")])
            return [round(ImageStat.Stat(Image.open(os.path.join(tmp, f"p{i}.png")).convert("L")).mean[0])
                    for i in range(1, n + 1)]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_volume_inteiro_em_ordem(self):
        r = self.client.get(reverse("obra:baixar_fac_simile_volume", args=[1]))
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="sinibaldi-fac-simile-vol1.pdf"', r["Content-Disposition"])
        tons = self.tons(self.corpo(r))
        self.assertEqual(len(tons), 4)
        self.assertLess(tons[0], 50)      # p. 1 = metade esquerda (preta) da folha 1
        self.assertGreater(tons[1], 200)
        self.assertGreater(tons[2], 200)
        self.assertLess(tons[3], 50)
        self.assertEqual(self.client.get(reverse("obra:baixar_fac_simile_volume", args=[9])).status_code, 404)

    def test_trecho(self):
        # tese 1 começa na p. 1 e tem <pb n="2"> dentro: páginas 1 e 2
        r = self.client.get(reverse("obra:baixar_fac_simile", args=["1916", "v1.t1"]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("fac-simile.pdf", r["Content-Disposition"])
        tons = self.tons(self.corpo(r))
        self.assertEqual(len(tons), 2)
        self.assertLess(tons[0], 50)
        self.assertGreater(tons[1], 200)
        # parte 2: o título está no fim da p. 2 e a tese 3 na p. 3
        r = self.client.get(reverse("obra:baixar_fac_simile", args=["1916", "v1.parte-2"]))
        self.assertEqual(self.tons(self.corpo(r)), [255, 255])   # pp. 2 e 3: ambas brancas

    def test_links(self):
        r = self.client.get(reverse("obra:edicao", args=["1916"]))
        self.assertContains(r, reverse("obra:baixar_fac_simile_volume", args=[1]))
        self.assertContains(r, reverse("obra:baixar_fac_simile", args=["1916", "v1.cap-1"]))
        r = self.client.get(reverse("obra:no", args=["1916", "v1.cap-1"]))
        self.assertContains(r, "Fac-símile (PDF do scan)")
        r = self.client.get(reverse("obra:facsimile", args=[1, 2]))
        self.assertContains(r, "volume inteiro (PDF")

    def test_sem_scan_erro_amigavel(self):
        os.rename(os.path.join(self.dados, "vol1", "vol1.pdf"), os.path.join(self.dados, "vol1", "x.pdf"))
        try:
            r = self.client.get(reverse("obra:baixar_fac_simile", args=["1916", "v1.t1"]))
            self.assertEqual(r.status_code, 503)
            self.assertContains(r, "não está disponível", status_code=503)
            r = self.client.get(reverse("obra:no", args=["1916", "v1.cap-1"]))
            self.assertNotContains(r, "Fac-símile (PDF do scan)")
        finally:
            os.rename(os.path.join(self.dados, "vol1", "x.pdf"), os.path.join(self.dados, "vol1", "vol1.pdf"))
