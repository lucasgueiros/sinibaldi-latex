"""Refaz o «Indice das materias» do fim de cada volume a partir dos títulos (obra/indice.py)."""
from django.core.management.base import BaseCommand, CommandError

from obra import indice, leitura, servicos
from obra.management.commands.aplicar_componentes import religar
from obra.models import Edicao, Volume


class Command(BaseCommand):
    help = "Lista (e, com --aplicar, grava) o índice das matérias gerado dos títulos de cada edição."

    def add_arguments(self, p):
        p.add_argument("--aplicar", action="store_true", help="Grava (sem isso, só relata).")
        p.add_argument("--edicao", action="append", help="slug (repetível); padrão: 1916 e as derivadas")
        p.add_argument("--volume", type=int, action="append", help="número do volume (repetível); padrão: todos")
        p.add_argument("--detalhe", action="store_true", help="imprime as entradas geradas")

    def handle(self, *args, aplicar, edicao, volume, detalhe, **opts):
        slugs = edicao or ["1916"] + [e.slug for e in Edicao.ordenadas(Edicao.objects.filter(tipo__in=Edicao.DERIVADAS))]
        impressas = leitura.impressas()
        numeros = volume or list(Volume.objects.order_by("numero").values_list("numero", flat=True))
        for slug in slugs:
            ed = Edicao.objects.filter(slug=slug).first()
            if ed is None:
                raise CommandError(f"Edição '{slug}' não existe.")
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {slug}"))
            tocados = []
            for n in numeros:
                blocos = indice.regiao(ed, n)
                if not blocos:
                    self.stdout.write(f"  vol. {n}: sem anexo do índice (rode aplicar_componentes antes).")
                    continue
                xmls = indice.gerar(ed, n, impressas)
                if xmls == indice.atual(blocos):
                    self.stdout.write(f"  vol. {n}: já em dia ({len(xmls)} entradas).")
                    continue
                self.stdout.write(f"  vol. {n}: {len(blocos) - 2} bloco(s) -> {len(xmls)} entradas")
                if detalhe:
                    for x in xmls:
                        self.stdout.write(f"      {x}")
                if aplicar:
                    r = servicos.salvar_blocos(ed, [b.pk for b in blocos], indice.componente(blocos, xmls), None,
                                               indice.COMENTARIO, volume=blocos[0].volume_id, pagina=blocos[0].pagina)
                    tocados += r.blocos
            if aplicar and ed.derivada and tocados:
                self.stdout.write(f"  {religar(ed, [b.pk for b in tocados])} bloco(s) religados à 1916 como cópia.")
            if not aplicar:
                self.stdout.write("  (use --aplicar para gravar)")
