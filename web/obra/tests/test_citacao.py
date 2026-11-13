"""Citação ABNT (Word/LaTeX) na parte pública."""
import io
import zipfile
from datetime import date

from django.urls import reverse
from lxml import etree

from obra import citacao

from .base import BaseBanco


def _c(**kw):
    base = dict(ano=1917, volume=1, titulo_volume="Logica – Ontologia – Cosmologia", edicao_txt="5. ed.",
                pi="12", pf="12", trecho="A idea é simples.", url="https://ex.org/edicao/1916/v1.t1/",
                acesso=citacao.data_acesso(date(2026, 11, 13)), chave="sinibaldi1917v1")
    base.update(kw)
    return citacao.Citacao(**base)


class FormatadorTest(BaseBanco):
    def test_chamada_e_paginas(self):
        self.assertEqual(_c().chamada, "(SINIBALDI, 1917, v. 1, p. 12)")
        self.assertEqual(_c(pf="13").chamada, "(SINIBALDI, 1917, v. 1, p. 12-13)")
        self.assertEqual(_c(pi="", pf="").chamada, "(SINIBALDI, 1917, v. 1)")
        self.assertEqual(_c(ano=None, volume=None).chamada, "(SINIBALDI, s.d., p. 12)")
        self.assertEqual(_c().chamada_narrativa, "Sinibaldi (1917, v. 1, p. 12)")

    def test_curta_tem_aspas_e_ponto_depois_da_chamada(self):
        c = _c(trecho='Disse "não" e «sim».')
        self.assertFalse(c.longa)
        self.assertEqual(c.citacao_texto, "“Disse 'não' e 'sim'.” (SINIBALDI, 1917, v. 1, p. 12).")

    def test_longa_sem_aspas(self):
        c = _c(trecho="palavra " * 50)
        self.assertTrue(c.longa)
        self.assertFalse(c.citacao_corpo.startswith("“"))
        self.assertTrue(c.citacao_texto.endswith("(SINIBALDI, 1917, v. 1, p. 12)"))

    def test_referencia_nbr6023(self):
        self.assertEqual(
            _c().referencia_texto,
            "SINIBALDI, Thiago. Elementos de philosophia: Logica – Ontologia – Cosmologia. 5. ed. "
            "Roma: [s. n.], 1917. v. 1, p. 12. Disponível em: <https://ex.org/edicao/1916/v1.t1/>. Acesso em: 13 nov. 2026.")
        self.assertIn(("Elementos de philosophia", True), _c().referencia)

    def test_data_de_acesso(self):
        self.assertEqual(citacao.data_acesso(date(2026, 5, 2)), "2 maio 2026")

    def test_latex_escapa_e_usa_abntex2(self):
        c = _c(trecho="100% de A & B_c")
        t = c.latex()
        self.assertIn(r"“100\% de A \& B\_c” \cite[v.~1, p.~12]{sinibaldi1917v1}.", t)
        self.assertIn("@book{sinibaldi1917v1,", t)
        self.assertIn("edition = {5}", t)
        self.assertIn("urlaccessdate = {13 nov. 2026}", t)
        longa = _c(trecho="x " * 200).latex()
        self.assertIn("\\begin{citacao}", longa)
        self.assertIn("\\end{citacao}", longa)

    def test_docx_valido_e_com_formatacao_abnt(self):
        for c in (_c(), _c(trecho="palavra " * 50), _c(trecho="")):
            z = zipfile.ZipFile(io.BytesIO(c.docx()))
            self.assertIsNone(z.testzip())
            for nome in z.namelist():
                etree.fromstring(z.read(nome))          # todo o XML é bem formado
            doc = z.read("word/document.xml").decode()
            self.assertIn("REFERÊNCIAS", doc)
            self.assertIn("Elementos de philosophia", doc)
        longa = zipfile.ZipFile(io.BytesIO(_c(trecho="palavra " * 50).docx())).read("word/document.xml").decode()
        self.assertIn('w:left="2268"', longa)           # recuo de 4 cm
        self.assertIn('w:val="20"', longa)              # corpo 10
        self.assertIn("<w:b/>", longa)                  # título em negrito

    def test_docx_escapa_xml(self):
        doc = zipfile.ZipFile(io.BytesIO(_c(trecho="a < b & c").docx())).read("word/document.xml").decode()
        self.assertIn("a &lt; b &amp; c", doc)


class RotaTest(BaseBanco):
    def url(self, xml_id="v1.t1", slug="1916"):
        return reverse("obra:citar", args=[slug, xml_id])

    def test_sem_trecho_cita_o_no(self):
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SINIBALDI, 1917, v. 1, p. 1")
        self.assertContains(r, "<strong>Elementos de philosophia</strong>")
        self.assertContains(r, "abntex2cite")

    def test_post_com_trecho_e_paginas(self):
        r = self.client.post(self.url(), {"trecho": "A idea é\n simples", "pi": "1", "pf": "2", "bloco": "7"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "“A idea é simples” (SINIBALDI, 1917, v. 1, p. 1-2).")
        self.assertContains(r, "#b7")

    def test_pagina_inventada_cai_no_padrao_e_nao_injeta(self):
        r = self.client.get(self.url(), {"trecho": "x", "pi": "<script>", "pf": "999"})
        self.assertNotContains(r, "<script>alert")
        self.assertNotContains(r, "999")

    def test_trecho_html_e_escapado(self):
        r = self.client.post(self.url(), {"trecho": "<img src=x onerror=1>"})
        self.assertNotContains(r, "<img src=x")

    def test_trecho_longo_demais_recusado(self):
        r = self.client.post(self.url(), {"trecho": "a " * (citacao.LIMITE_TRECHO)})
        self.assertEqual(r.status_code, 400)

    def test_downloads(self):
        dados = {"trecho": "A idea é simples", "pi": "1", "pf": "1"}
        r = self.client.post(self.url(), {**dados, "formato": "docx"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(".docx", r["Content-Disposition"])
        self.assertIsNone(zipfile.ZipFile(io.BytesIO(r.content)).testzip())
        r = self.client.post(self.url(), {**dados, "formato": "tex"})
        self.assertContains(r, "\\cite[v.~1, p.~1]{sinibaldi1917v1}")
        self.assertIn(".tex", r["Content-Disposition"])
        r = self.client.post(self.url(), {**dados, "formato": "txt"})
        self.assertContains(r, "REFERÊNCIA")

    def test_no_inexistente_404(self):
        self.assertEqual(self.client.get(self.url("nao-existe")).status_code, 404)

    def test_pagina_de_leitura_tem_o_botao(self):
        r = self.client.get(reverse("obra:no", args=["1916", "v1.t1"]))
        self.assertContains(r, "data-ct-flutuante")
        self.assertContains(r, 'data-ct-form')
        self.assertContains(r, self.url())
