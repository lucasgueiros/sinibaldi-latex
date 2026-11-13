"""Reconhece as citações pelas aspas e cria o cadastro (`Citacao`) — ver `obra/citacoes.py`.

    manage.py marcar_citacoes                      # só relata (1916 e nova)
    manage.py marcar_citacoes --aplicar            # grava (com Revisao) e indexa
    manage.py marcar_citacoes --edicao 1916 --volume 2 --exemplos 10
    manage.py marcar_citacoes --reindexar          # só refaz o cadastro a partir do texto

Na 1916 todo parágrafo/sumário com aspas é examinado; as cópias exatas na nova recebem o xml marcado
(mesmos ids); na nova, só os blocos adaptados/novos são examinados. Idempotente.
"""
from django.core.management.base import BaseCommand

from obra import servicos_citacoes
from obra.models import Edicao


class Command(BaseCommand):
    help = "Marca as citações (aspas -> <quote>, «(…)» -> <bibl>) e indexa o cadastro de citações."

    def add_arguments(self, p):
        p.add_argument("--aplicar", action="store_true", help="grava; sem isto só relata")
        p.add_argument("--edicao", choices=["1916", "nova"], help="só esta edição")
        p.add_argument("--volume", type=int, help="só este volume")
        p.add_argument("--exemplos", type=int, default=0, help="mostra N fragmentos alterados")
        p.add_argument("--reindexar", action="store_true", help="só refaz o cadastro a partir do texto")

    def handle(self, *args, aplicar, edicao, volume, exemplos, reindexar, **opts):
        if reindexar:
            n, inativas = servicos_citacoes.reindexar()
            self.stdout.write(f"{n} citação(ões) indexada(s); {inativas} marcada(s) como inativa(s).")
            return
        eds = [e for e in (Edicao.objects.filter(slug="1916").first(), Edicao.objects.filter(tipo=Edicao.NOVA).first())
               if e is not None and (edicao is None or e.slug == edicao or (edicao == "nova" and e.tipo == Edicao.NOVA))]
        alterados_1916 = []
        for ed in eds:
            if ed.tipo == Edicao.NOVA and alterados_1916:
                n = servicos_citacoes.propagar_para_nova(alterados_1916, aplicar=aplicar)
                self.stdout.write(f"[{ed.slug}] {n} cópia(s) recebem o xml marcado da 1916.")
            rel, alterados = servicos_citacoes.marcar_edicao(ed, aplicar=aplicar, volume=volume)
            if ed.tipo == Edicao.DIPLOMATICA:
                alterados_1916 = alterados
            self.stdout.write(f"[{ed.slug}] {len(alterados)} bloco(s): {rel}")
            for b, xml in alterados[:exemplos]:
                self.stdout.write(f"  #{b.pk} p.{b.pagina}: {xml[:400]}")
        if not aplicar:
            self.stdout.write("(use --aplicar para gravar)")
        else:
            n, inativas = servicos_citacoes.reindexar()
            self.stdout.write(f"Cadastro: {n} citação(ões) indexada(s); {inativas} inativa(s).")
