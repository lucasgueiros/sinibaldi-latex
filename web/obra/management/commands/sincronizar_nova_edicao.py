"""Sincroniza a edição "nova" com a "1916" (que continua sendo revisada)."""
from django.core.management.base import BaseCommand, CommandError

from obra import servicos_nova
from obra.models import Edicao


class Command(BaseCommand):
    help = ("Mostra (e, com --aplicar, atualiza) as cópias da nova edição cujo texto difere do da 1916. "
            "Também informa os adaptados com origem alterada e os blocos da 1916 sem correspondente.")

    def add_arguments(self, p):
        p.add_argument("--aplicar", action="store_true",
                       help="Atualiza as cópias desatualizadas (sem isso, só relata).")

    def handle(self, *args, aplicar, **opts):
        try:
            nova = Edicao.objects.get(slug="nova", tipo=Edicao.NOVA)
        except Edicao.DoesNotExist:
            raise CommandError("A edição 'nova' não existe (derivar_nova_edicao).")
        copias = servicos_nova.copias_desatualizadas(nova).count()
        self.stdout.write(f"Cópias desatualizadas: {copias}")
        if aplicar:
            n = servicos_nova.atualizar_copias(nova, autor=None)
            self.stdout.write(self.style.SUCCESS(f"{n} cópia(s) atualizada(s) a partir da 1916."))
        elif copias:
            self.stdout.write("(use --aplicar para atualizá-las)")
        self.stdout.write(f"Adaptados com origem alterada (decisão do editor): {servicos_nova.adaptados_pendentes(nova).count()}")
        self.stdout.write(f"Blocos da 1916 sem correspondente na nova: {servicos_nova.sem_correspondente(nova).count()}")
