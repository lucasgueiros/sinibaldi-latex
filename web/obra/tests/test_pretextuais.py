"""Componente pré-textual: nível `pretextual`, parágrafos tipados e o comando `aplicar_pretextuais`."""
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from obra import arvore, esquema, pretextuais
from obra.models import PASSO_ORDEM, Bloco, Edicao, No, Volume

PECAS = {
    "volume": 1,
    "pecas": [
        {"tipo": "rosto", "titulo": "FOLHA DE ROSTO", "xml_id": "v1.pre-rosto", "paginas": [-13],
         "pag_blocos": [-13, -13], "blocos": [
            '<p type="centro">D. THIAGO SINIBALDI</p>',
            '<p type="titulo-obra">ELEMENTOS</p>',
        ]},
        {"tipo": "carta", "titulo": "CARTA DE LEÃO XIII", "xml_id": "v1.pre-carta", "paginas": [-3, -2],
         "pag_blocos": [-3, -3, -3, -2, -2], "blocos": [
            '<p type="enderecamento">AO VENERAVEL IRMÃO</p>',
            '<p type="saudacao">Veneravel Irmão,</p>',
            '<p>Bem sabeis que<pb n="-2" facs="paginas/f013.png"/> vivamente approvamos.</p>',
            '<p type="data-local">Dado em Roma, 1893.</p>',
            '<p type="fecho">LEÃO XIII, PAPA</p>',
        ]},
    ],
    "avisos": [], "falhas": [], "ate": 0,
}


class EsquemaTest(SimpleTestCase):
    def test_tipos_pretextuais_validos(self):
        for t in ("titulo-obra", "centro", "enderecamento", "saudacao", "data-local", "fecho"):
            self.assertEqual(esquema.validar_fragmento(f'<p type="{t}">x</p>'), [], t)
        self.assertTrue(esquema.validar_fragmento('<p type="inventado">x</p>'))

    def test_marco_pretextual(self):
        self.assertEqual(esquema.validar_fragmento('<milestone unit="pretextual" xml:id="v1.pre-rosto"/>'), [])
        self.assertIn("pretextual", esquema.NIVEIS)
        self.assertIn("rosto", esquema.PRETEXTUAIS)

    def test_pecas_do_json_validam(self):
        self.assertEqual(pretextuais.validar(PECAS), [])

    def test_paginas_dos_blocos(self):
        self.assertEqual(len(pretextuais.blocos_do_volume(PECAS)), len(pretextuais.paginas_do_volume(PECAS)))
        self.assertEqual(pretextuais.paginas_do_volume(PECAS),
                         [-13] * 4                       # marco, head, 2 blocos do rosto
                         + [-3] * 5 + [-2] * 2)          # marco e head da carta + seus 5 blocos (3 em -3, 2 em -2)


class ArvoreTest(TestCase):
    def test_pretextuais_sao_nos_irmaos_e_nao_engolem_a_parte(self):
        ed = Edicao.objects.create(slug="1916", titulo="D", tipo="diplomatica")
        vol = Volume.objects.create(numero=1, titulo="V1", ano=1917, diretorio="vol1")
        xmls = pretextuais.blocos_do_volume(PECAS) + [
            '<milestone unit="parte" xml:id="v1.parte-1"/>', "<head>INTRODUCÇÃO</head>",
            '<milestone unit="tese" n="1" xml:id="v1.t1"/>', '<p xml:id="v1.t1.p1">Texto.</p>']
        Bloco.objects.bulk_create([Bloco(edicao=ed, ordem=i * PASSO_ORDEM, tipo=esquema.tipo_do_fragmento(x), xml=x,
                                         volume=vol, pagina=1) for i, x in enumerate(xmls, 1)])
        arvore.reconstruir(ed)
        nos = list(No.objects.filter(edicao=ed).order_by("ordem_ini"))
        self.assertEqual([(n.nivel, n.xml_id) for n in nos],
                         [("pretextual", "v1.pre-rosto"), ("pretextual", "v1.pre-carta"),
                          ("parte", "v1.parte-1"), ("tese", "v1.t1")])
        self.assertEqual([n.pai_id for n in nos[:3]], [None, None, None])       # pretextual não tem filhos nem pai
        self.assertEqual(nos[3].pai_id, nos[2].pk)
        self.assertEqual(nos[0].titulo, "FOLHA DE ROSTO")


class ComandoTest(TestCase):
    def setUp(self):
        self.vol = Volume.objects.create(numero=1, titulo="V1", ano=1917, diretorio="vol1")
        self.vol2 = Volume.objects.create(numero=2, titulo="V2", ano=1916, diretorio="vol2")
        self.ed = Edicao.objects.create(slug="1916", titulo="D", tipo="diplomatica")
        self.nova = Edicao.objects.create(slug="nova", titulo="N", tipo="nova")
        ocr = ['<fw type="header">b. THIAGO SINIBALDI</fw>', "<p>ELEMENTOS DE PHILOSOPHIA</p>",
               '<p><pb n="-12" facs="paginas/f003.png"/>IMPRIMATUR lixo</p>',
               '<milestone unit="parte" xml:id="v1.parte-1"/>', "<head>INTRODUCÇÃO</head>",
               '<p xml:id="v1.p1"><pb n="1" facs="paginas/0001.png"/>Corpo.</p>']
        pg = [-13, -13, -12, 1, 1, 1]
        antes = {}
        for ed, pular_fw in ((self.ed, False), (self.nova, True)):
            for i, (x, p) in enumerate(zip(ocr, pg), 1):
                if pular_fw and x.startswith("<fw"):
                    continue                                    # o cabeçalho corrente não é copiado nas derivadas
                b = Bloco.objects.create(edicao=ed, ordem=i * PASSO_ORDEM, tipo=esquema.tipo_do_fragmento(x), xml=x,
                                         volume=self.vol, pagina=p,
                                         **({"origem": antes[x], "procedencia": Bloco.COPIA, "origem_versao_vista": 1}
                                            if ed is self.nova else {}))
                if ed is self.ed:
                    antes[x] = b
        arvore.reconstruir(self.ed)
        arvore.reconstruir(self.nova)
        self.dir = tempfile.TemporaryDirectory()
        (Path(self.dir.name) / "vol1").mkdir()
        (Path(self.dir.name) / "vol1" / "pretextuais.json").write_text(json.dumps(PECAS), encoding="utf-8")

    def tearDown(self):
        self.dir.cleanup()

    def roda(self, *args):
        out = StringIO()
        call_command("aplicar_pretextuais", "--dados", self.dir.name, "--volume", "1", *args, stdout=out)
        return out.getvalue()

    def test_sem_aplicar_so_relata(self):
        antes = Bloco.objects.count()
        self.assertIn("2 peça(s)", self.roda())
        self.assertEqual(Bloco.objects.count(), antes)

    def test_aplica_nas_duas_edicoes_e_preserva_o_corpo(self):
        self.roda("--aplicar")
        for ed in (self.ed, self.nova):
            nos = list(No.objects.filter(edicao=ed).order_by("ordem_ini"))
            self.assertEqual([n.xml_id for n in nos], ["v1.pre-rosto", "v1.pre-carta", "v1.parte-1"], ed.slug)
            self.assertEqual([(n.pagina_ini, n.pagina_fim) for n in nos[:2]], [(-13, -13), (-3, -2)], ed.slug)
            corpo = Bloco.objects.filter(edicao=ed, xml__contains="Corpo.")
            self.assertEqual(corpo.count(), 1)
            self.assertFalse(Bloco.objects.filter(edicao=ed, xml__contains="lixo").exists())
        self.assertFalse(Bloco.objects.filter(edicao=self.ed, tipo=Bloco.CABECALHO).exists())
        pre_nova = Bloco.objects.filter(edicao=self.nova, ordem__lt=Bloco.objects.get(
            edicao=self.nova, xml__contains="parte-1").ordem)
        self.assertTrue(all(b.procedencia == Bloco.COPIA and b.origem_id for b in pre_nova))
        self.assertTrue(all(b.origem.edicao_id == self.ed.pk and b.origem.xml == b.xml for b in pre_nova))

    def test_idempotente(self):
        self.roda("--aplicar")
        n = Bloco.objects.count()
        saida = self.roda("--aplicar")
        self.assertIn("já aplicado", saida)
        self.assertEqual(Bloco.objects.count(), n)

    def test_derivada_com_bloco_editado_e_pulada(self):
        Bloco.objects.filter(edicao=self.nova, xml__contains="ELEMENTOS").update(procedencia=Bloco.ADAPTADO)
        saida = self.roda("--aplicar")
        self.assertIn("pulado", saida)
        self.assertTrue(Bloco.objects.filter(edicao=self.nova, xml__contains="IMPRIMATUR lixo").exists())
