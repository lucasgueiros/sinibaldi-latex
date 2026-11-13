"""Gera de antemão, no cache, os PDFs dos volumes inteiros que o site oferece para baixar.

    manage.py preparar_downloads                     # fac-símile e PDF (LaTeX) de todos os volumes e edições
    manage.py preparar_downloads --so fac-simile     # só os fac-símiles (segundos)
    manage.py preparar_downloads --edicao 1916 --volume 1 --so pdf

Sem isso, cada arquivo é gerado na primeira vez que alguém o pede (o leitor vê "preparando…").
"""
from django.core.management.base import BaseCommand, CommandError

from obra import exportacao, fac_simile
from obra.models import Edicao, Volume


class Command(BaseCommand):
    help = "Gera no cache os PDFs (fac-símile e LaTeX) dos volumes inteiros."

    def add_arguments(self, parser):
        parser.add_argument("--edicao", nargs="*", help="slugs das edições (padrão: todas)")
        parser.add_argument("--volume", nargs="*", type=int, help="números dos volumes (padrão: todos)")
        parser.add_argument("--so", choices=["fac-simile", "pdf"], help="só um dos tipos")

    def handle(self, *args, **o):
        vols = Volume.objects.all()
        if o["volume"]:
            vols = vols.filter(numero__in=o["volume"])
        eds = Edicao.objects.all()
        if o["edicao"]:
            eds = eds.filter(slug__in=o["edicao"])
        falhas = 0
        for vol in vols:
            if o["so"] != "pdf":
                if fac_simile.disponivel(vol):
                    origem, destino, total = fac_simile.plano_volume(vol)
                    falhas += self._roda(f"fac-símile vol. {vol.numero}",
                                         lambda: fac_simile.preparar_volume(origem, destino, total))
                else:
                    self.stdout.write(f"fac-símile vol. {vol.numero}: scan original ausente, pulado")
            if o["so"] == "fac-simile":
                continue
            if not exportacao.pdf_disponivel():
                raise CommandError("latexmk não encontrado")
            for ed in eds:
                blocos = exportacao.blocos_do_volume(ed, vol)
                if not blocos.exists():
                    continue
                limite = exportacao.tempo_limite_pdf(blocos.count())
                falhas += self._roda(f"PDF {ed.slug} vol. {vol.numero}", lambda: exportacao.compilar_pdf(
                    exportacao.latex_do_volume(ed, vol), limite))
        if falhas:
            raise CommandError(f"{falhas} arquivo(s) falharam")

    def _roda(self, nome, funcao):
        self.stdout.write(f"{nome}… ", ending="")
        self.stdout.flush()
        try:
            caminho = funcao()
        except exportacao.ErroExportacao as e:
            self.stdout.write(self.style.ERROR(str(e)))
            return 1
        self.stdout.write(self.style.SUCCESS(f"{caminho} ({caminho.stat().st_size // 2**20} MB)"))
        return 0
