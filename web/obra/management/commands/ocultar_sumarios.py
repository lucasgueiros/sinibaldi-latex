"""Oculta na edição nova os sumários de capítulo do autor (OCR ruim); a página do capítulo
mostra no lugar um sumário gerado dos artigos e teses (obra/sumarios.py)."""
from django.core.management.base import BaseCommand, CommandError

from obra import leitura, servicos_nova, sumarios
from obra.models import Bloco, Edicao, Revisao


class Command(BaseCommand):
    help = ("Lista (e, com --aplicar, suprime na edição nova) os sumários de capítulo do autor. "
            "--desfazer restaura os que este comando suprimiu.")

    def add_arguments(self, p):
        p.add_argument("--aplicar", action="store_true", help="Suprime os blocos achados (sem isso, só relata).")
        p.add_argument("--desfazer", action="store_true", help="Restaura os blocos suprimidos por este comando.")
        p.add_argument("--edicao", default="nova")

    def handle(self, *args, aplicar, desfazer, edicao, **opts):
        try:
            ed = Edicao.objects.get(slug=edicao, tipo=Edicao.NOVA)
        except Edicao.DoesNotExist:
            raise CommandError(f"Não há edição nova com slug '{edicao}'.")
        if desfazer:
            return self._desfazer(ed)
        arv = leitura.Arvore(ed)
        achados = sumarios.detectar(ed)
        for a in achados:
            no = arv.cobrindo(a.blocos[0].ordem)
            onde = no.xml_id if no else "?"
            extra = f"  [título grudado: {a.titulo_embutido}]" if a.titulo_embutido else ""
            self.stdout.write(f"{onde}: {len(a.blocos)} bloco(s){extra}")
            for b in a.blocos:
                self.stdout.write(f"    {leitura.texto_plano(b.xml, notas=False)[:100]}")
        n = sum(len(a.blocos) for a in achados)
        self.stdout.write(f"{len(achados)} sumário(s), {n} bloco(s).")
        if not aplicar:
            if achados:
                self.stdout.write("(use --aplicar para suprimi-los na edição nova)")
            return
        feitos = 0
        for a in achados:
            for b in a.blocos:
                feitos += servicos_nova.definir_supressao(ed, b.ordem, b.ordem + 1, True,
                                                          comentario=sumarios.COMENTARIO)
        self.stdout.write(self.style.SUCCESS(f"{feitos} bloco(s) suprimido(s)."))

    def _desfazer(self, ed):
        pks = set(Revisao.objects.filter(edicao=ed, comentario=sumarios.COMENTARIO, bloco__isnull=False)
                  .values_list("bloco_id", flat=True))
        feitos = 0
        for b in Bloco.objects.filter(pk__in=pks, procedencia=Bloco.SUPRIMIDO).order_by("ordem"):
            feitos += servicos_nova.definir_supressao(ed, b.ordem, b.ordem + 1, False,
                                                      comentario="Sumário do autor restaurado (ocultar_sumarios --desfazer).")
        self.stdout.write(self.style.SUCCESS(f"{feitos} bloco(s) restaurado(s)."))
