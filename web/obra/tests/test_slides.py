"""Slides: página pública, PDF/.tex/.txt, cache, editor da fonte, histórico, concorrência."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model
from django.urls import reverse

from obra import arvore, exportacao, slides
from obra.models import Apresentacao, ApresentacaoRevisao, Bloco, No

from .base import BaseBanco

PDF_MINIMO = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n" + b"0" * 64
CAP = "v1.cap-1"


class SlidesBase(BaseBanco):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        perm = Permission.objects.get(codename="change_bloco", content_type__app_label="obra")
        cls.user.user_permissions.add(perm)     # ana edita; beto não

    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cache, True)
        p = mock.patch.dict(os.environ, {"SINIBALDI_CACHE": self.cache})
        p.start()
        self.addCleanup(p.stop)
        self.compilacoes = []

        def falso(tex, destino, *, timeout=180):
            self.compilacoes.append(tex)
            destino.write_bytes(PDF_MINIMO)

        p = mock.patch.object(slides.gerador(), "compilar", falso)
        p.start()
        self.addCleanup(p.stop)

    def no(self, xml_id=CAP):
        return No.objects.get(edicao=self.edicao, xml_id=xml_id)

    def url(self, nome, xml_id=CAP, slug="1916"):
        return reverse(f"obra:{nome}", args=[slug, xml_id])

    def entrar(self, usuario=None):
        self.client.force_login(usuario or self.user)


class PublicoTest(SlidesBase):
    def test_pagina_publica(self):
        r = self.client.get(self.url("slides"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.url("slides_pdf"))
        self.assertContains(r, "gerado automaticamente")
        self.assertContains(r, "<iframe")
        self.assertNotContains(r, "Corrigir os slides")
        self.assertEqual(self.compilacoes, [], "a página não compila")

    def test_link_na_pagina_do_no(self):
        r = self.client.get(reverse("obra:no", args=["1916", CAP]))
        self.assertContains(r, 'href="%s"' % self.url("slides"))

    def test_pagina_mostra_botao_so_para_editor(self):
        self.entrar()
        self.assertContains(self.client.get(self.url("slides")), "Corrigir os slides")
        self.entrar(self.user2)
        self.assertNotContains(self.client.get(self.url("slides")), "Corrigir os slides")

    def test_pdf(self):
        r = self.client.get(self.url("slides_pdf"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("inline", r["Content-Disposition"])
        self.assertTrue(b"".join(r.streaming_content).startswith(b"%PDF"))
        self.assertEqual(r["X-Frame-Options"], "SAMEORIGIN")
        self.assertTrue(r["ETag"])

    def test_pdf_baixar_e_etag(self):
        r = self.client.get(self.url("slides_pdf"), {"baixar": "1"})
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn(".pdf", r["Content-Disposition"])
        n = len(self.compilacoes)
        r2 = self.client.get(self.url("slides_pdf"), HTTP_IF_NONE_MATCH=r["ETag"])
        self.assertEqual(r2.status_code, 304)
        self.assertEqual(len(self.compilacoes), n)

    def test_tex_e_txt(self):
        r = self.client.get(self.url("slides_txt"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/plain", r["Content-Type"])
        self.assertIn("=== capa", r.content.decode())
        r = self.client.get(self.url("slides_tex"), {"baixar": "1"})
        self.assertIn("\\begin{document}", r.content.decode())
        self.assertIn("attachment", r["Content-Disposition"])

    def test_cache(self):
        self.client.get(self.url("slides_pdf"))
        self.assertEqual(len(self.compilacoes), 1)
        self.client.get(self.url("slides_pdf"))
        self.assertEqual(len(self.compilacoes), 1)

    def test_fonte_nova_recompila(self):
        self.client.get(self.url("slides_pdf"))
        no = self.no()
        slides.pdf_do_no(no, slides.fonte_automatica(no) + "\n=== texto\n# Outro\n")
        self.assertEqual(len(self.compilacoes), 2)

    def test_tema_novo_recompila(self):
        self.client.get(self.url("slides_pdf"))
        with mock.patch.object(slides, "versao_tema", return_value="outro"):
            self.client.get(self.url("slides_pdf"))
        self.assertEqual(len(self.compilacoes), 2)

    def test_404(self):
        for nome in ("slides", "slides_pdf", "slides_tex", "slides_txt"):
            self.assertEqual(self.client.get(self.url(nome, "v1.nao-existe")).status_code, 404, nome)
            self.assertEqual(self.client.get(self.url(nome, slug="zzz")).status_code, 404, nome)

    def test_limite_de_tamanho(self):
        with mock.patch.object(slides, "MAX_BLOCOS", 2):
            r = self.client.get(self.url("slides", "v1.parte-1"))
            self.assertContains(r, "mais do que os 2")
            self.assertContains(r, self.url("slides", "v1.cap-1"))     # aponta para os filhos
            self.assertNotContains(r, "<iframe")
            r = self.client.get(self.url("slides_pdf", "v1.parte-1"))
            self.assertEqual(r.status_code, 503)
            self.assertEqual(self.compilacoes, [])
            r = self.client.get(reverse("obra:no", args=["1916", "v1.parte-1"]))
            self.assertNotContains(r, 'href="%s"' % self.url("slides", "v1.parte-1"))

    def test_erro_de_compilacao_amigavel(self):
        g = slides.gerador()

        def quebra(tex, destino, *, timeout=180):
            raise g.ErroSlides("o LaTeX falhou", "! Undefined control sequence.")

        with mock.patch.object(g, "compilar", quebra):
            r = self.client.get(self.url("slides_pdf"))
            self.assertEqual(r.status_code, 503)
            self.assertContains(r, "Não foi possível", status_code=503)
            self.assertNotContains(r, "Undefined control", status_code=503)      # log só para o editor
            self.entrar()
            r = self.client.get(self.url("slides_pdf"))
            self.assertContains(r, "Undefined control", status_code=503)

    def test_nova_edicao(self):
        # nova edição derivada: mesmo trecho, outra apresentação
        from obra.models import Edicao
        nova = Edicao.objects.create(slug="nova", titulo="Nova", tipo="nova")
        Bloco.objects.bulk_create([Bloco(edicao=nova, ordem=b.ordem, tipo=b.tipo, xml=b.xml, volume=b.volume,
                                         pagina=b.pagina, origem=b) for b in self.blocos()])
        arvore.reconstruir(nova)
        self.assertEqual(self.client.get(self.url("slides", slug="nova")).status_code, 200)


class RestritoTest(SlidesBase):
    def test_exige_login_e_permissao(self):
        for nome in ("slides_lista", "slides_editor"):
            alvo = reverse("obra:slides_lista") if nome == "slides_lista" else self.url(nome)
            r = self.client.get(alvo)
            self.assertEqual(r.status_code, 302)
            self.assertIn("/entrar/", r["Location"])
            self.entrar(self.user2)
            self.assertEqual(self.client.get(alvo).status_code, 403)
            self.client.logout()
        for nome in ("slides_salvar", "slides_regenerar", "slides_descartar", "slides_restaurar"):
            self.assertEqual(self.client.post(self.url(nome), {}).status_code, 302)
            self.entrar(self.user2)
            self.assertEqual(self.client.post(self.url(nome), {}).status_code, 403)
            self.client.logout()
        self.assertEqual(Apresentacao.objects.count(), 0)

    def test_editor_mostra_fonte_sem_gravar(self):
        self.entrar()
        r = self.client.get(self.url("slides_editor"))
        self.assertContains(r, "=== capa")
        self.assertContains(r, 'name="versao" value="0"')
        self.assertContains(r, "automática (ainda não salva)")
        self.assertEqual(Apresentacao.objects.count(), 0)
        self.assertEqual(self.client.get(self.url("slides_editor", "v1.nada")).status_code, 404)

    def salvar(self, fonte, versao=0, xml_id=CAP, **kw):
        return self.client.post(self.url("slides_salvar", xml_id), {"fonte": fonte, "versao": versao}, **kw)

    def fonte_corrigida(self):
        return slides.fonte_automatica(self.no()).replace("Idea", "Ideia", 1)

    def test_salvar(self):
        self.entrar()
        f = self.fonte_corrigida()
        r = self.salvar(f.replace("\n", "\r\n"))
        self.assertRedirects(r, self.url("slides_editor"), fetch_redirect_response=False)
        ap = Apresentacao.objects.get()
        self.assertEqual(ap.fonte, f)
        self.assertTrue(ap.editada)
        self.assertEqual(ap.versao, 1)
        self.assertEqual(ap.atualizado_por, self.user)
        rev = ApresentacaoRevisao.objects.get()
        self.assertEqual((rev.acao, rev.autor, rev.xml_id), ("editar", self.user, CAP))
        # recompilou a fonte nova e a página pública a usa
        self.assertEqual(len(self.compilacoes), 1)
        self.assertIn("Ideia", self.compilacoes[0])
        r = self.client.get(self.url("slides"))
        self.assertContains(r, "revisado por")
        self.assertContains(self.client.get(reverse("obra:slides_lista")), "corrigida")
        # segundo salvamento: versão sobe
        self.salvar(f + "\n=== texto\n# Mais\n", versao=1)
        self.assertEqual(Apresentacao.objects.get().versao, 2)
        self.assertEqual(ApresentacaoRevisao.objects.count(), 2)

    def test_fonte_invalida_nao_grava(self):
        self.entrar()
        r = self.salvar("=== capa\n=== texto\n")
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "linha 1:", status_code=400)
        self.assertContains(r, "=== capa", status_code=400)         # o texto digitado volta
        self.assertEqual(Apresentacao.objects.count(), 0)
        r = self.salvar("   ")
        self.assertContains(r, "vazia", status_code=400)

    def test_conflito_de_versao(self):
        self.entrar()
        f = self.fonte_corrigida()
        self.salvar(f)                                   # ana grava (versão 1)
        beto = get_user_model().objects.create_user("carla", password="x")
        beto.user_permissions.add(Permission.objects.get(codename="change_bloco"))
        self.entrar(beto)
        meu = f + "\n=== texto\n# Do beto\n"
        r = self.salvar(meu, versao=0)                   # beto leu antes da ana gravar
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, "Outra pessoa gravou", status_code=409)
        self.assertContains(r, "Do beto", status_code=409)           # nada de texto perdido
        self.assertContains(r, 'name="versao" value="1"', status_code=409)
        self.assertEqual(Apresentacao.objects.get().fonte, f)         # nada sobrescrito
        # com a versão atual, salvar funciona
        self.assertEqual(self.salvar(meu, versao=1).status_code, 302)
        self.assertEqual(Apresentacao.objects.get().versao, 2)

    def test_regenerar(self):
        self.entrar()
        f = self.fonte_corrigida()
        self.salvar(f)
        # com correções, exige confirmação
        r = self.client.post(self.url("slides_regenerar"), {"versao": 1})
        self.assertEqual(Apresentacao.objects.get().fonte, f)
        r = self.client.post(self.url("slides_regenerar"), {"versao": 1, "confirmo": "1"})
        ap = Apresentacao.objects.get()
        self.assertEqual(ap.fonte, slides.fonte_automatica(self.no()))
        self.assertFalse(ap.editada)
        self.assertEqual(ap.versao, 2)
        self.assertEqual(ApresentacaoRevisao.objects.first().acao, "regenerar")
        self.assertTrue(ApresentacaoRevisao.objects.filter(fonte=f).exists())     # a anterior está no histórico

    def test_descartar(self):
        self.entrar()
        f = self.fonte_corrigida()
        self.salvar(f)
        self.client.post(self.url("slides_descartar"), {"versao": 1})                 # sem confirmação
        self.assertEqual(Apresentacao.objects.count(), 1)
        self.client.post(self.url("slides_descartar"), {"versao": 1, "confirmo": "1"})
        self.assertEqual(Apresentacao.objects.count(), 0)
        self.assertEqual(slides.fonte_do_no(self.no()), slides.fonte_automatica(self.no()))
        ultima = ApresentacaoRevisao.objects.first()
        self.assertEqual((ultima.acao, ultima.fonte), ("descartar", f))              # histórico sobrevive

    def test_restaurar(self):
        self.entrar()
        f1 = self.fonte_corrigida()
        f2 = f1 + "\n=== texto\n# Segunda\n"
        self.salvar(f1)
        self.salvar(f2, versao=1)
        primeira = ApresentacaoRevisao.objects.order_by("pk").first()
        r = self.client.post(self.url("slides_restaurar"), {"revisao": primeira.pk, "versao": 2})
        self.assertEqual(r.status_code, 302)
        ap = Apresentacao.objects.get()
        self.assertEqual(ap.fonte, f1)
        self.assertEqual(ap.versao, 3)
        self.assertEqual(ApresentacaoRevisao.objects.first().acao, "restaurar")
        self.assertContains(self.client.get(self.url("slides_editor")), "Restaurar")
        # revisão de outro trecho não vale
        r = self.client.post(self.url("slides_restaurar", "v1.t1"), {"revisao": primeira.pk, "versao": 0})
        self.assertEqual(r.status_code, 404)

    def test_aviso_texto_mudou(self):
        self.entrar()
        f = self.fonte_corrigida()
        self.salvar(f)
        self.assertNotContains(self.client.get(self.url("slides_editor")), "texto do livro mudou")
        b = Bloco.objects.get(edicao=self.edicao, xml__contains='xml:id="v1.t1.p1"')
        b.xml = b.xml.replace("simples", "complicada")
        b.versao += 1
        b.save()
        r = self.client.get(self.url("slides_editor"))
        self.assertContains(r, "texto do livro mudou")
        self.assertContains(r, "complicada")                      # diff com a fonte automática nova
        self.assertContains(self.client.get(reverse("obra:slides_lista")), "texto do livro mudou")
        self.assertEqual(Apresentacao.objects.get().fonte, f)  # não sobrescreve

    def test_sobrevive_a_reconstruir(self):
        self.entrar()
        self.salvar(self.fonte_corrigida())
        arvore.reconstruir(self.edicao)
        ap = slides.apresentacao_do_no(self.no())
        self.assertIsNotNone(ap)
        self.assertIn("Ideia", slides.fonte_do_no(self.no()))
        self.assertEqual(self.client.get(self.url("slides_editor")).status_code, 200)

    def test_erro_de_compilacao_depois_de_salvar(self):
        self.entrar()
        g = slides.gerador()

        def quebra(tex, destino, *, timeout=180):
            raise g.ErroSlides("o LaTeX falhou", "! Missing $ inserted.")

        with mock.patch.object(g, "compilar", quebra):
            r = self.salvar(self.fonte_corrigida(), follow=True)
        self.assertEqual(Apresentacao.objects.count(), 1)             # a fonte ficou salva
        self.assertContains(r, "compilação falhou")
        self.assertContains(r, "Missing $ inserted")

    def test_conteudo_hostil(self):
        self.entrar()
        hostil = ("=== texto\n# <script>alert(1)</script> \\input{/etc/passwd}\n"
                  "! \\write18{id} </textarea><script>x()</script> $ & # % _ ~ {\n")
        r = self.salvar(hostil)
        self.assertEqual(r.status_code, 302)
        r = self.client.get(self.url("slides_editor"))
        self.assertNotContains(r, "<script>alert(1)")
        self.assertNotContains(r, "</textarea><script>x()")
        self.assertContains(r, "&lt;script&gt;alert(1)")
        tex = slides.tex_do_no(self.no())
        self.assertNotIn("\\input{/etc/passwd}", tex)
        self.assertNotIn("\\write18{", tex)
        self.assertEqual(self.client.get(self.url("slides")).status_code, 200)
        self.assertEqual(self.client.get(self.url("slides_tex")).status_code, 200)
        r = self.client.get(reverse("obra:slides_lista"))
        self.assertNotContains(r, "<script>alert(1)")


class ComandoTest(SlidesBase):
    def test_gerar_slides(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command("gerar_slides", "--edicao", "1916", "--no", CAP, "--fonte", stdout=out)
        self.assertIn("=== capa", out.getvalue())
        destino = os.path.join(self.cache, "saida.pdf")
        call_command("gerar_slides", "--no", CAP, "-o", destino, stdout=StringIO(), stderr=StringIO())
        self.assertTrue(open(destino, "rb").read().startswith(b"%PDF"))


@unittest.skipUnless(shutil.which("latexmk"), "latexmk não instalado")
class IntegracaoLatexTest(BaseBanco):
    """Compila de verdade (sem o falso)."""

    def test_pdf_real(self):
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, {"SINIBALDI_CACHE": cache}):
            no = No.objects.get(edicao=self.edicao, xml_id=CAP)
            pdf = slides.pdf_do_no(no)
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
            r = self.client.get(reverse("obra:slides_pdf", args=["1916", CAP]))
            self.assertEqual(r["Content-Type"], "application/pdf")
            # fonte hostil compila (tudo é escapado)
            h = "=== texto\n# \\input{/etc/passwd} $ & # %\n- ^ ~ _ { } \\\n"
            self.assertTrue(slides.pdf_do_no(no, h).is_file())
