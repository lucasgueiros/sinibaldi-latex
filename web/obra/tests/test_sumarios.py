"""Componentes: sumário de capítulo (<argument>) e aparato do fim do volume (anexo)."""
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase

from obra import anexos, servicos, sumarios
from obra.models import Bloco, Edicao, No

from .test_publico import PublicoBase


def p(xml, tipo=Bloco.PARAGRAFO):
    return Bloco(tipo=tipo, xml=xml if xml.startswith("<") else f"<p>{xml}</p>")


def achar(*blocos):
    return [[blocos.index(b) for b in a.blocos] for a in sumarios.detectar(None, blocos)]


class DetectarTest(SimpleTestCase):
    def test_variantes_do_rotulo(self):
        for rot in ("SussAnt0: —", "SUMMARIO : 7—", "Suwxaxio: —", "SuxwaR)0: —", '"BUMMARIO: —',
                    '<hi rend="sc">SuwMaRIO</hi>0: —', "SuwwARIO; —", "SUMNARIO ; —", "SuwMARIO :: —"):
            with self.subTest(rot):
                self.assertEqual(achar(p(f"{rot} Ente necessario e ente contingente.")), [[0]])

    def test_texto_corrido_nao_e_sumario(self):
        self.assertEqual(achar(p("o homem Supponhamos: — que a coisa seja.")), [])
        self.assertEqual(achar(p("Uma linha qualquer. " * 8 + "Summario: — x.")), [])

    def test_linhas_ate_o_ponto_e_parada_no_artigo(self):
        bs = [p("SussAnt0: — Idea, sua definição. — Divisão geral da idea. —"),
              p("Divisão da idea universal-reflexa. — Reducção das ideas,"),
              p("— Termo, suas especies e propriedades. — Definição e divisão."),
              p("Amrigo ]"), p('<p><hi rend="it">Idea, sua definição e analyse</hi></p>')]
        self.assertEqual(achar(*bs), [[0, 1, 2]])

    def test_linha_com_ponto_continua_se_a_seguinte_abre_com_travessao(self):
        bs = [p("SUNMMARIO: — Descripção do corpo humano. — Orgãos da vida vegetativa."),
              p("— Orgãos da sensibilidade externa. — Orgãos da sensibilidade interna"),
              p("e da locomoção."), p("7. Principaes regiões do corpo humano. — As regiões…")]
        self.assertEqual(achar(*bs), [[0, 1, 2]])

    def test_para_em_tese_italico_e_artigo_mesmo_sem_ponto(self):
        for prox in (p("34. Divisão do ente. — Todo o ente"), p('<p><hi rend="it">Unidade do ente</hi>,</p>'),
                     p("AmnrrGO [."), p('<milestone unit="tese" n="5"/>', Bloco.MARCO)):
            with self.subTest(prox.xml):
                self.assertEqual(achar(p("SUMMARIO: — Unidade do ente, — Verdade do ente,"), prox), [[0]])

    def test_cabecalho_no_meio_e_argument(self):
        bs = [p("SUMMARIO: — Moralidade, sua existencia. — Fontes da mora-"),
              p('<fw type="header">CAPITULO TERCEIRO</fw>', Bloco.CABECALHO),
              p("lidade dos actos humanos."),
              p("<argument><p>— Origem do corpo humano.</p></argument>", Bloco.SUMARIO)]
        self.assertEqual(achar(*bs), [[0, 2], [3]])


class ComponenteSumarioTest(SimpleTestCase):
    def comp(self, *blocos):
        return sumarios.componente(sumarios.detectar(None, blocos)[0])

    def test_um_p_por_assunto_hifenizacao_e_titulo_grudado(self):
        xml = self.comp(p("DIVISÃO DO ENTE SuxMARIO: — Ente necessario e ente contingente. -— Pro-"),
                        p("cesso: Methodo analytico, — Ente simples - composto,"))
        self.assertEqual(xml, ["<head>DIVISÃO DO ENTE</head>",
                               "<argument><p>Ente necessario e ente contingente.</p>"
                               "<p>Processo: Methodo analytico.</p><p>Ente simples - composto.</p></argument>"])

    def test_argument_antigo_preserva_marcacao(self):
        xml = self.comp(p('<argument><p>— Existencia de <hi rend="sc">Deus</hi> . — O atheismo.</p></argument>',
                          Bloco.SUMARIO))
        self.assertEqual(xml, ['<argument><p>Existencia de <hi rend="sc">Deus</hi>.</p><p>O atheismo.</p></argument>'])

    def test_titulo_curto_e_ruido(self):
        self.assertEqual(self.comp(p("IT SuwMARIO :: — Aspecto geral."))[0], "<argument><p>Aspecto geral.</p></argument>")


class AnexoTest(SimpleTestCase):
    def test_divisao(self):
        for t in ("CAPITULO SEGUNDO", "- CAPITULO TERCEIRO", "SECÇÃO Il. — Cosmologia geral.", "LOGICA",
                  "SYNOPSE DA MORAL"):
            self.assertTrue(anexos._e_divisao(t), t)
        for t in ("Juizo e proposição, sua divisão . . . 45", "a) Idea. — Idea é a simples representação"):
            self.assertFalse(anexos._e_divisao(t), t)


class AplicarComponentesTest(PublicoBase):
    """Na 1916 sintética: um sumário de OCR na tese 2 e um índice com capítulo fantasma no fim."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for ed in (cls.edicao, cls.nova):
            fim = Bloco.objects.filter(edicao=ed).order_by("-ordem").first()
            servicos.salvar_blocos(ed, [], [{"xml": x} for x in (
                "<p>SUMMARIO: — Juizo e proposição. — Divisão da</p>", "<p>proposição simples.</p>",
                "<p>INDICE DAS MATERIAS</p>", "<p>Idea e termo . . . 16</p>",
                '<milestone unit="capitulo" xml:id="v1.cap-99"/>', '<head type="rotulo">CAPITULO SEGUNDO</head>',
                "<p>Juizo e proposição . . . 45</p>")], None, ancora=fim.pk)
        # a nova copia a 1916: liga os blocos acrescentados
        novos16 = list(Bloco.objects.filter(edicao=cls.edicao).order_by("-ordem")[:7])[::-1]
        novosN = list(Bloco.objects.filter(edicao=cls.nova).order_by("-ordem")[:7])[::-1]
        for a, b in zip(novosN, novos16):
            a.origem, a.procedencia = b, Bloco.COPIA
        Bloco.objects.bulk_update(novosN, ["origem", "procedencia"])

    def cmd(self, *args):
        out = StringIO()
        call_command("aplicar_componentes", *args, stdout=out)
        return out.getvalue()

    def test_relatorio_nao_grava(self):
        self.assertIn("1 sumário(s), 1 anexo(s)", self.cmd())
        self.assertTrue(No.objects.filter(edicao=self.edicao, xml_id="v1.cap-99").exists())

    def test_aplicar(self):
        self.cmd("--aplicar")
        for ed in (self.edicao, self.nova):
            with self.subTest(ed.slug):
                self.assertFalse(No.objects.filter(edicao=ed, xml_id="v1.cap-99").exists())
                anexo = No.objects.get(edicao=ed, xml_id="v1.indice")
                self.assertEqual((anexo.nivel, anexo.titulo, anexo.pai_id), ("anexo", "INDICE DAS MATERIAS", None))
                xmls = list(Bloco.objects.filter(edicao=ed, ordem__gte=anexo.ordem_ini).order_by("ordem")
                            .values_list("xml", flat=True))
                self.assertEqual(xmls[2:], ['<p type="indice">Idea e termo . . . 16</p>',
                                            '<p type="anexo-titulo">CAPITULO SEGUNDO</p>',
                                            '<p type="indice">Juizo e proposição . . . 45</p>'])
                self.assertTrue(Bloco.objects.filter(
                    edicao=ed, xml="<argument><p>Juizo e proposição.</p><p>Divisão da proposição simples.</p></argument>").exists())
        # nova: tudo volta a ser cópia ligada à 1916
        for b in Bloco.objects.filter(edicao=self.nova, ordem__gte=No.objects.get(edicao=self.nova, xml_id="v1.indice").ordem_ini):
            self.assertEqual((b.procedencia, b.xml), (Bloco.COPIA, b.origem.xml))
        self.assertIn("0 sumário(s), 0 anexo(s)", self.cmd())          # idempotente
        r = self.get("no", "nova", "v1.indice")
        self.assertContains(r, 'data-type="indice"')
        r = self.get("edicao", "nova")
        self.assertContains(r, "INDICE DAS MATERIAS")
