"""Geração em segundo plano pelo Celery: vagas de compilação entre processos, id das tarefas e
slides pela fila (página "preparando" no iframe, gravação que não espera a compilação)."""
import os
import subprocess
import sys
import tempfile
import threading
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from obra import exportacao, slides, tarefas

from .base import fila_de_verdade
from .test_slides import CAP, PDF_MINIMO, SlidesBase


class VagaPdfTest(SimpleTestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        p = mock.patch.dict(os.environ, {"SINIBALDI_CACHE": self.cache})
        p.start()
        self.addCleanup(p.stop)

    @override_settings(SINIBALDI_PDF_SIMULTANEOS=1)
    def test_sem_vaga_levanta(self):
        with exportacao.vaga_pdf(1):
            with self.assertRaisesMessage(exportacao.ErroExportacao, "ocupado"):
                with exportacao.vaga_pdf(0.1):
                    pass
        with exportacao.vaga_pdf(0.1):      # liberada ao sair
            pass

    @override_settings(SINIBALDI_PDF_SIMULTANEOS=2)
    def test_duas_vagas(self):
        with exportacao.vaga_pdf(1), exportacao.vaga_pdf(1):
            with self.assertRaises(exportacao.ErroExportacao):
                with exportacao.vaga_pdf(0.1):
                    pass

    @override_settings(SINIBALDI_PDF_SIMULTANEOS=1)
    def test_vale_entre_processos(self):
        """Outro processo segurando a vaga (flock no mesmo arquivo) bloqueia este."""
        trava = os.path.join(self.cache, "vagas", "pdf-0.lock")
        os.makedirs(os.path.dirname(trava))
        codigo = ("import fcntl, sys, time; f = open(sys.argv[1], 'w'); fcntl.flock(f, fcntl.LOCK_EX); "
                  "print('ok', flush=True); time.sleep(30)")
        outro = subprocess.Popen([sys.executable, "-c", codigo, trava], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(outro.stdout.readline().strip(), "ok")
            with self.assertRaises(exportacao.ErroExportacao):
                with exportacao.vaga_pdf(0.3):
                    pass
        finally:
            outro.kill()
            outro.wait()
        with exportacao.vaga_pdf(2):
            pass


class IdTarefaTest(SimpleTestCase):
    def test_deterministico(self):
        a = exportacao.id_tarefa(tarefas.pdf, ["/x.tex", 120])
        self.assertEqual(a, exportacao.id_tarefa(tarefas.pdf, ["/x.tex", 120]))
        self.assertNotEqual(a, exportacao.id_tarefa(tarefas.pdf, ["/y.tex", 120]))
        self.assertNotEqual(a, exportacao.id_tarefa(tarefas.pdf_formato, ["/x.tex", 120]))

    def test_tarefas_registradas(self):
        from sinibaldi.celery import app
        for nome in ("obra.pdf", "obra.pdf_formato", "obra.fac_simile_trecho", "obra.fac_simile_volume",
                     "obra.slides"):
            self.assertIn(nome, app.tasks)


class SlidesPelaFilaTest(SlidesBase):
    def lento(self):
        """Troca a compilação falsa por uma que espera `liberado`."""
        liberado = threading.Event()

        def compila(tex, destino, *, timeout=180):
            self.compilacoes.append(tex)
            liberado.wait(10)
            destino.write_bytes(PDF_MINIMO)

        p = mock.patch.object(slides.gerador(), "compilar", compila)
        p.start()
        self.addCleanup(p.stop)
        return liberado

    def test_iframe_mostra_preparando_e_depois_o_pdf(self):
        liberado = self.lento()
        url = self.url("slides_pdf")
        with fila_de_verdade(), mock.patch("obra.exportacao.ESPERA_PADRAO", 0.05):
            r = self.client.get(url, headers={"Sec-Fetch-Dest": "iframe"})
            self.assertEqual(r.status_code, 202)
            self.assertContains(r, 'http-equiv="refresh"', status_code=202)
            self.assertNotContains(r, "<nav", status_code=202)          # página leve, sem o layout do site
            self.assertEqual(r["Cache-Control"], "no-store")
            r = self.client.get(url)                                    # fora do iframe: página completa
            self.assertContains(r, "Voltar aos slides", status_code=202)
            liberado.set()
            with mock.patch("obra.exportacao.ESPERA_PADRAO", 5):
                r = self.client.get(url, headers={"Sec-Fetch-Dest": "iframe"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), PDF_MINIMO)
        self.assertEqual(len(self.compilacoes), 1)

    def test_salvar_nao_espera_a_compilacao(self):
        liberado = self.lento()
        self.entrar()
        fonte = slides.fonte_automatica(self.no()) + "\n=== texto\n# Mais um\n"
        with fila_de_verdade(), mock.patch("obra.views_slides.ESPERA_RECOMPILAR", 0.05):
            r = self.client.post(self.url("slides_salvar"), {"fonte": fonte, "versao": 0}, follow=True)
            self.assertContains(r, "sendo compilado")
            self.assertNotContains(r, "recompilados")
            liberado.set()
            with mock.patch("obra.exportacao.ESPERA_PADRAO", 5):
                r = self.client.get(self.url("slides_pdf"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.compilacoes), 1)

    def test_erro_pela_fila_mostra_log_ao_editor(self):
        g = slides.gerador()

        def quebra(tex, destino, *, timeout=180):
            raise g.ErroSlides("o LaTeX falhou", "! Undefined control sequence.")

        self.entrar()
        with fila_de_verdade(), mock.patch.object(g, "compilar", quebra), \
                mock.patch("obra.exportacao.ESPERA_PADRAO", 5):
            r = self.client.get(self.url("slides_pdf"))
        self.assertContains(r, "Não foi possível", status_code=503)
        self.assertContains(r, "Undefined control", status_code=503)


class SemFilaTest(SlidesBase):
    def test_broker_fora_do_ar_vira_erro_amigavel(self):
        from sinibaldi.celery import app
        app.conf.task_always_eager = False      # (patch.object em app.conf apagaria a chave ao restaurar)
        self.addCleanup(setattr, app.conf, "task_always_eager", True)
        with mock.patch.object(tarefas.slides_pdf, "AsyncResult", side_effect=ConnectionError("sem redis")):
            r = self.client.get(reverse("obra:slides_pdf", args=["1916", CAP]))
        self.assertContains(r, "indisponível", status_code=503)
