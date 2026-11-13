"""Gera os slides de um trecho pela linha de comando, com o mesmo serviço do site."""
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from obra import exportacao, slides
from obra.models import No


class Command(BaseCommand):
    help = ("Gera o PDF dos slides de um trecho (a fonte salva no site, se houver; senão a automática). "
            "Com --fonte, escreve a fonte (.txt) em vez do PDF; sem -o, a fonte vai para a saída padrão.")

    def add_arguments(self, p):
        p.add_argument("--edicao", default="1916")
        p.add_argument("--no", required=True, help="xml:id do trecho, ex.: v2.art-6")
        p.add_argument("-o", "--saida", help="arquivo de saída (padrão do PDF: nome do trecho, na pasta atual)")
        p.add_argument("--fonte", action="store_true", help="gera a fonte dos slides, não o PDF")
        p.add_argument("--forcar", action="store_true", help="permite sobrescrever o arquivo de saída")

    def handle(self, *args, edicao, no, saida, fonte, forcar, **opts):
        try:
            n = No.objects.select_related("edicao", "volume").get(edicao__slug=edicao, xml_id=no)
        except No.DoesNotExist:
            raise CommandError(f"Trecho {edicao}/{no} não encontrado.")
        try:
            if not slides.disponivel(n):
                raise CommandError(f"{no} tem mais de {slides.MAX_BLOCOS} blocos; escolha um trecho menor.")
            texto = slides.fonte_do_no(n)
            if fonte:
                if not saida:
                    self.stdout.write(texto, ending="")
                    return
                destino = self._destino(saida, forcar)
                destino.write_text(texto, encoding="utf-8")
            else:
                destino = self._destino(saida or exportacao.nome_arquivo(n, "slides.pdf"), forcar)
                self.stderr.write(f"{slides.resumo(texto)[0]} slides; compilando…")
                shutil.copyfile(slides.pdf_do_no(n, texto), destino)
        except exportacao.ErroExportacao as e:
            raise CommandError(f"{e}\n{getattr(e, 'log', '')}".strip())
        self.stdout.write(self.style.SUCCESS(f"Escrito {destino} ({destino.stat().st_size} bytes)."))

    @staticmethod
    def _destino(caminho, forcar):
        d = Path(caminho)
        if d.exists() and not forcar:
            raise CommandError(f"{d} já existe; use --forcar para sobrescrever.")
        d.parent.mkdir(parents=True, exist_ok=True)
        return d
