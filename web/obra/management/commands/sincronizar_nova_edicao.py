"""Sincroniza as edições derivadas ("atualizada", "nova") com a "1916" (que continua sendo revisada)."""
from django.core.management.base import BaseCommand, CommandError

from obra import servicos_nova
from obra.models import Edicao


class Command(BaseCommand):
    help = ("Mostra (e, com --aplicar, atualiza) as cópias das edições derivadas cujo texto difere do da 1916. "
            "Também informa os adaptados com origem alterada e os blocos da 1916 sem correspondente.")

    def add_arguments(self, p):
        p.add_argument("--aplicar", action="store_true",
                       help="Atualiza as cópias desatualizadas (sem isso, só relata).")
        p.add_argument("--edicao", action="append", help="slug (repetível); padrão: todas as derivadas")

    def handle(self, *args, aplicar, edicao, **opts):
        qs = Edicao.objects.filter(tipo__in=Edicao.DERIVADAS)
        if edicao:
            qs = qs.filter(slug__in=edicao)
        eds = Edicao.ordenadas(qs)
        if not eds:
            raise CommandError("Nenhuma edição derivada (derivar_edicao_atualizada / derivar_nova_edicao).")
        for nova in eds:
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {nova.slug}"))
            self._uma(nova, aplicar)

    def _uma(self, nova, aplicar):
        copias = servicos_nova.copias_desatualizadas(nova).count()
        self.stdout.write(f"Cópias desatualizadas: {copias}")
        if aplicar:
            n = servicos_nova.atualizar_copias(nova, autor=None)
            self.stdout.write(self.style.SUCCESS(f"{n} cópia(s) atualizada(s) a partir da 1916."))
        elif copias:
            self.stdout.write("(use --aplicar para atualizá-las)")
        self.stdout.write(f"Adaptados com origem alterada (decisão do editor): {servicos_nova.adaptados_pendentes(nova).count()}")
        self.stdout.write(f"Blocos da 1916 sem correspondente: {servicos_nova.sem_correspondente(nova).count()}")
