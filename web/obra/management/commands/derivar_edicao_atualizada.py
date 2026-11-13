"""Cria a edição "atualizada" a partir da 1916, na MESMA ordem (sem reordenar partes).

É a base sobre a qual os editores fazem a rediagramação, a atualização ortográfica e gramatical, a
das referências e citações, a revisão das gravuras e as notas do editor (`Edicao.COMPONENTES_ATUALIZADA`).
Cada bloco nasce `copia`, com `origem` na 1916, e acompanha a revisão dela como a nova edição
(`sincronizar_nova_edicao --edicao atualizada`)."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from obra import arvore
from obra.models import PASSO_ORDEM, Bloco, Edicao

DESCRICAO = ("Parte do texto de 1916/17, na mesma ordem, com rediagramação, ortografia e gramática atualizadas, "
             "referências e citações atualizadas, gravuras revistas e notas do editor; cada trecho remete à origem "
             "na edição de 1916/17.")


class Command(BaseCommand):
    help = "Deriva a edição 'atualizada' da '1916' (cópia dos blocos, sem cabeçalhos correntes, na mesma ordem)."

    def add_arguments(self, p):
        p.add_argument("--recriar", action="store_true", help="Apaga os blocos atuais da atualizada e copia de novo.")
        p.add_argument("--oculta", action="store_true", help="Cria a edição escondida da parte pública.")

    @transaction.atomic
    def handle(self, *args, recriar, oculta, **opts):
        try:
            orig = Edicao.objects.get(slug="1916")
        except Edicao.DoesNotExist:
            raise CommandError("Importe a edição 1916 antes (importar_tei).")
        ed, criada = Edicao.objects.get_or_create(slug="atualizada", defaults=dict(
            titulo="Edição atualizada", tipo=Edicao.ATUALIZADA, descricao=DESCRICAO, publica=not oculta))
        if not criada and ed.tipo != Edicao.ATUALIZADA:
            raise CommandError("Já existe uma edição 'atualizada' de outro tipo.")
        if ed.blocos.exists():
            if not recriar:
                raise CommandError("A edição 'atualizada' já tem blocos; use --recriar.")
            ed.blocos.all().delete()
            ed.nos.all().delete()
        novos = [Bloco(edicao=ed, ordem=i * PASSO_ORDEM, tipo=b.tipo, xml=b.xml, volume_id=b.volume_id,
                       pagina=b.pagina, origem=b, procedencia=Bloco.COPIA, origem_versao_vista=b.versao)
                 for i, b in enumerate(orig.blocos.exclude(tipo=Bloco.CABECALHO).order_by("ordem"), 1)]
        Bloco.objects.bulk_create(novos, batch_size=1000)
        arvore.reconstruir(ed)
        self.stdout.write(f"Edição 'atualizada': {len(novos)} blocos, {ed.nos.count()} nós"
                          f"{' (oculta)' if not ed.publica else ''}.")
