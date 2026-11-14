"""Índice das matérias gerado dos títulos (obra/indice.py)."""
from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from obra import esquema, indice
from obra.models import Bloco


def no(nivel, rotulo, titulo="", ordem=0, pag=1):
    return NS(nivel=nivel, rotulo=rotulo, titulo=titulo, ordem_ini=ordem, volume_id=1, pagina_ini=pag)


IMP = {(1, 1): "1", (1, 5): "17", (1, 9): "33"}


class EntradasTest(SimpleTestCase):
    def test_niveis_e_pagina_impressa(self):
        es = indice.entradas([no("parte", "PARTE PRIMEIRA", "LOGICA", 1, 1), no("tese", "6.", "x", 2, 5),
                              no("capitulo", "CAPITULO PRIMEIRO", "IDEA E TERMO", 3, 5),
                              no("artigo", "Artigo I.", "Divisão da idea.", 4, 9)], IMP)
        self.assertEqual(es, [("parte", "PARTE PRIMEIRA — LOGICA", "1"),
                              ("capitulo", "CAPITULO PRIMEIRO — IDEA E TERMO", "17"),
                              ("artigo", "Artigo I. — Divisão da idea.", "33")])

    def test_ordem_do_texto_e_nao_a_da_lista(self):
        es = indice.entradas([no("capitulo", "CAPITULO B", "BBB", 2), no("capitulo", "CAPITULO A", "AAA", 1)], IMP)
        self.assertEqual([e[1] for e in es], ["CAPITULO A — AAA", "CAPITULO B — BBB"])

    def test_limpa_ruido_do_ocr(self):
        es = indice.entradas([no("artigo", "Artigo 11.", "y", 1), no("artigo", "Artigo |.", "|", 2),
                              no("capitulo", "CAPITULO QUARTO", "ATTRIBUTOS GENÉRICOS DO ENTE 588", 3),
                              no("capitulo", "CAPITULO TERCEIRO", "RACIOCINIO — 65", 4)], IMP)
        self.assertEqual([e[1] for e in es], ["Artigo II.", "Artigo I.", "CAPITULO QUARTO — ATTRIBUTOS GENÉRICOS DO ENTE",
                                              "CAPITULO TERCEIRO — RACIOCINIO"])

    def test_descarta_repeticao_do_titulo_corrente(self):
        es = indice.entradas([no("capitulo", "CAPITULO SEGUNDO", "JUIZO", 1), no("capitulo", "CAPITULO SEGUNDO", "", 2),
                              no("capitulo", "CAPITULO SEGUNDO", "JUIZO", 3)], IMP)
        self.assertEqual(len(es), 1)

    def test_artigo_i_volta_em_capitulo_novo(self):
        es = indice.entradas([no("capitulo", "CAPITULO I", "A", 1), no("artigo", "Artigo I.", "x", 2),
                              no("capitulo", "CAPITULO II", "B", 3), no("artigo", "Artigo I.", "x", 4)], IMP)
        self.assertEqual([e[0] for e in es], ["capitulo", "artigo", "capitulo", "artigo"])

    def test_sem_pagina_sem_label(self):
        self.assertEqual(indice.xml_da_entrada("artigo", "Artigo I.", ""), '<p type="indice-artigo">Artigo I.</p>')
        self.assertEqual(indice.xml_da_entrada("parte", "A & B", "7"),
                         '<p type="indice-parte">A &amp; B<label>7</label></p>')


class EsquemaTest(SimpleTestCase):
    def test_entradas_geradas_validam(self):
        xmls = [indice.xml_da_entrada(n, "X — Y", "3") for n in indice.NIVEIS_INDICE]
        self.assertEqual(esquema.validar_blocos([{"id": None, "xml": x} for x in xmls]), [])


class ComponenteTest(SimpleTestCase):
    def test_mantem_marco_e_head_e_reaproveita_ids(self):
        bs = [Bloco(pk=i, xml=f"<p>{i}</p>") for i in (10, 11, 12, 13)]
        novos = indice.componente(bs, ["<p>a</p>", "<p>b</p>", "<p>c</p>"])
        self.assertEqual([n["id"] for n in novos], [10, 11, 12, 13, None])
        self.assertEqual([n["xml"] for n in novos][:2], ["<p>10</p>", "<p>11</p>"])
        self.assertEqual(indice.atual(bs), ["<p>12</p>", "<p>13</p>"])
