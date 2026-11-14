"""Comando corrigir_texto: troca só em texto (nunca em tags), 1916 + cópias + adaptados da nova."""
import re
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase

from obra.management.commands.corrigir_texto import substituir
from obra.models import Bloco, Revisao

from .test_nova import NovaBase

ERRADO = '<p xml:id="x.p1">Logo Deus é infinito, isto 6, a essencia <hi rend="it">isto 6</hi>.</p>'
CERTO = '<p xml:id="x.p1">Logo Deus é infinito, isto é, a essencia <hi rend="it">isto é</hi>.</p>'
PAD = re.compile(r"(?<!\w)(?:isto\ 6)(?!\w)")


class SubstituirTest(SimpleTestCase):
    def test_so_texto(self):
        novo, n = substituir(ERRADO, PAD, "isto é")
        self.assertEqual((novo, n), (CERTO, 2))

    def test_nao_toca_em_tags(self):
        xml = '<p xml:id="isto 6" rend="isto 6">isto 6</p>'
        novo, n = substituir(xml, PAD, "X")
        self.assertEqual(novo, '<p xml:id="isto 6" rend="isto 6">X</p>')
        self.assertEqual(n, 1)

    def test_fronteira_de_palavra(self):
        self.assertEqual(substituir("<p>isto 66 e isto 6</p>", PAD, "isto é"), ("<p>isto 66 e isto é</p>", 1))


class ComandoTest(NovaBase):
    def setUp(self):
        super().setUp()
        self.alvo16 = self.b1916()[-1]
        self.cop = Bloco.objects.get(edicao=self.nova, origem=self.alvo16)
        for b in (self.alvo16, self.cop):
            Bloco.objects.filter(pk=b.pk).update(xml=ERRADO)

    def roda(self, *args):
        out = StringIO()
        call_command("corrigir_texto", "isto 6", "isto é", "--palavra", *args, stdout=out)
        return out.getvalue()

    def test_sem_aplicar_nao_grava(self):
        antes = [(b.pk, b.xml, b.versao) for b in Bloco.objects.order_by("pk")]
        saida = self.roda()
        self.assertIn("use --aplicar", saida)
        self.assertEqual(antes, [(b.pk, b.xml, b.versao) for b in Bloco.objects.order_by("pk")])

    def test_aplica_na_1916_e_na_copia(self):
        self.roda("--aplicar", "--autor", "ana")
        self.alvo16.refresh_from_db()
        self.cop.refresh_from_db()
        self.assertEqual(self.alvo16.xml, CERTO)
        self.assertEqual(self.cop.xml, CERTO)
        self.assertEqual(self.cop.procedencia, Bloco.COPIA)
        rev = Revisao.objects.filter(bloco=self.alvo16).order_by("-pk").first()
        self.assertEqual(rev.comentario, "isto 6 -> isto é")
        self.assertEqual(rev.autor.username, "ana")

    def test_idempotente(self):
        self.roda("--aplicar")
        versao = Bloco.objects.get(pk=self.alvo16.pk).versao
        saida = self.roda("--aplicar")
        self.assertEqual(Bloco.objects.get(pk=self.alvo16.pk).versao, versao)
        self.assertIn("0 bloco(s) alterado(s)", saida)

    def test_adaptado_recebe_a_troca_e_mantem_o_texto_do_editor(self):
        Bloco.objects.filter(pk=self.cop.pk).update(
            procedencia=Bloco.ADAPTADO, xml=ERRADO.replace("infinito", "ilimitado"))
        self.roda("--aplicar")
        self.cop.refresh_from_db()
        self.assertEqual(self.cop.procedencia, Bloco.ADAPTADO)
        self.assertEqual(self.cop.xml, CERTO.replace("infinito", "ilimitado"))

    def test_adaptado_sem_o_trecho_e_avisado(self):
        Bloco.objects.filter(pk=self.cop.pk).update(procedencia=Bloco.ADAPTADO, xml="<p>Reescrito.</p>")
        saida = self.roda("--aplicar")
        self.cop.refresh_from_db()
        self.assertEqual(self.cop.xml, "<p>Reescrito.</p>")
        self.assertIn("conferir à mão", saida)

    def test_bloco_so_da_nova_tambem_e_corrigido(self):
        Bloco.objects.filter(pk=self.cop.pk).update(procedencia=Bloco.ADAPTADO, origem=None, xml=ERRADO)
        Bloco.objects.filter(pk=self.alvo16.pk).update(xml="<p>nada</p>")
        self.roda("--aplicar")
        self.cop.refresh_from_db()
        self.assertEqual(self.cop.xml, CERTO)
