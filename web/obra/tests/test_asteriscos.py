"""Componente asterisco: fragmento, esquema, ida e volta HTML, e o comando aplicar_asteriscos."""
import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase
from lxml import etree

from obra import asteriscos, esquema, tei
from obra.models import PASSO_ORDEM, Bloco

from .test_nova import NovaBase

ANCORA = '<anchor type="asterisco"/>'
CORPO = ('<p xml:id="x.p1">Primeira frase termina aqui. Segunda frase segue<hi rend="it"> em itálico</hi>'
         ' e acaba.<note place="foot" n="1" xml:id="x.n1"><p>Texto da nota até aqui e depois dele.</p></note></p>')


class FragmentoTest(SimpleTestCase):
    def test_solto(self):
        self.assertTrue(asteriscos.eh_solto("<p>*</p>"))
        self.assertTrue(asteriscos.eh_solto('<p xml:id="v1.t1.p3"> * </p>'))
        self.assertFalse(asteriscos.eh_solto("<p>*a</p>"))
        self.assertEqual(asteriscos.converter_solto('<p xml:id="a.b">*</p>'), f'<p xml:id="a.b">{ANCORA}</p>')
        self.assertIsNone(asteriscos.converter_solto("<p>texto</p>"))

    def test_no_corpo(self):
        novo, motivo = asteriscos.inserir_apos(CORPO, "termina aqui.")
        self.assertIsNone(motivo)
        self.assertIn(f"termina aqui.{ANCORA} Segunda frase", novo)
        self.assertEqual(esquema.validar_blocos([{"id": None, "xml": novo}]), [])

    def test_depois_de_trecho_que_atravessa_marca(self):
        novo, _ = asteriscos.inserir_apos(CORPO, "segue em itálico")
        self.assertIn(f'em itálico{ANCORA}</hi> e acaba', novo)

    def test_no_meio_da_nota(self):
        novo, motivo = asteriscos.inserir_apos(CORPO, "Texto da nota até aqui", nota=1)
        self.assertIsNone(motivo)
        self.assertIn(f"até aqui{ANCORA} e depois dele", novo)
        self.assertEqual(esquema.validar_blocos([{"id": None, "xml": novo}]), [])
        # o corpo não foi tocado
        self.assertNotIn(ANCORA, novo.split("<note")[0])

    def test_corpo_nao_enxerga_a_nota_nem_o_contrario(self):
        self.assertEqual(asteriscos.inserir_apos(CORPO, "Texto da nota")[1], "trecho não encontrado")
        self.assertEqual(asteriscos.inserir_apos(CORPO, "frase", nota=1)[1], "trecho não encontrado")
        self.assertIn("não existe", asteriscos.inserir_apos(CORPO, "frase", nota=7)[1])

    def test_ambiguo_e_ausente(self):
        self.assertIn("ambíguo", asteriscos.inserir_apos(CORPO, "frase")[1])
        self.assertEqual(asteriscos.inserir_apos(CORPO, "nada disso")[1], "trecho não encontrado")

    def test_tolera_espaco(self):
        novo, motivo = asteriscos.inserir_apos(CORPO, "termina   aqui.")
        self.assertIsNone(motivo)
        self.assertIn(ANCORA, novo)


class EsquemaTest(SimpleTestCase):
    def test_tipo_invalido(self):
        erros = esquema.validar_blocos([{"id": None, "xml": '<p>a<anchor type="estrela"/>b</p>'}])
        self.assertTrue(erros)

    def test_vazio(self):
        erros = esquema.validar_blocos([{"id": None, "xml": '<p>a<anchor type="asterisco">x</anchor>b</p>'}])
        self.assertTrue(erros)

    def test_ida_e_volta_html(self):
        xml = f'<p>antes {ANCORA} depois<note place="foot" n="1"><p>na {ANCORA} nota</p></note></p>'
        html = tei.fragmento_para_html(xml)
        self.assertEqual(html.count('data-tei="anchor"'), 2)
        blocos = tei.html_para_blocos(html)
        self.assertEqual(len(blocos), 1)
        self.assertEqual(etree.fromstring(blocos[0]["xml"]).xpath("count(.//anchor[@type='asterisco'])"), 2)


class ComandoTest(NovaBase):
    def setUp(self):
        super().setUp()
        self.alvo16 = self.b1916()[-1]
        self.cop = Bloco.objects.get(edicao=self.nova, origem=self.alvo16)
        for b in (self.alvo16, self.cop):
            Bloco.objects.filter(pk=b.pk).update(xml=CORPO)
        # um `*` solto, na 1916 e na sua cópia
        s16 = Bloco.objects.create(edicao=self.e1916, ordem=self.alvo16.ordem + PASSO_ORDEM, tipo=Bloco.PARAGRAFO,
                                   xml="<p>*</p>", volume=self.vol, pagina=self.alvo16.pagina)
        Bloco.objects.create(edicao=self.nova, ordem=s16.ordem, tipo=Bloco.PARAGRAFO, xml="<p>*</p>",
                             volume=self.vol, pagina=s16.pagina, origem=s16, procedencia=Bloco.COPIA)
        self.s16 = s16

    def lista(self, *linhas):
        fd, caminho = tempfile.mkstemp(suffix=".tsv")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("volume\tpagina\tdepois_de\tnota\n")
            f.write("".join("\t".join(l) + "\n" for l in linhas))
        self.addCleanup(os.unlink, caminho)
        return caminho

    def roda(self, *args):
        out = StringIO()
        call_command("aplicar_asteriscos", *args, stdout=out)
        return out.getvalue()

    def test_sem_aplicar_nao_grava(self):
        antes = [(b.pk, b.xml, b.versao) for b in Bloco.objects.order_by("pk")]
        saida = self.roda()
        self.assertIn("use --aplicar", saida)
        self.assertEqual(antes, [(b.pk, b.xml, b.versao) for b in Bloco.objects.order_by("pk")])

    def test_solto_vira_componente_nas_duas_edicoes(self):
        self.roda("--aplicar")
        self.s16.refresh_from_db()
        self.assertEqual(self.s16.xml, f"<p>{ANCORA}</p>")
        nova = Bloco.objects.get(edicao=self.nova, origem=self.s16)
        self.assertEqual(nova.xml, self.s16.xml)
        self.assertEqual(nova.procedencia, Bloco.COPIA)

    def test_lista_corpo_e_nota_replicados_na_nova(self):
        pag = str(self.alvo16.pagina)
        caminho = self.lista(("1", pag, "termina aqui.", ""), ("1", pag, "Texto da nota até aqui", "1"))
        self.roda("--aplicar", "--sem-solitarios", "--lista", caminho)
        self.alvo16.refresh_from_db()
        self.cop.refresh_from_db()
        self.assertEqual(self.alvo16.xml.count(ANCORA), 2)
        self.assertEqual(self.cop.xml, self.alvo16.xml)
        self.assertEqual(self.cop.procedencia, Bloco.COPIA)

    def test_adaptado_recebe_a_insercao_se_o_trecho_existe(self):
        Bloco.objects.filter(pk=self.cop.pk).update(
            procedencia=Bloco.ADAPTADO, xml=CORPO.replace("acaba", "termina"))
        caminho = self.lista(("1", str(self.alvo16.pagina), "termina aqui.", ""))
        saida = self.roda("--aplicar", "--sem-solitarios", "--lista", caminho)
        self.cop.refresh_from_db()
        self.assertEqual(self.cop.procedencia, Bloco.ADAPTADO)
        self.assertIn(f"termina aqui.{ANCORA}", self.cop.xml)
        self.assertIn("e termina.", self.cop.xml)   # texto adaptado preservado
        self.assertNotIn("à mão", saida)

    def test_adaptado_sem_o_trecho_e_avisado(self):
        Bloco.objects.filter(pk=self.cop.pk).update(
            procedencia=Bloco.ADAPTADO, xml="<p>Reescrito por completo.</p>")
        caminho = self.lista(("1", str(self.alvo16.pagina), "termina aqui.", ""))
        saida = self.roda("--aplicar", "--sem-solitarios", "--lista", caminho)
        self.cop.refresh_from_db()
        self.assertEqual(self.cop.xml, "<p>Reescrito por completo.</p>")
        self.assertIn("inserir à mão", saida)

    def test_pendencia_na_lista(self):
        caminho = self.lista(("1", str(self.alvo16.pagina), "texto que não existe", ""), ("9", "1", "x", ""))
        saida = self.roda("--sem-solitarios", "--lista", caminho)
        self.assertIn("trecho não encontrado", saida)
        self.assertIn("volume inexistente", saida)
