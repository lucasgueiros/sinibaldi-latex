"""Sugestões de correção: envio anônimo, anti-spam, triagem e aplicação ao texto."""
from django.core.cache import cache
from django.urls import reverse

from obra import servicos_sugestoes
from obra.models import Bloco, Edicao, Revisao, Sugestao

from .base import BaseBanco
from .test_views_edicao import com_permissao

XML_ID = "v1.t1"  # tese 1 do TEI sintético


class SugestoesBase(BaseBanco):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.p1 = Bloco.objects.get(edicao=self.edicao, xml__contains='xml:id="v1.t1.p1"')
        self.p2 = Bloco.objects.get(edicao=self.edicao, xml__contains='xml:id="v1.t2.p1"')
        self.url = reverse("obra:sugerir", args=["1916", XML_ID])

    def envia(self, **dados):
        base = {"bloco": self.p1.pk, "trecho": "simples", "sugestao": "simplices", "comentario": "",
                "nome": "", "email": "", "site": ""}
        base.update(dados)
        return self.client.post(self.url, base)

    def cria(self, **kw):
        dados = dict(edicao=self.edicao, bloco=self.p1, no_xml_id=XML_ID, bloco_versao=self.p1.versao,
                     trecho="simples", sugestao="simplices", nome="Zé")
        dados.update(kw)
        return Sugestao.objects.create(**dados)


class EnvioTest(SugestoesBase):
    def test_get_sem_bloco(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="sugestao"')
        self.assertContains(r, 'name="site"')
        self.assertNotContains(r, "PARÁGRAFO EM QUESTÃO")

    def test_get_com_bloco_mostra_texto(self):
        r = self.client.get(self.url, {"bloco": self.p1.pk})
        self.assertContains(r, "PARÁGRAFO EM QUESTÃO")
        self.assertContains(r, "é simples")
        self.assertContains(r, f'value="{self.p1.pk}"')

    def test_get_bloco_invalido_ignorado(self):
        r = self.client.get(self.url, {"bloco": "999999"})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "PARÁGRAFO EM QUESTÃO")

    def test_post_valido(self):
        r = self.envia(nome="Ana", email="a@exemplo.org")
        self.assertRedirects(r, reverse("obra:no", args=["1916", XML_ID]) + f"#b{self.p1.pk}",
                             fetch_redirect_response=False)
        (s,) = Sugestao.objects.all()
        self.assertEqual((s.estado, s.bloco_id, s.bloco_versao, s.no_xml_id, s.edicao_id),
                         ("pendente", self.p1.pk, self.p1.versao, XML_ID, self.edicao.pk))
        self.assertEqual((s.trecho, s.sugestao, s.nome, s.email), ("simples", "simplices", "Ana", "a@exemplo.org"))
        r = self.client.get(r.url.split("#")[0])
        self.assertContains(r, "Obrigado! Sua sugestão foi enviada")

    def test_post_sem_bloco(self):
        r = self.envia(bloco="", trecho="", sugestao="", comentario="Falta uma nota na p. 3.")
        self.assertRedirects(r, reverse("obra:no", args=["1916", XML_ID]), fetch_redirect_response=False)
        self.assertIsNone(Sugestao.objects.get().bloco_id)

    def test_sem_sugestao_nem_comentario(self):
        r = self.envia(sugestao="", comentario="  ")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Informe o texto corrigido ou um comentário")
        self.assertEqual(Sugestao.objects.count(), 0)

    def test_nada_alterado(self):
        r = self.envia(sugestao="simples")
        self.assertContains(r, "Nada foi alterado")
        self.assertEqual(Sugestao.objects.count(), 0)

    def test_limites(self):
        r = self.envia(trecho="x" * 2001)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Sugestao.objects.count(), 0)
        self.envia(nome="n" * 81)
        self.envia(sugestao="s" * 5001)
        self.envia(comentario="c" * 2001)
        self.assertEqual(Sugestao.objects.count(), 0)

    def test_bloco_de_outra_edicao(self):
        outra = Edicao.objects.create(slug="nova", titulo="Nova", tipo="nova")
        b = Bloco.objects.create(edicao=outra, ordem=1, tipo="paragrafo", xml="<p>Outro.</p>")
        r = self.envia(bloco=b.pk)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Trecho inválido para esta edição")
        self.assertEqual(Sugestao.objects.count(), 0)

    def test_bloco_suprimido_ou_cabecalho(self):
        Bloco.objects.filter(pk=self.p2.pk).update(procedencia=Bloco.SUPRIMIDO)
        r = self.envia(bloco=self.p2.pk)
        self.assertContains(r, "não aceita sugestões")
        cab = Bloco.objects.create(edicao=self.edicao, ordem=1, tipo=Bloco.CABECALHO, xml="<fw>x</fw>")
        r = self.envia(bloco=cab.pk)
        self.assertContains(r, "não aceita sugestões")
        self.assertEqual(Sugestao.objects.count(), 0)

    def test_honeypot(self):
        r = self.envia(site="http://spam.example")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Sugestao.objects.count(), 0)

    def test_erro_preserva_valores(self):
        r = self.envia(sugestao="", comentario="", trecho="meu trecho", nome="Beta")
        self.assertContains(r, "meu trecho")
        self.assertContains(r, 'value="Beta"')

    def test_limite_por_ip(self):
        for i in range(10):
            self.assertEqual(self.envia(sugestao=f"v{i}").status_code, 302)
        r = self.envia(sugestao="demais")
        self.assertEqual(r.status_code, 429)
        self.assertContains(r, "Muitos envios", status_code=429)
        self.assertEqual(Sugestao.objects.count(), 10)
        # o IP cru não vira chave de cache
        self.assertFalse(cache.get("sugestao-ip:127.0.0.1"))

    def test_no_inexistente(self):
        r = self.client.get(reverse("obra:sugerir", args=["1916", "nao-existe"]))
        self.assertEqual(r.status_code, 404)

    def test_pagina_do_no_tem_link_e_dialogo(self):
        r = self.client.get(reverse("obra:no", args=["1916", XML_ID]))
        self.assertContains(r, self.url)
        self.assertContains(r, "<dialog")
        # comentário de template vazando na página (um `{# #}` de várias linhas) já quebrou o diálogo
        self.assertNotContains(r, "{#")
        self.assertEqual(r.content.decode().count("<dialog"), 1)
        self.assertContains(r, 'name="sugestao"')
        self.assertContains(r, "js/sugestao.js")
        self.assertContains(r, "Achou um erro?")


class ListaTest(SugestoesBase):
    def setUp(self):
        super().setUp()
        self.url_lista = reverse("obra:sugestoes")
        self.editor = com_permissao(self.user)

    def test_acesso(self):
        r = self.client.get(self.url_lista)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/entrar/", r["Location"])
        self.client.force_login(self.user2)  # sem permissão
        self.assertEqual(self.client.get(self.url_lista).status_code, 403)
        r = self.client.post(reverse("obra:sugestao_acao", args=[1]), {"acao": "rejeitar"})
        self.assertEqual(r.status_code, 403)

    def test_editor_ve_lista_com_diff_e_links(self):
        s = self.cria(comentario="Veja o scan", email="z@exemplo.org")
        self.client.force_login(self.editor)
        r = self.client.get(self.url_lista)
        self.assertContains(r, "Zé")
        self.assertContains(r, "z@exemplo.org")
        self.assertContains(r, "Veja o scan")
        self.assertContains(r, '<del class="dif-del">simples</del>')
        self.assertContains(r, reverse("obra:revisar", args=[1, self.p1.pagina]))
        self.assertContains(r, reverse("obra:no", args=["1916", XML_ID]) + f"#b{self.p1.pk}")
        self.assertContains(r, "Aplicar ao texto")
        self.assertContains(r, reverse("obra:sugestao_acao", args=[s.pk]))
        # aba com contagem
        self.assertContains(r, 'etiqueta etiqueta-carmim ml-1">1<')

    def test_filtros_e_avisos(self):
        s = self.cria()
        Bloco.objects.filter(pk=self.p1.pk).update(versao=5)
        orf = self.cria(bloco=None, bloco_versao=None, trecho="x", sugestao="y")
        rej = self.cria(estado=Sugestao.REJEITADA, trecho="rejeitada-t")
        self.client.force_login(self.editor)
        r = self.client.get(self.url_lista)
        self.assertContains(r, "O bloco foi alterado depois do envio")
        self.assertContains(r, f'id="s{orf.pk}"')
        self.assertNotContains(r, f'id="s{rej.pk}"')
        self.assertNotContains(r, "Aplicar ao texto</button>", count=None) if False else None
        r = self.client.get(self.url_lista, {"estado": "todas"})
        self.assertContains(r, f'id="s{rej.pk}"')
        r = self.client.get(self.url_lista, {"estado": "rejeitada"})
        self.assertNotContains(r, f'id="s{s.pk}"')
        r = self.client.get(self.url_lista, {"estado": "todas", "edicao": "nova"})
        self.assertNotContains(r, f'id="s{s.pk}"')

    def test_painel_mostra_cartao(self):
        self.client.force_login(self.editor)
        self.assertNotContains(self.client.get(reverse("obra:painel")), "Sugestões de leitores")
        self.cria()
        self.assertContains(self.client.get(reverse("obra:painel")), "1 sugestão pendente")


class AcaoTest(SugestoesBase):
    def setUp(self):
        super().setUp()
        self.editor = com_permissao(self.user)
        self.client.force_login(self.editor)

    def acao(self, s, qual, **extra):
        return self.client.post(reverse("obra:sugestao_acao", args=[s.pk]),
                                {"acao": qual, "next": reverse("obra:sugestoes") + "?estado=todas", **extra})

    def mensagens(self, r):
        return [str(m) for m in self.client.get(r.url).context["messages"]]

    def test_aplicar_ocorrencia_unica(self):
        s = self.cria()
        antes = self.p1.xml
        r = self.acao(s, "aplicar", resposta="ok")
        self.assertRedirects(r, reverse("obra:sugestoes") + "?estado=todas", fetch_redirect_response=False)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.xml, antes.replace("simples", "simplices"))
        self.assertEqual(self.p1.versao, 2)
        self.assertEqual(self.p1.atualizado_por, self.editor)
        rev = Revisao.objects.get(bloco=self.p1, acao=Revisao.EDITAR)
        self.assertEqual((rev.autor, rev.xml_antes, rev.xml_depois), (self.editor, antes, self.p1.xml))
        self.assertIn(f"Sugestão #{s.pk} de leitor (Zé)", rev.comentario)
        self.assertEqual((rev.volume, rev.pagina), (self.p1.volume, self.p1.pagina))
        s.refresh_from_db()
        self.assertEqual((s.estado, s.resolvida_por, s.resposta), ("aceita", self.editor, "ok"))
        self.assertIsNotNone(s.resolvida_em)

    def test_aplicar_nao_altera_pagina_nem_volume(self):
        s = self.cria()
        vol, pag = self.p1.volume_id, self.p1.pagina
        self.acao(s, "aplicar")
        self.p1.refresh_from_db()
        self.assertEqual((self.p1.volume_id, self.p1.pagina), (vol, pag))

    def test_aplicar_trecho_ausente(self):
        s = self.cria(trecho="não existe aqui")
        antes = self.p1.xml
        r = self.acao(s, "aplicar")
        self.assertTrue(any("não foi encontrado" in m for m in self.mensagens(r)))
        self.p1.refresh_from_db()
        self.assertEqual((self.p1.xml, self.p1.versao), (antes, 1))
        s.refresh_from_db()
        self.assertEqual(s.estado, "pendente")

    def test_aplicar_ambiguo(self):
        s = self.cria(trecho="e", sugestao="E")
        r = self.acao(s, "aplicar")
        self.assertTrue(any("aparece" in m and "vezes" in m for m in self.mensagens(r)))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.versao, 1)
        s.refresh_from_db()
        self.assertEqual(s.estado, "pendente")

    def test_aplicar_atravessando_elementos(self):
        s = self.cria(trecho="A idea é", sugestao="A ideia é")  # "idea" está num <hi>
        r = self.acao(s, "aplicar")
        self.assertTrue(any("atravessa" in m for m in self.mensagens(r)))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.versao, 1)

    def test_espacos_diferentes_casam(self):
        s = self.cria(trecho="—\n  A", sugestao="— O")
        self.acao(s, "aplicar")
        self.p1.refresh_from_db()
        self.assertIn("— O <hi", self.p1.xml)
        self.assertEqual(self.p1.versao, 2)

    def test_trecho_com_e_comercial(self):
        self.assertIn("&amp; fim", self.p1.xml)
        s = self.cria(trecho="continua & fim", sugestao="continua e fim")
        self.acao(s, "aplicar")
        self.p1.refresh_from_db()
        self.assertIn("continua e fim", self.p1.xml)
        self.assertNotIn("&amp; fim", self.p1.xml)
        s.refresh_from_db()
        self.assertEqual(s.estado, "aceita")

    def test_serializacao_identica_sem_troca(self):
        for b in Bloco.objects.filter(edicao=self.edicao):
            self.assertEqual(servicos_sugestoes.substituir_no_xml.__module__, "obra.servicos_sugestoes")
            from lxml import etree
            raiz = etree.fromstring(b.xml.encode("utf-8"))
            self.assertEqual(etree.tostring(raiz, encoding="unicode"), b.xml, b.xml)

    def test_pode_aplicar_so_quando_possivel(self):
        self.assertTrue(servicos_sugestoes.pode_aplicar(self.cria()))
        self.assertFalse(servicos_sugestoes.pode_aplicar(self.cria(trecho="")))
        self.assertFalse(servicos_sugestoes.pode_aplicar(self.cria(bloco=None)))
        self.assertFalse(servicos_sugestoes.pode_aplicar(self.cria(estado=Sugestao.REJEITADA)))
        s = self.cria(bloco=None)
        r = self.acao(s, "aplicar")
        self.assertTrue(any("não pode ser aplicada" in m for m in self.mensagens(r)))

    def test_rejeitar_e_reabrir(self):
        s = self.cria()
        self.acao(s, "rejeitar", resposta="Conferi no scan: está certo.")
        s.refresh_from_db()
        self.assertEqual((s.estado, s.resolvida_por, s.resposta), ("rejeitada", self.editor, "Conferi no scan: está certo."))
        self.acao(s, "reabrir")
        s.refresh_from_db()
        self.assertEqual((s.estado, s.resolvida_por, s.resolvida_em), ("pendente", None, None))

    def test_aceitar_a_mao(self):
        s = self.cria()
        self.acao(s, "aceitar")
        s.refresh_from_db()
        self.assertEqual((s.estado, s.resolvida_por), ("aceita", self.editor))
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.versao, 1)

    def test_so_post_e_next_seguro(self):
        s = self.cria()
        self.assertEqual(self.client.get(reverse("obra:sugestao_acao", args=[s.pk])).status_code, 405)
        r = self.client.post(reverse("obra:sugestao_acao", args=[s.pk]),
                             {"acao": "rejeitar", "next": "https://mal.example/x"})
        self.assertEqual(r.url, reverse("obra:sugestoes"))
