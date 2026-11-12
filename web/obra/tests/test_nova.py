"""Telas e serviços da nova edição: estrutura, ordem das partes, suprimir, procedência, pendências."""
import json
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from lxml import etree

from obra import arvore, leitura, partes, servicos, servicos_nova, tei
from obra.models import PASSO_ORDEM, Bloco, Edicao, No, Pagina, Revisao, Volume

PARTES = [  # fora da ordem-alvo, como no original (+ "Direito natural" não identificada)
    ("Moral", "ETHICA"), ("Teodiceia", "THEODICEA"), ("Direito", "DIREITO NATURAL"),
    ("Ontologia", "ONTOLOGIA"), ("Antropologia", "ANTHROPOLOGIA"), ("Cosmologia", "COSMOLOGIA"),
    ("Logica", "LOGICA"),
]


def tei_partes(partes_=PARTES, extras=0):
    corpo = ['<pb n="1" facs="paginas/0001.png"/><p>Frontispício solto</p>']
    for i, (chave, titulo) in enumerate(partes_, 1):
        corpo.append(
            f'<div type="parte" xml:id="parte-{chave.lower()}"><head type="rotulo">PARTE {i}</head><head>{titulo}</head>'
            f'<pb n="{i + 1}" facs="paginas/{i + 1:04d}.png"/>'
            f'<div type="tese" n="{i}" xml:id="t{i}"><p xml:id="t{i}.p1"><label>{i}.</label> <hi rend="bold">Tese {chave}.</hi> — Texto de {chave}.</p>'
            + "".join(f"<p>Parágrafo extra {j} de {chave}.</p>" for j in range(extras)) +
            '</div></div>')
    return ('<?xml version="1.0" encoding="UTF-8"?><TEI xmlns="http://www.tei-c.org/ns/1.0" xml:lang="pt">'
            '<teiHeader><fileDesc><titleStmt><title>T</title></titleStmt></fileDesc></teiHeader>'
            '<text><body><div type="volume">' + "".join(corpo) + '</div></body></text></TEI>')


def permitir(usuario):
    usuario.user_permissions.add(Permission.objects.get(codename="change_bloco", content_type__app_label="obra"))
    return get_user_model().objects.get(pk=usuario.pk)


def conteudo_xml(blocos, substituir=None):
    substituir = substituir or {}
    """Texto da aba XML dos blocos; `substituir`: {pk: novo xml}."""
    return tei.blocos_para_texto_xml([
        {"id": b.pk, "versao": b.versao, "xml": substituir.get(b.pk, b.xml)} for b in blocos])


class NovaBase(TestCase):
    extras = 0
    partes_ = PARTES

    @classmethod
    def setUpTestData(cls):
        cls.ana = permitir(get_user_model().objects.create_user("ana", password="x"))
        cls.sem = get_user_model().objects.create_user("sem", password="x")
        cls.e1916 = Edicao.objects.create(slug="1916", titulo="Diplomática", tipo="diplomatica")
        cls.nova = Edicao.objects.create(slug="nova", titulo="Nova edição", tipo="nova")
        cls.vol = Volume.objects.create(numero=1, titulo="V1", ano=1917, diretorio="vol1")
        rel = tei.Relatorio()
        dados = tei.achatar(etree.fromstring(tei_partes(cls.partes_, cls.extras).encode()), numero=1, relatorio=rel)
        Bloco.objects.bulk_create([
            Bloco(edicao=cls.e1916, ordem=i * PASSO_ORDEM, tipo=d.tipo, xml=d.xml, volume=cls.vol, pagina=d.pagina)
            for i, d in enumerate(dados, 1)])
        Pagina.objects.bulk_create([Pagina(volume=cls.vol, seq=s, arquivo=a, impressa=str(s))
                                    for s, a in rel.paginas.items()])
        orig = list(Bloco.objects.filter(edicao=cls.e1916).order_by("ordem"))
        Bloco.objects.bulk_create([
            Bloco(edicao=cls.nova, ordem=b.ordem, tipo=b.tipo, xml=b.xml, volume=b.volume, pagina=b.pagina,
                  origem=b, procedencia=Bloco.COPIA) for b in orig])
        arvore.reconstruir(cls.e1916)
        arvore.reconstruir(cls.nova)

    def setUp(self):
        self.client.force_login(self.ana)

    def b1916(self):
        return list(Bloco.objects.filter(edicao=self.e1916).order_by("ordem"))

    def bnova(self):
        return list(Bloco.objects.filter(edicao=self.nova).order_by("ordem"))

    def foto_1916(self):
        return [(b.pk, b.ordem, b.xml, b.versao, b.procedencia) for b in self.b1916()]

    def ids_marcos(self, unit="parte"):
        out = []
        for b in self.bnova():
            if b.tipo == Bloco.MARCO:
                r = etree.fromstring(b.xml.encode())
                if r.get("unit") == unit:
                    out.append(r.get("{http://www.w3.org/XML/1998/namespace}id"))
        return out

    def gravar(self, blocos, comentario="", url=None, subst=None):
        corpo = {"formato": "xml", "conteudo": conteudo_xml(blocos, subst or {}), "ids": [b.pk for b in blocos],
                 "comentario": comentario}
        return self.client.post(url or reverse("obra:nova_gravar"), json.dumps(corpo), content_type="application/json")

    def primeiro_paragrafo(self, chave="cosmologia"):
        t = No.objects.get(edicao=self.nova, xml_id=f"v1.t{[p[0].lower() for p in self.partes_].index(chave) + 1}")
        return arvore.blocos_do_no(t).filter(tipo=Bloco.PARAGRAFO).first()


URLS_GET = [
    ("obra:nova_estrutura", []), ("obra:nova_no", ["v1.t1"]), ("obra:nova_mover", ["v1.t1"]),
    ("obra:nova_trecho", [PASSO_ORDEM]), ("obra:nova_pendencias", []),
]
URLS_POST = [
    ("obra:nova_aplicar_ordem", []), ("obra:nova_no_acao", ["v1.t1"]), ("obra:nova_gravar", []),
    ("obra:nova_bloco_acao", []), ("obra:nova_pendencias_acao", []),
]


class PermissoesTest(NovaBase):
    def test_anonimo_vai_para_login(self):
        self.client.logout()
        for nome, args in URLS_GET:
            r = self.client.get(reverse(nome, args=args))
            self.assertEqual(r.status_code, 302, nome)
            self.assertIn("/entrar", r["Location"])
        for nome, args in URLS_POST:
            r = self.client.post(reverse(nome, args=args), {})
            self.assertIn(r.status_code, (302, 401), nome)

    def test_sem_permissao_403(self):
        self.client.force_login(self.sem)
        for nome, args in URLS_GET:
            self.assertEqual(self.client.get(reverse(nome, args=args)).status_code, 403, nome)
        for nome, args in URLS_POST:
            self.assertEqual(self.client.post(reverse(nome, args=args), {}).status_code, 403, nome)

    def test_com_permissao_200(self):
        for nome, args in URLS_GET:
            if nome == "obra:nova_trecho":
                continue  # o primeiro bloco pertence a um trecho solto: ver TelasTest
            self.assertEqual(self.client.get(reverse(nome, args=args)).status_code, 200, nome)

    def test_get_nao_executa_acoes(self):
        self.assertEqual(self.client.get(reverse("obra:nova_aplicar_ordem")).status_code, 405)
        self.assertEqual(self.client.get(reverse("obra:nova_no_acao", args=["v1.t1"])).status_code, 405)

    def test_post_sem_csrf_recusado(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.ana)
        self.assertEqual(c.post(reverse("obra:nova_no_acao", args=["v1.t1"]), {"acao": "suprimir"}).status_code, 403)
        self.assertFalse(Bloco.objects.filter(edicao=self.nova, procedencia=Bloco.SUPRIMIDO).exists())


class PartesTest(NovaBase):
    def test_plano(self):
        plano = partes.plano_partes(self.nova)
        self.assertEqual(plano["faltam"], [])
        self.assertFalse(plano["na_ordem"])
        titulos = [p.titulo for p in plano["alvo"]]
        # "Direito natural" (não identificada) segue a Teodiceia, que a antecede no original
        self.assertEqual(titulos, ["LOGICA", "COSMOLOGIA", "ANTHROPOLOGIA", "ONTOLOGIA", "THEODICEA",
                                   "DIREITO NATURAL", "ETHICA"])

    def test_classificacao_sem_acento_e_caixa(self):
        class N:
            def __init__(self, t, r=""):
                self.titulo, self.rotulo = t, r
        casos = {"LÓGICA": 0, "Cosmologia": 1, "ANTHROPOLOGIA": 2, "Antropologia": 2, "ONTOLOGIA": 3,
                 "THEODICEA": 4, "Teodiceia": 4, "MORAL": 5, "ETHICA": 5, "DIREITO NATURAL": None}
        for t, r in casos.items():
            self.assertEqual(partes.classificar_parte(N(t)), r, t)

    def test_aplicar_ordem_reordena_blocos(self):
        antes = self.foto_1916()
        n_blocos = len(self.bnova())
        # no original o "Direito" vem logo depois de Teodiceia; Moral é a primeira
        self.assertEqual(self.ids_marcos(), ["v1.parte-moral", "v1.parte-teodiceia", "v1.parte-direito",
                                             "v1.parte-ontologia", "v1.parte-antropologia", "v1.parte-cosmologia",
                                             "v1.parte-logica"])
        r = self.client.post(reverse("obra:nova_aplicar_ordem"), follow=True)
        self.assertEqual(r.status_code, 200)
        esperado = ["v1.parte-logica", "v1.parte-cosmologia", "v1.parte-antropologia", "v1.parte-ontologia",
                    "v1.parte-teodiceia", "v1.parte-direito", "v1.parte-moral"]
        self.assertEqual(self.ids_marcos(), esperado)
        self.assertEqual(len(self.bnova()), n_blocos)
        # o trecho solto continua no início; cada parte leva o seu conteúdo
        blocos = self.bnova()
        self.assertEqual(blocos[0].tipo, Bloco.PARAGRAFO)
        self.assertIn("Frontispício", blocos[0].xml)
        nos = list(No.objects.filter(edicao=self.nova, nivel="parte").order_by("ordem_ini"))
        self.assertEqual([n.xml_id for n in nos], esperado)
        for n in nos:
            tese = No.objects.get(edicao=self.nova, pai=n, nivel="tese")
            self.assertIn("Texto de " + n.xml_id.split("-")[1].capitalize(),
                          "".join(b.xml for b in arvore.blocos_do_no(tese)))
        self.assertEqual([x.ordem for x in blocos], sorted(x.ordem for x in blocos))
        self.assertEqual(len({x.ordem for x in blocos}), len(blocos))
        self.assertTrue(Revisao.objects.filter(edicao=self.nova, acao=Revisao.MOVER, autor=self.ana).exists())
        # idempotente e a 1916 não mudou
        self.assertTrue(partes.plano_partes(self.nova)["na_ordem"])
        self.assertEqual(self.foto_1916(), antes)

    def test_aplicar_exige_as_seis_partes(self):
        # tira "Moral" da nova edição (marcando o marco como outra coisa não é preciso: basta remover as partes)
        faltando = [p for p in PARTES if p[0] != "Moral"]
        Bloco.objects.filter(edicao=self.nova).delete()
        rel = tei.Relatorio()
        dados = tei.achatar(etree.fromstring(tei_partes(faltando).encode()), numero=1, relatorio=rel)
        for i, d in enumerate(dados, 1):
            Bloco.objects.create(edicao=self.nova, ordem=i * PASSO_ORDEM, tipo=d.tipo, xml=d.xml, volume=self.vol)
        arvore.reconstruir(self.nova)
        self.assertEqual(partes.plano_partes(self.nova)["faltam"], [5])
        with self.assertRaises(servicos.ErroOperacao):
            servicos_nova.aplicar_ordem_partes(self.nova, autor=self.ana)
        r = self.client.post(reverse("obra:nova_aplicar_ordem"), follow=True)
        self.assertContains(r, "Faltam partes: Moral")
        self.assertEqual(self.ids_marcos()[0], "v1.parte-teodiceia")

    def test_so_nova(self):
        with self.assertRaises(servicos.ErroOperacao):
            servicos_nova.aplicar_ordem_partes(self.e1916, autor=self.ana)

    def test_painel_na_estrutura(self):
        r = self.client.get(reverse("obra:nova_estrutura"))
        self.assertContains(r, "Ordem das partes")
        self.assertContains(r, "Aplicar ordem-alvo")
        self.assertNotContains(r, "Habilitado quando as seis")


class MoverTest(NovaBase):
    def test_subir_e_descer_entre_irmaos(self):
        # reordenar para ter as teses sob suas partes; sobe a Cosmologia (5ª) acima da Antropologia
        def ordem():
            return [n.xml_id for n in No.objects.filter(edicao=self.nova, nivel="parte").order_by("ordem_ini")]
        antes = ordem()
        r = self.client.post(reverse("obra:nova_no_acao", args=["v1.parte-cosmologia"]), {"acao": "subir"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("foco=v1.parte-cosmologia#no-v1.parte-cosmologia", r["Location"])
        depois = ordem()
        i = antes.index("v1.parte-cosmologia")
        self.assertEqual(depois[i - 1], "v1.parte-cosmologia")
        self.client.post(reverse("obra:nova_no_acao", args=["v1.parte-cosmologia"]), {"acao": "descer"})
        self.assertEqual(ordem(), antes)
        rev = Revisao.objects.filter(edicao=self.nova, acao=Revisao.MOVER, autor=self.ana)
        self.assertEqual(rev.count(), 2)

    def test_limite_nao_move(self):
        r = self.client.post(reverse("obra:nova_no_acao", args=["v1.parte-moral"]), {"acao": "subir"}, follow=True)
        self.assertContains(r, "já está no limite")

    def test_mover_para_outro_pai(self):
        # a tese 1 (da Moral) vai para dentro da parte Logica
        alvo = No.objects.get(edicao=self.nova, xml_id="v1.parte-logica")
        r = self.client.post(reverse("obra:nova_mover", args=["v1.t1"]), {"alvo": alvo.pk, "modo": "dentro"})
        self.assertEqual(r.status_code, 302)
        t1 = No.objects.get(edicao=self.nova, xml_id="v1.t1")
        self.assertEqual(No.objects.get(pk=t1.pai_id).xml_id, "v1.parte-logica")

    def test_mover_antes_de_outro_irmao(self):
        alvo = No.objects.get(edicao=self.nova, xml_id="v1.parte-logica")
        self.client.post(reverse("obra:nova_mover", args=["v1.parte-moral"]), {"alvo": alvo.pk, "modo": "antes"})
        self.assertEqual(self.ids_marcos()[-2:], ["v1.parte-moral", "v1.parte-logica"])

    def test_destino_invalido(self):
        alvo = No.objects.get(edicao=self.nova, xml_id="v1.parte-logica")
        r = self.client.post(reverse("obra:nova_mover", args=["v1.t1"]), {"alvo": alvo.pk, "modo": "antes"})
        self.assertEqual(r.status_code, 200)  # tese vs parte: nível diferente -> volta ao formulário com erro
        self.assertContains(r, "mesmo nível")

    def test_nao_toca_1916(self):
        antes = self.foto_1916()
        self.client.post(reverse("obra:nova_no_acao", args=["v1.parte-cosmologia"]), {"acao": "subir"})
        self.client.post(reverse("obra:nova_aplicar_ordem"))
        self.assertEqual(self.foto_1916(), antes)

    def test_so_nova_no_servico(self):
        no = No.objects.get(edicao=self.e1916, xml_id="v1.parte-moral")
        outro = No.objects.get(edicao=self.e1916, xml_id="v1.parte-logica")
        with self.assertRaises(servicos.ErroOperacao):
            servicos.mover_no(no, antes_de=outro, autor=self.ana)

    def test_rotas_nao_enxergam_nos_da_1916(self):
        # o xml_id existe nas duas edições; a ação vale só para a nova
        self.client.post(reverse("obra:nova_no_acao", args=["v1.t3"]), {"acao": "suprimir"})
        self.assertFalse(Bloco.objects.filter(edicao=self.e1916, procedencia=Bloco.SUPRIMIDO).exists())
        self.assertTrue(Bloco.objects.filter(edicao=self.nova, procedencia=Bloco.SUPRIMIDO).exists())


class SuprimirTest(NovaBase):
    def test_suprimir_e_restaurar_no(self):
        no = No.objects.get(edicao=self.nova, xml_id="v1.parte-logica")
        n_no = arvore.blocos_do_no(no).count()
        r = self.client.post(reverse("obra:nova_no_acao", args=["v1.parte-logica"]), {"acao": "suprimir"}, follow=True)
        self.assertContains(r, f"({n_no} blocos)")
        sup = Bloco.objects.filter(edicao=self.nova, procedencia=Bloco.SUPRIMIDO)
        self.assertEqual(sup.count(), n_no)
        self.assertEqual(Bloco.objects.filter(edicao=self.nova).count(), len(self.bnova()))  # nada apagado
        # aparece riscado na árvore
        self.assertContains(self.client.get(reverse("obra:nova_estrutura")), "nova-suprimido")
        # a parte pública oculta
        html, _ = leitura.renderizar(list(arvore.blocos_do_no(no)), impressas_={})
        self.assertEqual(html.strip(), "")
        self.assertEqual(Revisao.objects.filter(edicao=self.nova, comentario="Suprimido.", autor=self.ana).count(), n_no)
        self.client.post(reverse("obra:nova_no_acao", args=["v1.parte-logica"]), {"acao": "restaurar"})
        self.assertFalse(Bloco.objects.filter(edicao=self.nova, procedencia=Bloco.SUPRIMIDO).exists())
        self.assertTrue(all(b.procedencia == Bloco.COPIA for b in arvore.blocos_do_no(no)))

    def test_restaurar_volta_a_procedencia_natural(self):
        p = self.primeiro_paragrafo("logica")
        self.assertEqual(self.gravar([p], subst={p.pk: p.xml.replace("Texto", "Contexto")}).status_code, 200)
        no = No.objects.get(edicao=self.nova, xml_id="v1.parte-logica")
        servicos_nova.definir_supressao(self.nova, no.ordem_ini, no.ordem_fim, True, autor=self.ana)
        servicos_nova.definir_supressao(self.nova, no.ordem_ini, no.ordem_fim, False, autor=self.ana)
        p.refresh_from_db()
        self.assertEqual(p.procedencia, Bloco.ADAPTADO)
        outro = arvore.blocos_do_no(no).exclude(pk=p.pk).first()
        self.assertEqual(outro.procedencia, Bloco.COPIA)

    def test_servico_so_nova(self):
        with self.assertRaises(servicos.ErroOperacao):
            servicos_nova.definir_supressao(self.e1916, 0, 10 ** 9, True)


class ProcedenciaTest(NovaBase):
    def test_copia_alterada_vira_adaptado(self):
        p = self.primeiro_paragrafo()
        r = self.gravar([p], comentario="ajuste", subst={p.pk: p.xml.replace("Texto", "Contexto")})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(d["info"][str(p.pk)]["procedencia"], "adaptado")
        p.refresh_from_db()
        self.assertEqual((p.procedencia, p.versao, p.atualizado_por), (Bloco.ADAPTADO, 2, self.ana))
        self.assertEqual(p.origem_versao_vista, p.origem.versao)
        self.assertEqual(Revisao.objects.filter(bloco=p, autor=self.ana, comentario="ajuste").count(), 1)
        # gravar de novo sem mudar não altera nada
        self.assertFalse(self.gravar([p]).json()["alterou"])

    def test_bloco_criado_nasce_novo_e_herda_do_anterior(self):
        p = self.primeiro_paragrafo()
        anterior = Bloco.objects.filter(edicao=self.nova, ordem__lt=p.ordem).order_by("-ordem").first()
        texto = conteudo_xml([p]) + "\n\n<p>Parágrafo criado aqui.</p>"
        corpo = {"formato": "xml", "conteudo": texto, "ids": [p.pk]}
        r = self.client.post(reverse("obra:nova_gravar"), json.dumps(corpo), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        novo = Bloco.objects.get(edicao=self.nova, xml__contains="Parágrafo criado aqui")
        self.assertEqual(novo.procedencia, Bloco.NOVO)
        self.assertIsNone(novo.origem)
        self.assertEqual((novo.volume_id, novo.pagina), (p.volume_id, p.pagina))  # herda do bloco imediatamente anterior
        self.assertEqual(novo.criado_por, self.ana)
        self.assertGreater(novo.ordem, p.ordem)
        self.assertIsNotNone(anterior)

    def test_servico_na_1916_cria_copia(self):
        b = self.b1916()[0]
        res = servicos.salvar_blocos(self.e1916, [b.pk], [{"id": b.pk, "versao": b.versao, "xml": b.xml},
                                                         {"id": None, "versao": None, "xml": "<p>Novo</p>"}],
                                     autor=self.ana)
        self.assertEqual(res.criados, 1)
        self.assertEqual(Bloco.objects.get(edicao=self.e1916, xml="<p>Novo</p>").procedencia, Bloco.COPIA)

    def test_conflito_409(self):
        p = self.primeiro_paragrafo()
        servicos.salvar_blocos(self.nova, [p.pk], [{"id": p.pk, "versao": p.versao, "xml": p.xml.replace("Texto", "Outro")}],
                               autor=self.ana)
        r = self.gravar([p], subst={p.pk: p.xml.replace("Texto", "Meu")})  # `p` ainda na versão antiga
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()["conflito"])

    def test_xml_id_repetido_recusado_com_erro_claro(self):
        p = self.primeiro_paragrafo()
        marco = '<milestone unit="parte" n="1" xml:id="v1.parte-moral"/>'
        corpo = {"formato": "xml", "conteudo": marco + "\n\n" + conteudo_xml([p]), "ids": [p.pk]}
        r = self.client.post(reverse("obra:nova_gravar"), json.dumps(corpo), content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("já é usado em outro bloco", r.json()["erros"][0])

    def test_criar_marco_de_parte_aparece_na_arvore(self):
        p = self.primeiro_paragrafo()
        marco = '<milestone unit="parte" n="9" xml:id="n.parte-ontologia-2"/>'
        titulo = '<head>ONTOLOGIA NOVA</head>'
        corpo = {"formato": "xml", "conteudo": marco + "\n\n" + titulo + "\n\n" + conteudo_xml([p]), "ids": [p.pk]}
        r = self.client.post(reverse("obra:nova_gravar"), json.dumps(corpo), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["estrutura_mudou"])
        no = No.objects.get(edicao=self.nova, xml_id="n.parte-ontologia-2")
        self.assertEqual(no.titulo, "ONTOLOGIA NOVA")
        self.assertEqual(no.volume_id, self.vol.pk)
        # a classificação encontra a parte pelo título
        self.assertIn(3, partes.plano_partes(self.nova)["identificadas"])

    def test_1916_nao_grava_blocos_da_nova(self):
        p = self.primeiro_paragrafo()
        antes_nova = [(b.pk, b.xml, b.versao) for b in self.bnova()]
        corpo = {"formato": "xml", "ids": [p.pk],
                 "conteudo": conteudo_xml([p], {p.pk: p.xml.replace("Texto", "Invasão")})}
        pg = Pagina.objects.filter(volume=self.vol).first()
        r = self.client.post(reverse("obra:gravar", args=[1, pg.seq]), json.dumps(corpo), content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual([(b.pk, b.xml, b.versao) for b in self.bnova()], antes_nova)

    def test_nova_nao_grava_blocos_da_1916(self):
        b = self.b1916()[0]
        antes = self.foto_1916()
        r = self.gravar([b], subst={b.pk: "<p>Invasão</p>"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.foto_1916(), antes)
        # nem as ações por bloco
        r = self.client.post(reverse("obra:nova_bloco_acao"), json.dumps({"acao": "suprimir", "bloco": b.pk, "ids": [b.pk]}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.foto_1916(), antes)


class RestaurarTest(NovaBase):
    def acao(self, acao, p, ids=None):
        return self.client.post(reverse("obra:nova_bloco_acao"),
                                json.dumps({"acao": acao, "bloco": p.pk, "ids": ids or [p.pk]}),
                                content_type="application/json")

    def test_restaurar_texto_de_1916(self):
        p = self.primeiro_paragrafo()
        original = p.xml
        self.gravar([p], subst={p.pk: p.xml.replace("Texto", "Outro texto")})
        p.refresh_from_db()
        self.assertEqual(p.procedencia, Bloco.ADAPTADO)
        r = self.acao("restaurar_1916", p)
        self.assertEqual(r.status_code, 200, r.content)
        p.refresh_from_db()
        self.assertEqual((p.xml, p.procedencia, p.versao), (original, Bloco.COPIA, 3))
        self.assertEqual(r.json()["info"][str(p.pk)]["procedencia"], "copia")
        revs = list(Revisao.objects.filter(bloco=p).order_by("pk"))
        self.assertEqual(revs[-1].xml_depois, original)
        self.assertEqual(revs[-1].autor, self.ana)

    def test_restaurar_sem_origem_recusado(self):
        novo = Bloco.objects.create(edicao=self.nova, ordem=1, tipo="paragrafo", xml="<p>x</p>", volume=self.vol,
                                    procedencia=Bloco.NOVO)
        self.assertEqual(self.acao("restaurar_1916", novo).status_code, 400)

    def test_suprimir_bloco_e_restaurar(self):
        p = self.primeiro_paragrafo()
        self.assertEqual(self.acao("suprimir", p).json()["info"][str(p.pk)]["procedencia"], "suprimido")
        self.assertEqual(self.acao("restaurar_supressao", p).json()["info"][str(p.pk)]["procedencia"], "copia")

    def test_restaurar_estrutural_reconstroi_arvore(self):
        marco = Bloco.objects.get(edicao=self.nova, xml__contains='xml:id="v1.parte-logica"')
        servicos.salvar_blocos(self.nova, [marco.pk], [{"id": marco.pk, "versao": marco.versao,
                                                        "xml": marco.xml.replace("v1.parte-logica", "n.logica")}], autor=self.ana)
        self.assertTrue(No.objects.filter(edicao=self.nova, xml_id="n.logica").exists())
        marco.refresh_from_db()
        servicos_nova.restaurar_texto_1916(self.nova, [marco.pk], autor=self.ana)
        self.assertTrue(No.objects.filter(edicao=self.nova, xml_id="v1.parte-logica").exists())
        self.assertFalse(No.objects.filter(edicao=self.nova, xml_id="n.logica").exists())


class PendenciasTest(NovaBase):
    def mudar_1916(self, bloco, de="Texto", para="Texto revisto"):
        """Simula uma revisão da 1916 (via serviço, como a tela de revisão)."""
        b = Bloco.objects.get(pk=bloco.origem_id)
        servicos.salvar_blocos(self.e1916, [b.pk], [{"id": b.pk, "versao": b.versao, "xml": b.xml.replace(de, para)}],
                               autor=self.ana, comentario="revisão na 1916")
        return Bloco.objects.get(pk=b.pk)

    def test_copias_desatualizadas_e_atualizar(self):
        p = self.primeiro_paragrafo()
        self.assertEqual(servicos_nova.copias_desatualizadas(self.nova).count(), 0)
        o = self.mudar_1916(p)
        self.assertEqual(list(servicos_nova.copias_desatualizadas(self.nova)), [p])
        r = self.client.get(reverse("obra:nova_pendencias") + "?aba=copias")
        self.assertContains(r, "Atualizar todas as cópias (1)")
        self.assertContains(r, "dif-ins")
        r = self.client.post(reverse("obra:nova_pendencias_acao"), {"acao": "atualizar", "ids": [p.pk], "aba": "copias"},
                             follow=True)
        self.assertContains(r, "1 cópia atualizada")
        p.refresh_from_db()
        self.assertEqual((p.xml, p.versao, p.procedencia), (o.xml, 2, Bloco.COPIA))
        self.assertEqual(servicos_nova.copias_desatualizadas(self.nova).count(), 0)
        self.assertTrue(Revisao.objects.filter(bloco=p, autor=self.ana, comentario__contains="atualizada").exists())

    def test_atualizar_todas(self):
        ps = [self.primeiro_paragrafo("logica"), self.primeiro_paragrafo("moral")]
        for p in ps:
            self.mudar_1916(p)
        self.assertEqual(servicos_nova.copias_desatualizadas(self.nova).count(), 2)
        self.client.post(reverse("obra:nova_pendencias_acao"), {"acao": "atualizar_todas", "aba": "copias"})
        self.assertEqual(servicos_nova.copias_desatualizadas(self.nova).count(), 0)

    def test_nao_atualiza_adaptados(self):
        p = self.primeiro_paragrafo()
        self.gravar([p], subst={p.pk: p.xml.replace("Texto", "Meu texto")})
        self.mudar_1916(p, de="Texto", para="Texto novo")
        self.assertEqual(servicos_nova.copias_desatualizadas(self.nova).count(), 0)
        self.assertEqual(servicos_nova.atualizar_copias(self.nova, autor=self.ana), 0)
        p.refresh_from_db()
        self.assertIn("Meu texto", p.xml)

    def test_adaptados_com_origem_alterada(self):
        p = self.primeiro_paragrafo()
        self.gravar([p], subst={p.pk: p.xml.replace("Texto", "Meu texto")})
        self.assertEqual(servicos_nova.adaptados_pendentes(self.nova).count(), 0)
        self.mudar_1916(p, de="Texto", para="Texto da 1916")
        self.assertEqual(list(servicos_nova.adaptados_pendentes(self.nova)), [p])
        r = self.client.get(reverse("obra:nova_pendencias") + "?aba=adaptados")
        self.assertContains(r, "Marcar como visto")
        self.assertContains(r, "revisão na 1916")
        r = self.client.post(reverse("obra:nova_pendencias_acao"), {"acao": "visto", "ids": [p.pk], "aba": "adaptados"},
                             follow=True)
        self.assertContains(r, "marcado como visto")
        self.assertEqual(servicos_nova.adaptados_pendentes(self.nova).count(), 0)
        # nova alteração na origem volta a aparecer
        self.mudar_1916(p, de="da 1916", para="de novo")
        self.assertEqual(servicos_nova.adaptados_pendentes(self.nova).count(), 1)

    def test_adaptado_legado_sem_versao_vista_usa_data(self):
        p = self.primeiro_paragrafo()
        Bloco.objects.filter(pk=p.pk).update(procedencia=Bloco.ADAPTADO, xml=p.xml.replace("Texto", "X"))
        self.assertEqual(servicos_nova.adaptados_pendentes(self.nova).count(), 0)
        self.mudar_1916(p)
        self.assertEqual(servicos_nova.adaptados_pendentes(self.nova).count(), 1)

    def test_cobertura(self):
        self.assertEqual(servicos_nova.sem_correspondente(self.nova).count(), 0)
        p = self.primeiro_paragrafo()
        o = p.origem
        # um cabeçalho corrente na 1916 não conta; um parágrafo sem correspondente conta
        Bloco.objects.create(edicao=self.e1916, ordem=o.ordem + 1, tipo="cabecalho", xml='<fw type="header">x</fw>', volume=self.vol)
        self.assertEqual(servicos_nova.sem_correspondente(self.nova).count(), 0)
        extra = Bloco.objects.create(edicao=self.e1916, ordem=o.ordem + 2, tipo="paragrafo", xml="<p>Esquecido</p>",
                                     volume=self.vol, pagina=3)
        self.assertEqual(list(servicos_nova.sem_correspondente(self.nova)), [extra])
        r = self.client.get(reverse("obra:nova_pendencias") + "?aba=cobertura")
        self.assertContains(r, "Esquecido")
        self.assertContains(r, "ver na 1916")
        # suprimido conta como correspondente
        p.procedencia = Bloco.SUPRIMIDO
        p.save()
        self.assertEqual(servicos_nova.sem_correspondente(self.nova).count(), 1)
        Bloco.objects.filter(pk=p.pk).delete()
        self.assertEqual(servicos_nova.sem_correspondente(self.nova).count(), 2)

    def test_comando(self):
        p = self.primeiro_paragrafo()
        self.mudar_1916(p)
        out = StringIO()
        call_command("sincronizar_nova_edicao", stdout=out)
        self.assertIn("Cópias desatualizadas: 1", out.getvalue())
        self.assertEqual(servicos_nova.copias_desatualizadas(self.nova).count(), 1)  # sem --aplicar, nada muda
        out = StringIO()
        call_command("sincronizar_nova_edicao", "--aplicar", stdout=out)
        self.assertIn("1 cópia(s) atualizada(s)", out.getvalue())
        self.assertEqual(servicos_nova.copias_desatualizadas(self.nova).count(), 0)

    def test_painel_mostra_cartao_da_nova(self):
        r = self.client.get(reverse("obra:painel"))
        self.assertContains(r, "Nova edição")
        self.assertContains(r, reverse("obra:nova_pendencias"))
        self.assertContains(r, reverse("obra:nova_estrutura"))


class TelasTest(NovaBase):
    extras = 100

    def test_trecho_solto_e_arvore(self):
        r = self.client.get(reverse("obra:nova_estrutura"))
        self.assertContains(r, "trecho sem parte")
        primeiro = Bloco.objects.filter(edicao=self.nova).order_by("ordem").first()
        url = reverse("obra:nova_trecho", args=[primeiro.ordem])
        self.assertContains(r, url)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Frontispício")
        self.assertEqual(self.client.get(reverse("obra:nova_trecho", args=[No.objects.first().ordem_ini])).status_code, 404)

    def test_paginacao_por_blocos(self):
        no = No.objects.get(edicao=self.nova, xml_id="v1.parte-logica")
        total = arvore.blocos_do_no(no).count()
        self.assertGreater(total, 100)
        url = reverse("obra:nova_no", args=["v1.parte-logica"])
        r = self.client.get(url)
        self.assertEqual(r.context["telas"], -(-total // 40))
        d = r.context["dados"]
        self.assertEqual(len(d["ids"]), 40)
        r3 = self.client.get(url + "?p=3")
        ids3 = r3.context["dados"]["ids"]
        esperado = [b.pk for b in arvore.blocos_do_no(no)[80:120]]
        self.assertEqual(ids3, esperado)
        self.assertContains(r3, "tela 3 de")
        # tela fora do intervalo -> última
        ult = self.client.get(url + "?p=999")
        self.assertEqual(ult.context["tela"], ult.context["telas"])
        # sub-nó: a tese começa na tela 1
        self.assertEqual(d["subnos"][0]["xml_id"], "v1.t7")
        self.assertEqual(d["subnos"][0]["tela"], 1)

    def test_texto_de_1916_na_esquerda_e_gravar_na_tela(self):
        r = self.client.get(reverse("obra:nova_no", args=["v1.t7"]))
        self.assertContains(r, 'class="obra nova-1916"')
        self.assertContains(r, "Texto de Logica")
        d = r.context["dados"]
        pk = next(int(k) for k, v in d["info"].items() if v["origem"] and "Texto de Logica" in tei.fragmento_para_html(Bloco.objects.get(pk=int(k)).xml))
        self.assertEqual(d["info"][str(pk)]["procedencia"], "copia")
        self.assertContains(r, f'id="b{Bloco.objects.get(pk=pk).origem_id}"')
        self.assertEqual(d["prefixoId"], "n.")
