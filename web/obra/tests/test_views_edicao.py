import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from obra import diffs, servicos, tei
from obra.models import Bloco, Pagina, Revisao
from .base import BaseBanco


def com_permissao(usuario):
    usuario.user_permissions.add(Permission.objects.get(codename="change_bloco", content_type__app_label="obra"))
    return get_user_model().objects.get(pk=usuario.pk)


class TextoXmlTest(BaseBanco):
    def test_ida_e_volta(self):
        blocos = self.blocos()
        texto = tei.blocos_para_texto_xml(blocos)
        self.assertTrue(texto.startswith(f'<?bloco id="{blocos[0].pk}" versao="1"?>\n'))
        volta = tei.texto_xml_para_blocos(texto)
        self.assertEqual([(b["id"], b["versao"], b["xml"]) for b in volta], [(b.pk, b.versao, b.xml) for b in blocos])

    def test_blocos_novos_sem_cabecalho(self):
        texto = '<p>Um novo.</p>\n\n<?bloco id="7" versao="2"?>\n<p>Antigo</p>\n\n<p>Outro novo</p>'
        volta = tei.texto_xml_para_blocos(texto)
        self.assertEqual([(b["id"], b["versao"]) for b in volta], [(None, None), (7, 2), (None, None)])
        self.assertEqual(tei.blocos_para_texto_xml([{"xml": "<p>x</p>"}]), "<p>x</p>")

    def test_canonico_ordena_atributos(self):
        (b,) = tei.texto_xml_para_blocos('<milestone xml:id="a" n="1" unit="tese"/>')
        self.assertEqual(b["xml"], '<milestone unit="tese" n="1" xml:id="a"/>')

    def test_erros(self):
        with self.assertRaises(tei.ErroTextoXml) as cm:
            tei.texto_xml_para_blocos("<p>ok</p>\n\n<p>aberto\n\n<foo/>\n\n<p><b>x</b></p>")
        erros = "\n".join(cm.exception.erros)
        self.assertIn("Bloco 2: XML malformado", erros)
        self.assertIn("Bloco 3: Elemento <foo> fora do vocabulário", erros)
        self.assertIn("Bloco 4:", erros)
        with self.assertRaises(tei.ErroTextoXml) as cm:
            tei.texto_xml_para_blocos('<?bloco id="x"?>\n<p>a</p>')
        self.assertIn("inválido", cm.exception.erros[0])

    def test_xml_id_repetido_entre_blocos(self):
        with self.assertRaises(tei.ErroTextoXml) as cm:
            tei.texto_xml_para_blocos('<p xml:id="a">1</p>\n\n<p xml:id="a">2</p>')
        self.assertIn("já usado", cm.exception.erros[0])


class DiffTest(BaseBanco):
    def test_diff_por_palavras(self):
        h = str(diffs.diff_html("<p>a casa velha</p>", "<p>a casa nova &amp; bela</p>"))
        self.assertIn('<del class="dif-del">velha</del>', h)
        self.assertIn('<ins class="dif-ins">nova &amp;amp; bela</ins>', h)
        self.assertNotIn("<p>", h)  # o XML é escapado


class BaseViews(BaseBanco):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ana = com_permissao(cls.user)
        cls.beto = com_permissao(cls.user2)
        cls.sem = get_user_model().objects.create_user("sem", password="x")

    def setUp(self):
        self.client.force_login(self.ana)

    def url_rev(self, seq=2):
        return reverse("obra:revisar", args=[1, seq])

    def post_json(self, url, dados):
        return self.client.post(url, json.dumps(dados), content_type="application/json")

    def escopo(self, seq):
        bs = servicos.blocos_da_pagina(self.edicao, self.vol, seq)
        return bs, [b.pk for b in bs]


class PermissoesTest(BaseViews):
    def urls_html(self):
        return [reverse("obra:painel"), reverse("obra:paginas", args=[1]), self.url_rev(),
                reverse("obra:historico"), reverse("obra:historico_bloco", args=[self.blocos()[0].pk])]

    def urls_api(self):
        return [reverse("obra:converter"), reverse("obra:gravar", args=[1, 2])]

    def test_anonimo_vai_para_login(self):
        self.client.logout()
        for u in self.urls_html():
            r = self.client.get(u)
            self.assertEqual(r.status_code, 302, u)
            self.assertIn(reverse("entrar"), r["Location"])
        for u in self.urls_api():
            self.assertEqual(self.post_json(u, {}).status_code, 401, u)

    def test_sem_permissao_403(self):
        self.client.force_login(self.sem)
        for u in self.urls_html():
            self.assertEqual(self.client.get(u).status_code, 403, u)
        for u in self.urls_api():
            self.assertEqual(self.post_json(u, {}).status_code, 403, u)

    def test_com_permissao_200(self):
        for u in self.urls_html():
            self.assertEqual(self.client.get(u).status_code, 200, u)

    def test_get_em_endpoint_post_405(self):
        self.assertEqual(self.client.get(reverse("obra:converter")).status_code, 405)


class PainelEListaTest(BaseViews):
    def test_painel(self):
        servicos.marcar_pagina(Pagina.objects.get(seq=1), "revisada", self.ana)
        r = self.client.get(reverse("obra:painel"))
        self.assertContains(r, "Progresso por volume")
        vol = r.context["volumes"][0]
        self.assertEqual((vol["contagem"]["revisada"], vol["contagem"]["nao_revisada"], vol["total"]), (1, 2, 3))
        self.assertIsNone(r.context["continuar"])
        self.assertContains(r, "/edicao-colaborativa/nova/")

    def test_continuar_de_onde_parei(self):
        bs, ids = self.escopo(2)
        alvo = next(b for b in bs if "Outro" in b.xml)
        servicos.salvar_blocos(self.edicao, [alvo.pk], [{"id": alvo.pk, "versao": alvo.versao, "xml": alvo.xml.replace("Outro", "Mais")}],
                               self.ana, "x", volume=self.vol, pagina=2)
        r = self.client.get(reverse("obra:painel"))
        self.assertEqual(r.context["continuar"]["seq"], 2)
        self.assertEqual(len(r.context["lotes"]), 1)
        self.assertEqual(r.context["lotes"][0]["autor"], "ana")
        self.assertContains(r, self.url_rev(2))

    def test_paginas_filtro_e_ir(self):
        servicos.marcar_pagina(Pagina.objects.get(seq=3), "validada", self.ana)
        r = self.client.get(reverse("obra:paginas", args=[1]), {"estado": "validada"})
        self.assertEqual([p.seq for p in r.context["page_obj"]], [3])
        r = self.client.get(reverse("obra:paginas", args=[1]))
        self.assertEqual([p.seq for p in r.context["page_obj"]], [1, 2, 3])
        r = self.client.get(reverse("obra:paginas", args=[1]), {"ir": "2"})
        self.assertRedirects(r, self.url_rev(2), fetch_redirect_response=False)
        r = self.client.get(reverse("obra:paginas", args=[1]), {"ir": "99"})
        self.assertContains(r, "não encontrada")
        self.assertEqual(self.client.get(reverse("obra:paginas", args=[9])).status_code, 404)


class RevisarTest(BaseViews):
    def test_get(self):
        r = self.client.get(self.url_rev(2))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="dados-revisao"')
        self.assertContains(r, 'id="esquema-editor"')
        self.assertContains(r, "js/editor.bundle.js")
        d = r.context["dados"]
        bs, ids = self.escopo(2)
        self.assertEqual(d["ids"], ids)
        self.assertEqual(d["pagina"], {"n": 2, "facs": "paginas/0002.png", "impressa": "2"})
        self.assertEqual(r.context["anterior"].seq, 1)
        self.assertEqual(r.context["seguinte"].seq, 3)
        self.assertEqual(r.context["esquema"]["tipos_paragrafo"]["definicao"], "Definição")
        self.assertIn(f'data-bloco="{ids[0]}"', d["html"])

    def test_bloco_que_atravessa_e_sinalizado(self):
        r = self.client.get(self.url_rev(2))
        info = r.context["dados"]["info"]
        t1p1 = Bloco.objects.get(xml__contains='xml:id="v1.t1.p1"')  # começa na pág. 1, tem <pb n="2">
        self.assertTrue(info[str(t1p1.pk)]["comeca_antes"])
        proprios = [v for k, v in info.items() if k != str(t1p1.pk)]
        self.assertTrue(all(not v["comeca_antes"] for v in proprios))

    def test_pagina_inexistente(self):
        self.assertEqual(self.client.get(self.url_rev(99)).status_code, 404)

    def test_seq_negativo(self):
        Pagina.objects.create(volume=self.vol, seq=-3, arquivo="f003", impressa="iii")
        self.assertEqual(self.client.get(self.url_rev(-3)).status_code, 200)


class ConverterTest(BaseViews):
    url = property(lambda self: reverse("obra:converter"))

    def test_html_para_xml(self):
        bs, ids = self.escopo(2)
        html = tei.blocos_para_html(bs)
        d = self.post_json(self.url, {"de": "html", "conteudo": html}).json()
        self.assertEqual(d["erros"], [])
        self.assertEqual(d["xml"], tei.blocos_para_texto_xml(bs))
        self.assertEqual(d["html"], html)

    def test_xml_para_html(self):
        bs, ids = self.escopo(2)
        d = self.post_json(self.url, {"de": "xml", "conteudo": tei.blocos_para_texto_xml(bs)}).json()
        self.assertEqual(d["erros"], [])
        self.assertEqual(d["html"], tei.blocos_para_html(bs))

    def test_erro_de_validacao_xml(self):
        r = self.post_json(self.url, {"de": "xml", "conteudo": "<p>ok</p>\n\n<foo>x</foo>"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIsNone(d["html"])
        self.assertTrue(any(e.startswith("Bloco 2:") for e in d["erros"]), d["erros"])

    def test_xml_malformado(self):
        d = self.post_json(self.url, {"de": "xml", "conteudo": "<p>aberto"}).json()
        self.assertIn("XML malformado", d["erros"][0])

    def test_erro_de_validacao_html(self):
        d = self.post_json(self.url, {"de": "html", "conteudo": '<p data-tei="p" data-xmlid="a">x</p><p data-tei="p" data-xmlid="a">y</p>'}).json()
        self.assertEqual(d["xml"], None)
        self.assertIn("já usado", d["erros"][0])

    def test_pedido_invalido(self):
        self.assertEqual(self.post_json(self.url, {"de": "docx"}).status_code, 400)
        self.assertEqual(self.client.post(self.url, "isto não é json", content_type="application/json").status_code, 400)


class GravarTest(BaseViews):
    def url(self, seq=2):
        return reverse("obra:gravar", args=[1, seq])

    def corpo_html(self, bs, ids, subst=None, **extra):
        html = tei.blocos_para_html(bs)
        for a, b in (subst or {}).items():
            html = html.replace(a, b)
        return {"formato": "html", "conteudo": html, "ids": ids, "comentario": "teste", **extra}

    def test_edita_e_registra_autor(self):
        bs, ids = self.escopo(2)
        alvo = next(b for b in bs if "Outro parágrafo" in b.xml)
        r = self.post_json(self.url(), self.corpo_html(bs, ids, {"Outro parágrafo": "Outro parágrafo corrigido"}))
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertTrue(d["ok"] and d["alterou"])
        self.assertEqual(d["resumo"]["editados"], 1)
        alvo.refresh_from_db()
        self.assertIn("corrigido", alvo.xml)
        self.assertEqual((alvo.versao, alvo.atualizado_por), (2, self.ana))
        rev = Revisao.objects.get(bloco=alvo, acao="editar")
        self.assertEqual((rev.autor, rev.comentario, rev.volume, rev.pagina), (self.ana, "teste", self.vol, 2))
        self.assertEqual(d["ids"], ids)
        self.assertEqual(d["info"][str(alvo.pk)]["autor"], "ana")
        self.assertIn('data-versao="2"', d["html"])
        self.assertIn("<?bloco", d["xml"])

    def test_sem_alteracao_nao_cria_revisao(self):
        bs, ids = self.escopo(2)
        n = Revisao.objects.count()
        d = self.post_json(self.url(), self.corpo_html(bs, ids)).json()
        self.assertTrue(d["ok"])
        self.assertFalse(d["alterou"])
        self.assertEqual(Revisao.objects.count(), n)

    def test_grava_pelo_xml(self):
        bs, ids = self.escopo(2)
        texto = tei.blocos_para_texto_xml(bs).replace("Outro parágrafo", "Outro texto")
        r = self.post_json(self.url(), {"formato": "xml", "conteudo": texto, "ids": ids})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(Bloco.objects.filter(xml__contains="Outro texto").exists())

    def test_bloco_novo_recebe_volume_e_pagina(self):
        bs, ids = self.escopo(2)
        html = tei.blocos_para_html(bs) + '\n<p data-tei="p">Parágrafo criado na tela.</p>'
        d = self.post_json(self.url(), {"formato": "html", "conteudo": html, "ids": ids}).json()
        self.assertEqual(d["resumo"]["criados"], 1)
        novo = Bloco.objects.get(xml__contains="criado na tela")
        self.assertEqual((novo.volume, novo.pagina, novo.criado_por), (self.vol, 2, self.ana))
        self.assertEqual(Revisao.objects.get(bloco=novo).acao, "criar")
        self.assertEqual(d["ids"][-1], novo.pk)

    def test_remover_bloco(self):
        bs, ids = self.escopo(2)
        alvo = next(b for b in bs if "Outro parágrafo" in b.xml)
        html = tei.blocos_para_html([b for b in bs if b.pk != alvo.pk])
        d = self.post_json(self.url(), {"formato": "html", "conteudo": html, "ids": ids}).json()
        self.assertEqual(d["resumo"]["removidos"], 1)
        self.assertFalse(Bloco.objects.filter(pk=alvo.pk).exists())

    def test_erro_de_validacao_400(self):
        bs, ids = self.escopo(2)
        r = self.post_json(self.url(), {"formato": "xml", "conteudo": "<p>aberto", "ids": ids})
        self.assertEqual(r.status_code, 400)
        self.assertIn("XML malformado", r.json()["erros"][0])
        self.assertEqual(self.post_json(self.url(), {"formato": "x", "conteudo": "", "ids": ids}).status_code, 400)
        self.assertEqual(self.post_json(self.url(), {"formato": "html", "conteudo": "", "ids": ["a"]}).status_code, 400)

    def test_conflito_409(self):
        bs, ids = self.escopo(2)
        alvo = next(b for b in bs if "Outro parágrafo" in b.xml)
        # Beto grava primeiro
        servicos.salvar_blocos(self.edicao, [alvo.pk], [{"id": alvo.pk, "versao": alvo.versao, "xml": alvo.xml.replace("Outro", "Beto")}],
                               self.beto, "do beto", volume=self.vol, pagina=2)
        corpo = self.corpo_html(bs, ids, {"Outro parágrafo": "Outro da Ana"})  # versão antiga carregada
        r = self.post_json(self.url(), corpo)
        self.assertEqual(r.status_code, 409)
        d = r.json()
        self.assertTrue(d["conflito"])
        self.assertEqual(d["ids"], [alvo.pk])
        self.assertEqual(d["detalhes"][0]["autor"], "beto")
        self.assertIn("beto", d["erros"][0])
        alvo.refresh_from_db()
        self.assertIn("Beto", alvo.xml)  # nada foi sobrescrito

    def test_estado_da_pagina(self):
        bs, ids = self.escopo(2)
        d = self.post_json(self.url(), self.corpo_html(bs, ids, estado="revisada")).json()
        self.assertEqual(d["estado"]["valor"], "revisada")
        p = Pagina.objects.get(seq=2)
        self.assertEqual((p.estado, p.revisada_por), ("revisada", self.ana))
        self.assertEqual(self.post_json(self.url(), self.corpo_html(bs, ids, estado="x")).status_code, 400)

    def test_pagina_vazia_ancora_antes_do_fim(self):
        Pagina.objects.create(volume=self.vol, seq=99, impressa="99")
        Bloco.objects.filter(edicao=self.edicao).update(pagina=1)
        ultimo = Bloco.objects.filter(edicao=self.edicao).order_by("-ordem").first()
        # o último bloco da edição pertence ao volume 1, página 1: a página 99 (vazia) insere depois dele
        d = self.post_json(self.url(99), {"formato": "html", "conteudo": '<p data-tei="p">Nova.</p>', "ids": []}).json()
        self.assertEqual(d["resumo"]["criados"], 1)
        novo = Bloco.objects.get(xml__contains="Nova.")
        self.assertGreater(novo.ordem, ultimo.ordem)
        self.assertEqual(novo.pagina, 99)


class HistoricoTest(BaseViews):
    def setUp(self):
        super().setUp()
        bs, ids = self.escopo(2)
        self.alvo = next(b for b in bs if "Outro parágrafo" in b.xml)
        servicos.salvar_blocos(self.edicao, [self.alvo.pk], [{"id": self.alvo.pk, "versao": 1, "xml": self.alvo.xml.replace("Outro", "Segundo")}],
                               self.ana, "primeira troca", volume=self.vol, pagina=2)
        servicos.salvar_blocos(self.edicao, [self.alvo.pk], [{"id": self.alvo.pk, "versao": 2, "xml": self.alvo.xml.replace("Outro", "Terceiro")}],
                               self.beto, "segunda troca", volume=self.vol, pagina=2)

    def test_lista_com_diff_e_autor(self):
        r = self.client.get(reverse("obra:historico"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["itens"]), 2)
        self.assertContains(r, "primeira troca")
        self.assertContains(r, '<del class="dif-del">Segundo</del>')
        self.assertContains(r, '<ins class="dif-ins">Terceiro</ins>')
        self.assertContains(r, "beto")

    def test_filtros(self):
        h = reverse("obra:historico")
        r = self.client.get(h, {"autor": self.ana.pk})
        self.assertEqual([i["autor"] for i in r.context["itens"]], ["ana"])
        self.assertEqual(len(self.client.get(h, {"volume": "1", "pagina": "2"}).context["itens"]), 2)
        self.assertEqual(len(self.client.get(h, {"pagina": "3"}).context["itens"]), 0)
        self.assertEqual(len(self.client.get(h, {"volume": "2"}).context["itens"]), 0)

    def test_importacao_oculta_por_padrao(self):
        Revisao.objects.create(edicao=self.edicao, acao="importar", lote="7f2f4a4e-9d6b-4c4e-8f6a-1d1d2a3b4c5d", xml_depois="<p>x</p>")
        h = reverse("obra:historico")
        self.assertEqual(len(self.client.get(h).context["itens"]), 2)
        self.assertEqual(len(self.client.get(h, {"importacoes": "1"}).context["itens"]), 3)

    def test_historico_do_bloco(self):
        r = self.client.get(reverse("obra:historico_bloco", args=[self.alvo.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["linhas"]), 2)
        self.assertContains(r, "segunda troca")
        self.assertEqual(self.client.get(reverse("obra:historico_bloco", args=[999999])).status_code, 404)

    def test_tela_de_revisao_linka_historico(self):
        r = self.client.get(reverse("obra:revisar", args=[1, 2]))
        self.assertContains(r, reverse("obra:historico") + "?volume=1&amp;pagina=2")
        self.assertEqual(r.context["dados"]["info"][str(self.alvo.pk)]["autor"], "beto")
