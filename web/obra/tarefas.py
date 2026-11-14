"""Tarefas Celery: o trabalho pesado que antes rodava em threads do processo web.

Recebem caminhos e textos já resolvidos pela view (só as do volume inteiro leem o banco, para
gerar o LaTeX longe da requisição), escrevem no cache em disco (`SINIBALDI_CACHE`, compartilhado por
todos os processos) e devolvem ["pronto", caminho] ou ["erro", mensagem amigável]. São idempotentes — um pedido repetido acha o arquivo no cache e sai
na hora —, então rodar duas vezes (corrida entre processos, reentrega após queda do worker) é
inofensivo. Quem as chama: `exportacao.em_segundo_plano`.
"""
from pathlib import Path

from celery import shared_task

from . import exportacao, fac_simile, slides


def _rodar(funcao, *args):
    try:
        return ["pronto", str(funcao(*args))]
    except exportacao.ErroExportacao as e:
        return ["erro", str(e)]


@shared_task(name="obra.ping")
def ping():
    """Verificação de saúde (deploy/release.sh, CI): ida e volta por broker, worker e resultados."""
    return "pong"


@shared_task(name="obra.pdf")
def pdf(tex, limite):
    """PDF A5 padrão do .tex autônomo (nó ou volume)."""
    return _rodar(exportacao.compilar_pdf, Path(tex), limite)


@shared_task(name="obra.pdf_formato")
def pdf_formato(tex, formato, titulo, limite):
    """PDF numa das diagramações de `exportacao.FORMATOS_PDF`."""
    return _rodar(exportacao.compilar_pdf_formato, Path(tex), formato, titulo, limite)


@shared_task(name="obra.fac_simile_trecho")
def fac_simile_trecho(partes, destino):
    """Fac-símile das páginas de um trecho (`fac_simile.plano_trecho`)."""
    return _rodar(fac_simile.preparar_trecho, [tuple(p) for p in partes], destino)


@shared_task(name="obra.fac_simile_volume")
def fac_simile_volume(origem, destino, total):
    """Fac-símile do volume inteiro, paginado (`fac_simile.plano_volume`)."""
    return _rodar(fac_simile.preparar_volume, origem, destino, total)


@shared_task(name="obra.slides")
def slides_pdf(fonte, trecho, chave=None):
    """PDF dos slides de uma fonte; uma falha fica em `slides-<chave>.erro` com o log do LaTeX.
    `chave` (`slides.chave_da_fonte`: tema + fonte) só entra no id da tarefa: tema novo, pedido novo."""
    return _rodar(slides.compilar_fonte, fonte, trecho)


def _edicao_volume(edicao, numero):
    from .models import Edicao, Volume
    return Edicao.objects.get(slug=edicao), Volume.objects.get(numero=numero)


@shared_task(name="obra.pdf_volume")
def pdf_volume(edicao, numero, formato, limite, versao=None):
    """PDF do volume inteiro: gera o LaTeX (minutos; lê o banco) e compila. `formato` "" = A5.
    `versao` (`exportacao._versao_volume`) só entra no id: texto mudou, pedido novo."""
    def f():
        ed, vol = _edicao_volume(edicao, numero)
        return exportacao.pdf_do_volume(ed, vol, formato or None, limite)
    return _rodar(f)


@shared_task(name="obra.latex_volume")
def latex_volume(edicao, numero, versao=None):
    """.tex autônomo do volume inteiro (lê o banco)."""
    return _rodar(lambda: exportacao.latex_do_volume(*_edicao_volume(edicao, numero)))
