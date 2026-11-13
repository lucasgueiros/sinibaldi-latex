"""Sumários de capítulo: detecção do do autor (OCR), comando ocultar_sumarios e sumário gerado."""
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase

from obra import sumarios
from obra.models import Bloco

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

    def test_titulo_grudado(self):
        a = sumarios.detectar(None, [p("DIVISÃO DO ENTE SuxMARIO: — Ente necessario. — Ente finito.")])
        self.assertEqual(a[0].titulo_embutido, "DIVISÃO DO ENTE")

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


class SumarioGeradoTest(PublicoBase):
    def cmd(self, *args):
        out = StringIO()
        call_command("ocultar_sumarios", *args, stdout=out)
        return out.getvalue()

    def test_ocultar_gerar_desfazer(self):
        arg = Bloco.objects.get(edicao=self.nova, tipo=Bloco.SUMARIO)
        self.assertIn("1 sumário(s), 1 bloco(s)", self.cmd())
        arg.refresh_from_db()
        self.assertNotEqual(arg.procedencia, Bloco.SUPRIMIDO)          # sem --aplicar, só relata

        r = self.get("no", "nova", "v1.cap-1")
        self.assertContains(r, "Sumário do capítulo.")
        self.assertContains(r, 'class="sumario-cap')                   # gerado, mesmo antes
        self.assertContains(r, "Idea")
        self.assertContains(r, "Termo")
        self.assertRegex(r.content.decode(), r'href="#b\d+"><span class="num">1\.</span>')

        self.assertIn("1 bloco(s) suprimido(s)", self.cmd("--aplicar"))
        arg.refresh_from_db()
        self.assertEqual(arg.procedencia, Bloco.SUPRIMIDO)
        self.assertNotContains(self.get("no", "nova", "v1.cap-1"), "Sumário do capítulo.")
        self.assertIn("0 sumário(s)", self.cmd())                      # já suprimido: nada a fazer

        self.assertIn("1 bloco(s) restaurado(s)", self.cmd("--desfazer"))
        arg.refresh_from_db()
        self.assertEqual(arg.procedencia, Bloco.COPIA)

    def test_diplomatica_e_tese_sem_sumario_gerado(self):
        r = self.get("no", "1916", "v1.cap-1")
        self.assertContains(r, "Sumário do capítulo.")
        self.assertNotContains(r, 'class="sumario-cap')
        self.assertNotContains(self.get("no", "nova", "v1.t1"), 'class="sumario-cap')
