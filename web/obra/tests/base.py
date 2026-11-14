"""Fixtures compartilhadas pelos testes."""
import contextlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from lxml import etree

from obra import arvore, tei
from obra.models import PASSO_ORDEM, Bloco, Edicao, Pagina, Volume

TEI_SINTETICO = """<?xml version='1.0' encoding='UTF-8'?>
<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:lang="pt"><teiHeader><fileDesc><titleStmt><title>T</title></titleStmt></fileDesc></teiHeader>
<text><body><div type="volume"><pb n="1" facs="paginas/0001.png"/><p>Frontispício</p>
<div type="parte" xml:id="parte-1"><head type="rotulo">PARTE PRIMEIRA</head><head>LOGICA</head>
<div type="capitulo" xml:id="cap-1"><head type="rotulo">CAPITULO I</head><head>IDEA</head>
<argument><p>Sumário do capítulo.</p></argument>
<div type="tese" n="1" xml:id="t1"><p xml:id="t1.p1"><label>1.</label> <hi rend="bold">Idea.</hi> — A <hi rend="it">idea</hi> é simples<note place="foot" n="1" xml:id="n1-1"><p>Nota um <hi rend="it">it</hi>.</p><p>Segunda.</p></note> e<pb n="2" facs="paginas/0002.png"/><fw type="header">2 CABEC</fw> continua &amp; fim.</p>
<pb n="2" facs="paginas/0002.png"/><fw type="header">2 CABEC</fw></div>
<div type="tese" n="2" xml:id="t2"><p xml:id="t2.p1"><label>2.</label> <hi rend="bold">Termo.</hi> — Texto <hi rend="sc">Santo</hi> Thomas.<note place="foot" n="1" xml:id="n2-1">Nota solta com <hi rend="it">grifo</hi>.</note></p><p>Outro parágrafo.</p></div>
</div></div>
<div type="parte" xml:id="parte-2"><head type="rotulo">PARTE SEGUNDA</head><head>COSMOLOGIA</head>
<pb n="3" facs="paginas/0003.png"/>
<div type="tese" n="3" xml:id="t3"><p xml:id="t3.p1"><label>3.</label> <hi rend="bold">Mundo.</hi> — Corpo.</p></div></div>
</div></body></text></TEI>"""


def tei_sintetico():
    return etree.fromstring(TEI_SINTETICO.encode("utf-8"))


def texto(el):
    return "".join(t for t in el.itertext())


class BaseBanco(TestCase):
    """Cria edição 1916 com o TEI sintético importado (volume 1)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("ana", password="x")
        cls.user2 = get_user_model().objects.create_user("beto", password="x")
        cls.edicao = Edicao.objects.create(slug="1916", titulo="Diplomática", tipo="diplomatica")
        cls.vol = Volume.objects.create(numero=1, titulo="V1", ano=1917, diretorio="vol1")
        rel = tei.Relatorio()
        dados = tei.achatar(tei_sintetico(), numero=1, relatorio=rel)
        Bloco.objects.bulk_create([
            Bloco(edicao=cls.edicao, ordem=i * PASSO_ORDEM, tipo=d.tipo, xml=d.xml, volume=cls.vol, pagina=d.pagina)
            for i, d in enumerate(dados, 1)])
        Pagina.objects.bulk_create([Pagina(volume=cls.vol, seq=s, arquivo=a, impressa=str(s))
                                    for s, a in rel.paginas.items()])
        arvore.reconstruir(cls.edicao)

    def blocos(self, edicao=None):
        return list(Bloco.objects.filter(edicao=edicao or self.edicao).order_by("ordem"))


def define_eager(app, valor):
    """Liga/desliga o modo eager. As duas chaves: no Celery < 5.7, a chave com prefixo vinda do
    settings (CELERY_TASK_ALWAYS_EAGER) prevalece sobre `app.conf.task_always_eager`."""
    app.conf.task_always_eager = valor
    app.conf["CELERY_TASK_ALWAYS_EAGER"] = valor


@contextlib.contextmanager
def fila_de_verdade():
    """Desliga o modo eager e sobe um worker Celery numa thread (broker e backend em memória): os
    pedidos passam pela fila como em produção. As tarefas não usam o banco, então a thread não
    precisa da conexão do teste; os `mock.patch` do teste valem para ela."""
    from celery.contrib.testing.worker import start_worker
    from sinibaldi.celery import app
    antes = app.conf.task_always_eager
    define_eager(app, False)
    try:
        with start_worker(app, pool="solo", perform_ping_check=False, shutdown_timeout=10):
            yield app
    finally:
        define_eager(app, antes)
