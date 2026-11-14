"""Troca um trecho de texto em todos os blocos (correção simples de OCR), direto no banco.

    manage.py corrigir_texto "isto 6" "isto é" --palavra            # só relata
    manage.py corrigir_texto "isto 6" "isto é" --palavra --aplicar  # grava

A troca vale só para o texto dos blocos: o que está dentro de tags e atributos (`<hi rend="it">`,
`xml:id`) nunca é tocado. Um trecho que atravessa uma marca (`isto <hi>6</hi>`) não é achado.

Na 1916 grava pelo serviço `salvar_blocos` (uma Revisao por bloco, versão incrementada). Nas derivadas
(nova…), as cópias são atualizadas a partir da 1916 (servicos_nova.atualizar_copias); os blocos `adaptado`
(decisão do editor) recebem a mesma troca quando o trecho ainda existe neles. Idempotente."""
import re

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from obra import servicos, servicos_nova
from obra.models import Bloco, Edicao

_TAG = re.compile(r"(<[^>]*>)")


def substituir(xml, padrao, depois):
    """(novo_xml, n_trocas): troca só nos segmentos de texto, nunca dentro de tags."""
    n = 0
    partes = _TAG.split(xml)
    for i in range(0, len(partes), 2):          # índices pares = texto; ímpares = tags
        partes[i], k = padrao.subn(depois, partes[i])
        n += k
    return "".join(partes), n


class Command(BaseCommand):
    help = "Troca um trecho de texto nos blocos (1916 e derivadas); sem --aplicar só relata."

    def add_arguments(self, p):
        p.add_argument("antes", help="Trecho a procurar (literal; com --regex, expressão regular).")
        p.add_argument("depois", help="Substituto (com --regex, aceita \\1 etc.).")
        p.add_argument("--aplicar", action="store_true", help="Grava (sem isso, só relata).")
        p.add_argument("--regex", action="store_true", help="`antes` é uma expressão regular.")
        p.add_argument("--palavra", action="store_true", help="Só com fronteira de palavra nas pontas.")
        p.add_argument("--comentario", help="Comentário da Revisao (padrão: «antes -> depois»).")
        p.add_argument("--autor", help="Usuário que consta nas revisões (padrão: nenhum).")

    def handle(self, *args, antes, depois, aplicar, regex, palavra, comentario, autor, **opts):
        if not antes:
            raise CommandError("`antes` não pode ser vazio.")
        expr = antes if regex else re.escape(antes)
        if palavra:
            expr = rf"(?<!\w)(?:{expr})(?!\w)"
        try:
            padrao = re.compile(expr)
        except re.error as e:
            raise CommandError(f"Expressão inválida: {e}")
        if not regex:
            depois_fn = lambda m: depois          # noqa: E731  literal: sem escapes de grupo
        else:
            depois_fn = depois
        user = None
        if autor:
            user = get_user_model().objects.filter(username=autor).first()
            if user is None:
                raise CommandError(f"Usuário '{autor}' não existe.")
        comentario = comentario or f"{antes} -> {depois}"

        ed16 = Edicao.objects.filter(slug="1916").first()
        if ed16 is None:
            raise CommandError("A edição '1916' não existe.")
        self.stdout.write(self.style.MIGRATE_HEADING("== 1916"))
        alterados = self._edicao16(ed16, padrao, depois_fn, aplicar, comentario, user)
        derivadas = Edicao.ordenadas(Edicao.objects.filter(tipo__in=Edicao.DERIVADAS))
        for ed in derivadas if alterados else []:
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {ed.slug}"))
            self._derivada(ed, padrao, depois_fn, alterados, aplicar, comentario, user)
        # trechos que só existem na derivada (blocos novos/adaptados sem origem alterada)
        for ed in derivadas:
            self._so_derivada(ed, padrao, depois_fn, set(alterados), aplicar, comentario, user)
        if not aplicar:
            self.stdout.write("(use --aplicar para gravar)")

    def _edicao16(self, ed, padrao, depois, aplicar, comentario, user):
        alterados = {}
        for b in Bloco.objects.filter(edicao=ed).order_by("ordem"):
            novo, n = substituir(b.xml, padrao, depois)
            if not n or novo == b.xml:
                continue
            alterados[b.pk] = b.xml
            self.stdout.write(f"  bloco #{b.pk} (vol. {b.volume_id}, p. {b.pagina}): {n} troca(s)")
            if aplicar:
                servicos.salvar_blocos(ed, [b.pk], [{"id": b.pk, "versao": b.versao, "xml": novo}], user,
                                       comentario, volume=b.volume_id, pagina=b.pagina)
        self.stdout.write(f"  {len(alterados)} bloco(s) alterado(s).")
        return alterados

    def _derivada(self, ed, padrao, depois, alterados, aplicar, comentario, user):
        derivados = list(Bloco.objects.filter(edicao=ed, origem_id__in=alterados).select_related("origem"))
        copias = [b for b in derivados if b.procedencia == Bloco.COPIA]
        adaptados = [b for b in derivados if b.procedencia == Bloco.ADAPTADO]
        self.stdout.write(f"  {len(copias)} cópia(s) a atualizar, {len(adaptados)} adaptado(s) a conferir.")
        if copias and aplicar:
            servicos_nova.atualizar_copias(ed, ids=[b.pk for b in copias])
        for b in adaptados:
            self._grava(ed, b, padrao, depois, aplicar, comentario, user, adaptado=True)

    def _so_derivada(self, ed, padrao, depois, ja_vistos_origem, aplicar, comentario, user):
        """Blocos da derivada com o trecho que não vieram de um bloco da 1916 alterado agora
        (novos, ou adaptados cuja origem já estava certa)."""
        for b in Bloco.objects.filter(edicao=ed).exclude(origem_id__in=ja_vistos_origem).order_by("ordem"):
            if b.procedencia == Bloco.COPIA and b.origem_id:
                continue            # cópia fiel de um bloco da 1916 que não contém o trecho
            self._grava(ed, b, padrao, depois, aplicar, comentario, user)

    def _grava(self, ed, b, padrao, depois, aplicar, comentario, user, adaptado=False):
        b = Bloco.objects.get(pk=b.pk)
        novo, n = substituir(b.xml, padrao, depois)
        if not n or novo == b.xml:
            if adaptado:
                self.stdout.write(self.style.WARNING(
                    f"  adaptado #{b.pk}: trecho não encontrado; conferir à mão no site"))
            return
        self.stdout.write(f"  {'adaptado' if adaptado else b.procedencia} #{b.pk}: {n} troca(s)")
        if aplicar:
            with transaction.atomic():
                servicos.salvar_blocos(ed, [b.pk], [{"id": b.pk, "versao": b.versao, "xml": novo}], user,
                                       comentario, volume=b.volume_id, pagina=b.pagina)
