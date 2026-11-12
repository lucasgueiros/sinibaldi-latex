"""Exporta um volume de uma edição como TEI aninhado."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from obra import exportacao
from obra.models import Edicao, Volume


class Command(BaseCommand):
    help = "Exporta um volume de uma edição para um arquivo TEI (não sobrescreve sem --forcar)."

    def add_arguments(self, p):
        p.add_argument("--edicao", default="1916")
        p.add_argument("--volume", type=int, required=True)
        p.add_argument("-o", "--saida", required=True)
        p.add_argument("--forcar", action="store_true", help="permite sobrescrever o arquivo de saída")

    def handle(self, *args, edicao, volume, saida, forcar, **opts):
        try:
            ed = Edicao.objects.get(slug=edicao)
            vol = Volume.objects.get(numero=volume)
        except (Edicao.DoesNotExist, Volume.DoesNotExist) as e:
            raise CommandError(str(e))
        destino = Path(saida)
        if destino.exists() and not forcar:
            raise CommandError(f"{destino} já existe; use --forcar para sobrescrever.")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(exportacao.tei_do_volume(ed, vol), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Escrito {destino} ({destino.stat().st_size} bytes)."))
