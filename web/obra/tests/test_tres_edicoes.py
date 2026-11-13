"""Três edições (rediagramação 1916, atualizada, nova) e a opção de esconder uma edição da parte pública."""
import json
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from obra import servicos, servicos_nova
from obra.models import Bloco, Edicao, No

from .test_nova import NovaBase


class AtualizadaBase(NovaBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("derivar_edicao_atualizada", stdout=StringIO())
        cls.atu = Edicao.objects.get(slug="atualizada")


class DerivarAtualizadaTest(AtualizadaBase):
    def test_copia_na_ordem_da_1916(self):
        self.assertEqual(self.atu.tipo, Edicao.ATUALIZADA)
        self.assertTrue(self.atu.derivada)
        self.assertFalse(self.atu.reorganiza)
        orig = list(Bloco.objects.filter(edicao=self.e1916).exclude(tipo=Bloco.CABECALHO).order_by("ordem"))
        copia = list(Bloco.objects.filter(edicao=self.atu).order_by("ordem"))
        self.assertEqual([b.origem_id for b in copia], [b.pk for b in orig])
        self.assertTrue(all(b.procedencia == Bloco.COPIA for b in copia))
        self.assertEqual(list(No.objects.filter(edicao=self.atu, nivel="parte").order_by("ordem_ini")
                              .values_list("xml_id", flat=True)),
                         list(No.objects.filter(edicao=self.e1916, nivel="parte").order_by("ordem_ini")
                              .values_list("xml_id", flat=True)))

    def test_sem_recriar_recusa(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("derivar_edicao_atualizada", stdout=StringIO())

    def test_ordenadas(self):
        self.assertEqual([e.slug for e in Edicao.ordenadas()], ["1916", "atualizada", "nova"])


class EditorAtualizadaTest(AtualizadaBase):
    def test_telas_abrem(self):
        self.assertEqual(self.client.get(reverse("obra:nova_estrutura", args=["atualizada"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("obra:nova_no", args=["atualizada", "v1.t1"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("obra:nova_pendencias", args=["atualizada"])).status_code, 200)

    def test_estrutura_sem_ordem_das_partes(self):
        r = self.client.get(reverse("obra:nova_estrutura", args=["atualizada"]))
        self.assertNotContains(r, "Aplicar ordem-alvo")
        self.assertNotContains(r, 'value="suprimir"')
        r = self.client.get(reverse("obra:nova_estrutura", args=["nova"]))
        self.assertContains(r, "Aplicar ordem-alvo")

    def test_operacoes_estruturais_404(self):
        self.assertEqual(self.client.post(reverse("obra:nova_aplicar_ordem", args=["atualizada"])).status_code, 404)
        self.assertEqual(self.client.post(reverse("obra:nova_no_acao", args=["atualizada", "v1.t1"]),
                                          {"acao": "suprimir"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("obra:nova_mover", args=["atualizada", "v1.t1"])).status_code, 404)
        with self.assertRaises(servicos.ErroOperacao):
            servicos_nova.definir_supressao(self.atu, 0, 10**12, True)

    def test_1916_nao_e_derivada(self):
        self.assertEqual(self.client.get(reverse("obra:nova_estrutura", args=["1916"])).status_code, 404)

    def test_gravar_marca_adaptado_e_sincroniza(self):
        b = Bloco.objects.filter(edicao=self.atu, tipo=Bloco.PARAGRAFO).order_by("ordem").first()
        novo = b.xml.replace("Frontispício", "Frontispicio atualizado")
        self.assertNotEqual(novo, b.xml)
        r = self.gravar([b], url=reverse("obra:nova_gravar", args=["atualizada"]), subst={b.pk: novo})
        self.assertEqual(r.status_code, 200, r.content)
        b.refresh_from_db()
        self.assertEqual(b.procedencia, Bloco.ADAPTADO)
        # um bloco da 1916 revisado depois vira cópia desatualizada na atualizada
        c = Bloco.objects.filter(edicao=self.atu, tipo=Bloco.PARAGRAFO, procedencia=Bloco.COPIA).order_by("ordem").first()
        o = c.origem
        servicos.salvar_blocos(self.e1916, [o.pk], [{"id": o.pk, "versao": o.versao, "xml": o.xml.replace("Texto", "Textos")}], None)
        self.assertIn(c.pk, set(servicos_nova.copias_desatualizadas(self.atu).values_list("pk", flat=True)))
        self.assertEqual(servicos_nova.atualizar_copias(self.atu), 1)

    def test_gravar_nao_toca_outra_edicao(self):
        b = Bloco.objects.filter(edicao=self.nova, tipo=Bloco.PARAGRAFO).order_by("ordem").first()
        r = self.gravar([b], url=reverse("obra:nova_gravar", args=["atualizada"]))
        self.assertNotEqual(r.status_code, 200)


class VisibilidadeTest(AtualizadaBase):
    def setUp(self):
        super().setUp()
        Edicao.objects.filter(slug="nova").update(publica=False)

    def test_anonimo_nao_ve_a_oculta(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("obra:edicao", args=["nova"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("obra:no", args=["nova", "v1.t1"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("obra:busca", args=["nova"]) + "?q=Texto").status_code, 404)
        self.assertEqual(self.client.get(reverse("obra:citar", args=["nova", "v1.t1"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("obra:sugerir", args=["nova", "v1.t1"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("obra:baixar", args=["nova", "v1.t1", "txt"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("obra:edicao", args=["atualizada"])).status_code, 200)
        r = self.client.get(reverse("obra:inicio"))
        self.assertEqual([e.slug for e in r.context["edicoes"]], ["1916", "atualizada"])
        self.assertNotContains(r, reverse("obra:edicao", args=["nova"]))

    def test_editor_ve_a_oculta_marcada(self):
        r = self.client.get(reverse("obra:edicao", args=["nova"]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "oculta")
        r = self.client.get(reverse("obra:inicio"))
        self.assertEqual([e.slug for e in r.context["edicoes"]], ["1916", "atualizada", "nova"])

    def test_componentes_da_atualizada_no_sumario(self):
        self.client.logout()
        r = self.client.get(reverse("obra:edicao", args=["atualizada"]))
        for c in Edicao.COMPONENTES_ATUALIZADA:
            self.assertContains(r, c)

    def test_alternar_exige_change_edicao(self):
        url = reverse("obra:visibilidade", args=["nova"])
        self.assertEqual(self.client.post(url, {"publica": "1"}).status_code, 403)
        admin = get_user_model().objects.create_superuser("adm", password="x")
        self.client.force_login(admin)
        r = self.client.get(reverse("obra:painel"))
        self.assertContains(r, url)
        self.assertRedirects(self.client.post(url, {"publica": "1"}), reverse("obra:painel"))
        self.assertTrue(Edicao.objects.get(slug="nova").publica)
        self.client.post(url, {"publica": "0"})
        self.assertFalse(Edicao.objects.get(slug="nova").publica)

    def test_painel_tem_cartao_das_duas_derivadas(self):
        r = self.client.get(reverse("obra:painel"))
        self.assertEqual([d["edicao"].slug for d in r.context["derivadas"]], ["atualizada", "nova"])
        self.assertContains(r, reverse("obra:nova_estrutura", args=["atualizada"]))


class MigracaoTest(NovaBase):
    def test_derivar_nova_cria_oculta(self):
        Edicao.objects.filter(slug="nova").delete()
        call_command("derivar_nova_edicao", stdout=StringIO())
        self.assertFalse(Edicao.objects.get(slug="nova").publica)
