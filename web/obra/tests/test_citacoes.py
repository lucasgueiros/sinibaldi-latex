"""Componente de citação: dialeto, reconhecimento pelas aspas, cadastro, telas e saídas."""
import itertools
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from lxml import etree

from obra import arvore, citacoes, esquema, exportacao, leitura, referencias, servicos, servicos_citacoes, tei
from obra.models import PASSO_ORDEM, Bloco, Citacao, Edicao, Fonte, No, Pagina, Volume


def ids(prefixo="c"):
    n = itertools.count(1)
    return lambda: f"{prefixo}{next(n)}"


def marcar(xml, novo_id=None):
    return citacoes.marcar_xml(xml, novo_id or ids())


# ---------------------------------------------------------------------------------- dialeto
class DialetoTest(SimpleTestCase):
    def test_citacao_interrompida_valida_e_ida_e_volta_html(self):
        x = ('<p>Hegel diz que <quote type="direta" xml:id="c1">algo <hi rend="it">é</hi> assim</quote>, porém, '
             '<quote type="direta" corresp="#c1">e assado<pb n="3" facs="paginas/0003.png"/></quote> '
             '<bibl corresp="#c1">(Phän., p. 3)</bibl>.</p>')
        self.assertEqual(esquema.validar_fragmento(x), [])
        h = tei.fragmento_para_html(x)
        self.assertIn('<q data-tei="quote" data-type="direta" data-xmlid="c1">', h)
        self.assertIn('<cite data-tei="bibl" data-corresp="#c1">', h)
        self.assertEqual(tei.html_para_fragmento(h), x)

    def test_erros(self):
        casos = {
            '<p><quote type="direta">x</quote></p>': "sem xml:id nem corresp",
            '<p><quote type="direta" xml:id="a" corresp="#b">x</quote></p>': "não os dois",
            '<p><quote xml:id="a">x</quote></p>': "exige type",
            '<p><quote type="outra" xml:id="a">x</quote></p>': "inválido",
            '<p><quote type="direta" xml:id="a">x<quote type="mencao">y</quote></quote></p>': "dentro de citação",
            '<p><bibl corresp="a">x</bibl></p>': "corresp inválido",
        }
        for x, msg in casos.items():
            with self.subTest(x=x):
                self.assertTrue(any(msg in e for e in esquema.validar_fragmento(x)), esquema.validar_fragmento(x))

    def test_mencao_dispensa_id_e_nota_dentro_de_citacao_pode_citar(self):
        self.assertEqual(esquema.validar_fragmento('<p>a palavra <quote type="mencao">racional</quote></p>'), [])
        x = ('<p><quote type="direta" xml:id="a">x<note place="foot" n="1"><p>cf. '
             '<quote type="direta" xml:id="b">y</quote></p></note></quote></p>')
        self.assertEqual(esquema.validar_fragmento(x), [])

    def test_importacao_desembrulha_citacao_sem_tipo_e_aninhada(self):
        rel = tei.Relatorio()
        el = etree.fromstring('<p>a <quote>b</quote> <quote type="direta" xml:id="x">c <quote type="direta" '
                              'xml:id="y">d</quote></quote></p>')
        _, novo = tei.converter_bloco(el, rel)
        self.assertEqual(tei.serializar_fragmento(novo), '<p>a b <quote type="direta" xml:id="x">c d</quote></p>')

    def test_aninhar_tira_prefixo_tambem_do_corresp(self):
        blocos = [{"xml": '<p><quote type="direta" xml:id="v2.cit-a">x</quote> <bibl corresp="#v2.cit-a">(l. 1)</bibl></p>',
                   "pagina": None}]
        s = tei.serializar_tei(tei.aninhar(blocos, remover_prefixo="v2."))
        self.assertIn('xml:id="cit-a"', s)
        self.assertIn('corresp="#cit-a"', s)


# ------------------------------------------------------------------------------- detector
class DetectorTest(SimpleTestCase):
    def test_exemplo_do_pedido_aspas_retas_interrompidas(self):
        y, rel = marcar('<p>Hegel fala que "algo é assim", porém, " e assado". Fim.</p>')
        self.assertEqual(y, '<p>Hegel fala que <quote type="direta" xml:id="c1">algo é assim</quote>, porém, '
                            '<quote type="direta" corresp="#c1">e assado</quote>. Fim.</p>')
        self.assertEqual((rel.diretas, rel.continuacoes), (1, 1))

    def test_guillemets_com_referencia_e_italico_dentro(self):
        y, rel = marcar('<p>Diz S. Thomaz: « Prius debet addiscere <hi rend="it">logicam</hi>, quam alias scientias » '
                        '(In II Met., l. V). — Outros</p>')
        self.assertEqual(y, '<p>Diz S. Thomaz: <quote type="direta" xml:id="c1">Prius debet addiscere <hi rend="it">'
                            'logicam</hi>, quam alias scientias</quote> <bibl corresp="#c1">(In II Met., l. V)</bibl>.'
                            ' — Outros</p>')
        self.assertEqual(rel.bibls, 1)

    def test_referencia_depois_do_ponto_e_titulo_so_em_italico(self):
        y, _ = marcar('<p>«uma frase bem longa aqui citada». (<hi rend="it">Sum</hi>. <hi rend="it">Th</hi>., p. 1, q. 85).</p>')
        self.assertIn('</quote>. <bibl corresp="#c1">(<hi rend="it">Sum</hi>.', y)
        y, _ = marcar('<p>«uma frase bem longa aqui citada» (<hi rend="it">Lettres</hi>).</p>')
        self.assertIn('<bibl corresp="#c1">(<hi rend="it">Lettres</hi>)</bibl>', y)

    def test_parenteses_sem_cara_de_referencia_ficam(self):
        y, _ = marcar('<p>«uma frase bem longa aqui citada» (isto é, o autor)</p>')
        self.assertNotIn("<bibl", y)

    def test_mencoes_curtas(self):
        y, rel = marcar('<p>a palavra « racional » e as ideas «ente e nada» fossem</p>')
        self.assertEqual(y, '<p>a palavra <quote type="mencao">racional</quote> e as ideas '
                            '<quote type="mencao">ente e nada</quote> fossem</p>')
        self.assertEqual((rel.mencoes, rel.diretas), (2, 0))

    def test_aspas_internas_padronizadas_e_nota_e_pagina_dentro(self):
        y, _ = marcar('<p>M.: «Uma garrafa «contendo» carbonato<pb n="5" facs="x"/> é ideal<note place="foot" n="1">'
                      '<p>Cf. «Kreislauf des Lebens und so weiter» (p. 3).</p></note> o principio vital.» Não</p>')
        self.assertIn('<quote type="direta" xml:id="c1">Uma garrafa “contendo” carbonato<pb n="5" facs="x"/>', y)
        self.assertIn('<note place="foot" n="1"><p>Cf. <quote type="direta" xml:id="c2">Kreislauf', y)
        self.assertEqual(esquema.validar_fragmento(y), [])

    def test_familias_trocadas_pelo_ocr(self):
        y, _ = marcar('<p>diz «isto é uma citação um tanto longa” e segue</p>')
        self.assertIn('<quote type="direta" xml:id="c1">isto é uma citação um tanto longa</quote> e segue', y)

    def test_aspa_reta_entre_letras_nao_e_aspa(self):
        y, rel = marcar('<p>ao Exc"e Rev"º Senhor Bispo</p>')
        self.assertEqual(rel.total, 0)
        self.assertEqual(y, '<p>ao Exc"e Rev"º Senhor Bispo</p>')

    def test_idempotente_e_texto_ja_marcado_intocado(self):
        y, _ = marcar('<p>«primeira citação com muitas palavras» e «segunda citação com muitas palavras»</p>')
        z, rel = marcar(y, ids("d"))
        self.assertEqual((z, rel.total), (y, 0))

    def test_nao_pareia_entre_niveis(self):
        y, rel = marcar('<p>abre <hi rend="it">«dentro do itálico</hi> e fecha fora »</p>')
        self.assertEqual(rel.total, 0)
        self.assertEqual(rel.sem_par, 2)

    def test_ocorrencias(self):
        y, _ = marcar('<p>«A frase um longa», diz Vogt, «e a frase dois» (Leçons, pag. 12).</p>')
        oc = citacoes.ocorrencias_xml(y)["c1"]
        self.assertEqual(oc.texto, "A frase um longa […] e a frase dois")
        self.assertEqual(oc.referencia_autor, "(Leçons, pag. 12)")


# ----------------------------------------------------------------------------- referências
class ReferenciasTest(SimpleTestCase):
    def fonte(self, **kw):
        base = dict(chave="leon", entrada="book", papel="critica", abreviatura="", autor="Thomas Aquinas", editor="",
                    tradutor="", titulo="Summa theologiae", subtitulo="", titulo_maior="Opera omnia", serie="",
                    volume="4", edicao="", local="Romae", editora="Polyglotta", ano="1888", paginas="", periodico="",
                    idioma="", isbn="", doi="", url="", nota="")
        base.update(kw)
        return Fonte(**base)

    def test_bibtex(self):
        b = referencias.bibtex(self.fonte(abreviatura="ed. Leonina", nota="50% & mais"))
        self.assertTrue(b.startswith("@book{leon,\n  author = {Thomas Aquinas},"))
        self.assertIn("maintitle = {Opera omnia}", b)
        self.assertIn("shorthand = {ed. Leonina}", b)
        self.assertIn(r"note = {50\% \& mais}", b)

    def test_referencia_precisa(self):
        c = Citacao(autor_citado="Tomás de Aquino", obra_citada="Summa theologiae", lugar="I, q. 2, a. 3",
                    fonte=self.fonte(abreviatura="ed. Leonina"), pagina_fonte="31",
                    traducao=self.fonte(chave="trad", papel="traducao", tradutor="Silva, A.", titulo="Suma teológica",
                                        autor="", ano="2001", volume=""), pagina_traducao="160")
        seg = referencias.partes(c)
        self.assertEqual(referencias.texto(seg), "(Tomás de Aquino, Summa theologiae, I, q. 2, a. 3; ed. Leonina, "
                                                 "p. 31; trad.: Silva (trad.), Suma teológica, 2001, p. 160)")
        self.assertIn(r"\emph{Summa theologiae}", referencias.latex(seg))
        self.assertIn("<i>Summa theologiae</i>", referencias.html(seg))
        self.assertEqual(referencias.autocite(c), r"\autocites[31]{leon}[160]{trad}")

    def test_sem_dados_nao_ha_referencia(self):
        self.assertEqual(referencias.partes(Citacao()), [])


# --------------------------------------------------------------------------------- banco
TEI = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div type="volume"><pb n="10" facs="paginas/0010.png"/>
<div type="capitulo" xml:id="cap-1"><head>CAPITULO</head>
<p>Diz S. Thomaz: « Prius philosophus debet addiscere logicam quam alias scientias » (In II Met., l. V). Outro.</p>
<p>Hegel fala que "algo é assim, segundo o autor", porém, "e assado"<pb n="11" facs="paginas/0011.png"/> e «Uma
segunda citação, na página seguinte, sem referência nenhuma».</p>
<p>Sem aspas.</p></div></div></body></text></TEI>"""


class CitacoesBanco(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.ana = U.objects.create_superuser("ana", password="x")
        cls.sem = U.objects.create_user("sem", password="x")
        cls.e1916 = Edicao.objects.create(slug="1916", titulo="Diplomática", tipo="diplomatica")
        cls.nova = Edicao.objects.create(slug="nova", titulo="Nova edição", tipo="nova")
        cls.vol = Volume.objects.create(numero=1, titulo="V1", ano=1917, diretorio="vol1")
        rel = tei.Relatorio()
        dados = tei.achatar(etree.fromstring(TEI.encode()), numero=1, relatorio=rel)
        Bloco.objects.bulk_create([Bloco(edicao=cls.e1916, ordem=i * PASSO_ORDEM, tipo=d.tipo, xml=d.xml, volume=cls.vol,
                                         pagina=d.pagina) for i, d in enumerate(dados, 1)])
        Pagina.objects.bulk_create([Pagina(volume=cls.vol, seq=s, arquivo=a, impressa=str(s)) for s, a in rel.paginas.items()])
        orig = list(Bloco.objects.filter(edicao=cls.e1916).order_by("ordem"))
        Bloco.objects.bulk_create([Bloco(edicao=cls.nova, ordem=b.ordem, tipo=b.tipo, xml=b.xml, volume=b.volume,
                                         pagina=b.pagina, origem=b, procedencia=Bloco.COPIA) for b in orig])
        arvore.reconstruir(cls.e1916)
        arvore.reconstruir(cls.nova)

    def marcar_tudo(self):
        _, alt = servicos_citacoes.marcar_edicao(self.e1916, aplicar=True)
        servicos_citacoes.propagar_para_nova(alt, aplicar=True)
        return alt

    def test_marcar_indexa_e_propaga_para_a_nova_com_os_mesmos_ids(self):
        alt = self.marcar_tudo()
        self.assertEqual(len(alt), 2)
        cs = list(Citacao.objects.order_by("pagina", "xml_id"))
        self.assertEqual(len(cs), 3)
        self.assertTrue(all(c.xml_id.startswith("v1.cit-") for c in cs))
        hegel = next(c for c in cs if c.texto.startswith("algo"))
        self.assertEqual(hegel.texto, "algo é assim, segundo o autor […] e assado")
        thomaz = next(c for c in cs if c.texto.startswith("Prius"))
        self.assertEqual((thomaz.referencia_autor, thomaz.pagina, thomaz.volume_id), ("(In II Met., l. V)", 10, self.vol.pk))
        segunda = next(c for c in cs if c.texto.startswith("Uma"))
        self.assertEqual(segunda.pagina, 11)             # o <pb> do meio do parágrafo conta
        for b in Bloco.objects.filter(edicao=self.nova, tipo=Bloco.PARAGRAFO):
            self.assertEqual(b.xml, b.origem.xml)
            self.assertEqual(b.procedencia, Bloco.COPIA)
        _, de_novo = servicos_citacoes.marcar_edicao(self.e1916)
        self.assertEqual(de_novo, [])                    # idempotente

    def test_gravar_pelo_editor_cria_e_inativa_fichas(self):
        b = Bloco.objects.filter(edicao=self.e1916, xml__contains="Sem aspas").get()
        xml = '<p>Sem aspas, mas <quote type="indireta" xml:id="v1.cit-ind">uma paráfrase</quote>.</p>'
        servicos.salvar_blocos(self.e1916, [b.pk], [{"id": b.pk, "versao": b.versao, "xml": xml}], self.ana)
        c = Citacao.objects.get(xml_id="v1.cit-ind")
        self.assertEqual((c.tipo, c.texto, c.pagina), ("indireta", "uma paráfrase", 11))
        b.refresh_from_db()
        servicos.salvar_blocos(self.e1916, [b.pk], [{"id": b.pk, "versao": b.versao, "xml": "<p>Sem aspas.</p>"}], self.ana)
        servicos_citacoes.reindexar()
        self.assertFalse(Citacao.objects.get(xml_id="v1.cit-ind").ativa)

    def test_converter_detecta_para_o_editor(self):
        self.client.force_login(self.ana)
        r = self.client.post("/edicao-colaborativa/converter/", json.dumps({
            "de": "html", "conteudo": '<p data-tei="p">Ele diz: «uma citação qualquer bem longa» (l. 2).</p>',
            "detectar": True, "prefixo": "v1."}), content_type="application/json")
        d = r.json()
        self.assertEqual(d["marcadas"], 1)
        self.assertIn('<q data-tei="quote" data-type="direta" data-xmlid="v1.cit-', d["html"])
        self.assertIn('<cite data-tei="bibl"', d["html"])
        self.assertIn("1 citação(ões) direta(s)", d["relatorio"])

    def test_telas(self):
        self.marcar_tudo()
        c = Citacao.objects.get(texto__startswith="Prius")
        self.client.force_login(self.sem)
        self.assertEqual(self.client.get("/edicao-colaborativa/citacoes/").status_code, 403)
        self.client.force_login(self.ana)
        r = self.client.get("/edicao-colaborativa/citacoes/?ref=com")
        self.assertContains(r, c.xml_id)
        self.assertNotContains(r, "Uma segunda")
        r = self.client.get(f"/edicao-colaborativa/citacoes/{c.xml_id}/")
        self.assertContains(r, "(SINIBALDI, 1917, v. 1, p. 10)")
        self.assertContains(r, "destaque-citacao")
        r = self.client.post("/edicao-colaborativa/fontes/nova/", {"chave": "leonina-met", "papel": "critica",
                             "entrada": "book", "titulo": "In Metaphysicam", "abreviatura": "ed. Marietti", "ano": "1950"})
        self.assertEqual(r.status_code, 302)
        f = Fonte.objects.get(chave="leonina-met")
        r = self.client.post(f"/edicao-colaborativa/citacoes/{c.xml_id}/", {
            "tipo": "direta", "estado": "detectada", "autor_citado": "Tomás de Aquino",
            "obra_citada": "In Metaphysicam", "lugar": "lib. II, lect. 5", "fonte": f.pk, "pagina_fonte": "88"})
        self.assertEqual(r.status_code, 302)
        c.refresh_from_db()
        self.assertEqual((c.estado, c.pagina_fonte), (Citacao.REFERENCIADA, "88"))
        r = self.client.get(f"/edicao-colaborativa/citacoes/{c.xml_id}/")
        self.assertContains(r, "ed. Marietti, p. 88")
        r = self.client.get("/edicao-colaborativa/fontes.bib?usadas=1")
        self.assertEqual(r.content.decode().split(",")[0], "@book{leonina-met")
        outras = list(Citacao.objects.exclude(pk=c.pk).values_list("xml_id", flat=True))
        r = self.client.post("/edicao-colaborativa/citacoes/lote/", {"sel": outras, "autor_citado": "Hegel"})
        self.assertEqual(Citacao.objects.filter(autor_citado="Hegel").count(), 2)

    def test_leitura_e_saidas_da_nova_trocam_a_referencia(self):
        self.marcar_tudo()
        f = Fonte.objects.create(chave="leon", titulo="In Met.", abreviatura="ed. Leonina")
        Citacao.objects.filter(texto__startswith="Prius").update(autor_citado="Tomás", fonte=f, pagina_fonte="7")
        Citacao.objects.filter(texto__startswith="Uma").update(autor_citado="Anônimo", lugar="c. 1")
        no_nova = No.objects.get(edicao=self.nova, xml_id="v1.cap-1")
        h = self.client.get(f"/edicao/nova/{no_nova.xml_id}/").content.decode()
        self.assertIn('<span class="ref-precisa" title="Sinibaldi: (In II Met., l. V)">(Tomás; ed. Leonina, p. 7)</span>', h)
        self.assertIn('</q> <span class="ref-precisa">(Anônimo, c. 1)</span>', h)   # Sinibaldi não deu referência
        h16 = self.client.get("/edicao/1916/v1.cap-1/").content.decode()
        self.assertIn("(In II Met., l. V)</cite>", h16)
        self.assertIn('title="Referência precisa: (Tomás; ed. Leonina, p. 7)"', h16)
        t = exportacao.texto_do_no(no_nova)
        self.assertIn("«Prius philosophus debet addiscere logicam quam alias scientias» (Tomás; ed. Leonina, p. 7).", t)
        self.assertIn("«algo é assim, segundo o autor», porém, «e assado»", t)
        x = exportacao.tei_do_no(no_nova)
        self.assertIn('<listBibl type="fontes"><bibl type="critica" xml:id="fonte-leon">', x)
        self.assertIn('<citedRange unit="page" type="fonte">7</citedRange>', x)
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "x.xml"
            arq.write_text(x, encoding="utf-8")
            script = Path(settings.RAIZ_REPO) / "tools" / "tei2latex.py"

            def latex(*op):
                return subprocess.run([sys.executable, str(script), str(arq), "--puro", *op],
                                      capture_output=True, text=True, check=True).stdout

            self.assertIn("«Prius philosophus debet addiscere logicam quam alias scientias» (In II Met., l. V)", latex())
            self.assertIn("scientias» (Tomás; ed. Leonina, p. 7)", latex("--citacoes", "precisa"))
            self.assertIn(r"scientias» \autocite[7]{leon}", latex("--citacoes", "biblatex"))
            self.assertIn("sem referência nenhuma» (Anônimo, c. 1)", latex("--citacoes", "precisa"))
