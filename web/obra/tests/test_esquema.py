from django.test import SimpleTestCase

from obra import esquema


class ValidacaoTest(SimpleTestCase):
    def ok(self, xml):
        self.assertEqual(esquema.validar_fragmento(xml), [], xml)

    def ruim(self, xml, trecho):
        erros = esquema.validar_fragmento(xml)
        self.assertTrue(any(trecho in e for e in erros), (xml, erros))

    def test_aceita_vocabulario(self):
        self.ok('<milestone unit="tese" n="3" xml:id="v1.t3"/>')
        self.ok('<head type="rotulo">CAPITULO I</head>')
        self.ok('<p type="escolio" xml:id="a">Texto <hi rend="it">it</hi> <foreign xml:lang="la">ens</foreign>'
                '<pb n="3" facs="paginas/0003.png"/><note place="foot" n="1" xml:id="n"><p>x</p></note></p>')
        self.ok('<argument><p>Sumário</p></argument>')
        self.ok('<fw type="header">3 CABEC</fw>')
        self.ok('<p>antes <fw type="header">3 CABEC</fw> depois</p>')

    def test_rejeita_elemento_fora_do_vocabulario(self):
        self.ruim("<p>a <u>b</u></p>", "<u>")
        self.ruim("<div>x</div>", "<div>")
        self.ruim('<hi rend="it">x</hi>', "não pode ser um bloco")

    def test_rejeita_atributo_e_valor(self):
        self.ruim('<p class="x">a</p>', "class")
        self.ruim('<p type="inventado">a</p>', "inventado")
        self.ruim('<p><hi rend="underline">a</hi></p>', "underline")
        self.ruim('<milestone unit="livro"/>', "livro")

    def test_estrutura(self):
        self.ruim('<p><note place="foot" n="1"><p>a <note place="foot" n="2"><p>b</p></note></p></note></p>',
                  "Nota dentro de nota")
        self.ruim('<p><note place="foot" n="1">texto direto</note></p>', "texto solto")
        self.ruim("<argument>texto<p>a</p></argument>", "texto solto")
        self.ruim('<milestone unit="tese">x</milestone>', "vazio")
        self.ruim("<p>aberto", "malformado")
        self.ruim("", "vazio")
        self.ruim('<p xmlns="http://www.tei-c.org/ns/1.0">a</p>', "namespace")

    def test_ids_repetidos(self):
        self.ruim('<p xml:id="a">x<note place="foot" n="1" xml:id="a"><p>y</p></note></p>', "ID a")
        erros = esquema.validar_blocos(['<p xml:id="a">x</p>', '<p xml:id="a">y</p>', "<u/>"])
        self.assertTrue(any("já usado" in e for e in erros))
        self.assertTrue(any(e.startswith("Bloco 3") for e in erros))

    def test_constantes_para_ui(self):
        self.assertEqual(list(esquema.NIVEIS)[0], "parte")
        self.assertEqual(esquema.TIPOS_PARAGRAFO["enunciado"], "Tese")
        self.assertEqual(set(esquema.REND), {"it", "bold", "sc"})
