"""Aplica o componente "asterisco" (`<anchor type="asterisco"/>`, obra/asteriscos.py) sem regerar nada.

Na 1916:
  * todo parágrafo que é só um `*` solto vira o componente;
  * com `--lista`, insere o asterisco logo depois de um trecho (no corpo ou numa nota). TSV com
    cabeçalho: `volume<TAB>pagina<TAB>depois_de<TAB>nota` — `pagina` é a impressa (como no site);
    `depois_de`, o texto que antecede o asterisco (único naquela página); `nota`, o número da nota
    quando o asterisco está dentro dela (vazio = corpo).
Na nova: as cópias dos blocos alterados são atualizadas (servicos_nova.atualizar_copias); os blocos
`adaptado` (decisão do editor) recebem a mesma inserção quando o trecho ainda existe neles, e os
demais são listados para o editor tratar à mão."""
import csv
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from obra import asteriscos, servicos, servicos_nova
from obra.models import Bloco, Edicao, Pagina, Volume


class Command(BaseCommand):
    help = "Insere o componente asterisco (1916 e derivadas) a partir de `*` soltos e/ou de uma lista TSV."

    def add_arguments(self, p):
        p.add_argument("--aplicar", action="store_true", help="Grava (sem isso, só relata).")
        p.add_argument("--lista", help="TSV: volume, pagina, depois_de, nota (cabeçalho na 1ª linha).")
        p.add_argument("--sem-solitarios", action="store_true", help="Não converte os `<p>*</p>` soltos.")

    def handle(self, *args, aplicar, lista, sem_solitarios, **opts):
        ed16 = Edicao.objects.filter(slug="1916").first()
        if ed16 is None:
            raise CommandError("A edição '1916' não existe.")
        derivadas = Edicao.ordenadas(Edicao.objects.filter(tipo__in=Edicao.DERIVADAS))
        # pk do bloco da 1916 -> [(operação xml -> (xml_novo, motivo), descrição)]
        plano = defaultdict(list)
        if not sem_solitarios:
            for b in Bloco.objects.filter(edicao=ed16, tipo=Bloco.PARAGRAFO, xml__contains="*"):
                if asteriscos.eh_solto(b.xml):
                    plano[b.pk].append((self._op_solto, "`*` solto"))
        pendencias = []
        if lista:
            for linha in self._ler(lista):
                alvo, motivo = self._localizar(ed16, linha)
                if alvo is None:
                    pendencias.append((linha, motivo))
                    continue
                plano[alvo.pk].append((self._op(linha), self._rotulo(linha)))

        self.stdout.write(self.style.MIGRATE_HEADING("== 1916"))
        alterados = self._executar(ed16, plano, aplicar)
        for linha, motivo in pendencias:
            self.stdout.write(self.style.WARNING(f"  pendente: {self._rotulo(linha)} — {motivo}"))

        for nova in derivadas if alterados else []:
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {nova.slug}"))
            self._nova(nova, plano, alterados, aplicar)
        if not aplicar:
            self.stdout.write("(use --aplicar para gravar)")

    # ---------------------------------------------------------------- entrada
    def _ler(self, caminho):
        try:
            with open(caminho, newline="", encoding="utf-8") as f:
                linhas = list(csv.DictReader(f, delimiter="\t"))
        except OSError as e:
            raise CommandError(f"Não consegui ler {caminho}: {e}")
        for col in ("volume", "pagina", "depois_de"):
            if linhas and col not in linhas[0]:
                raise CommandError(f"A lista precisa da coluna '{col}'.")
        return linhas

    @staticmethod
    def _rotulo(linha):
        nota = f" (nota {linha['nota']})" if (linha.get("nota") or "").strip() else ""
        return f"vol. {linha['volume']} p. {linha['pagina']}{nota} depois de «{linha['depois_de']}»"

    @staticmethod
    def _op_solto(xml):
        novo = asteriscos.converter_solto(xml)
        return novo, (None if novo else "não é um `*` solto")

    @staticmethod
    def _op(linha):
        trecho, nota = linha["depois_de"], (linha.get("nota") or "").strip() or None
        return lambda x: asteriscos.inserir_apos(x, trecho, nota)

    def _localizar(self, ed, linha):
        """Bloco da edição onde o trecho aparece uma única vez, na página impressa indicada (ou na
        anterior, se o parágrafo começou lá)."""
        try:
            vol = Volume.objects.filter(numero=int(linha["volume"])).first()
        except ValueError:
            return None, "volume inválido"
        if vol is None:
            return None, "volume inexistente"
        pag = Pagina.objects.filter(volume=vol, impressa=linha["pagina"].strip()).first()
        if pag is None:
            return None, "página impressa inexistente"
        op = self._op(linha)
        achados = []
        for b in Bloco.objects.filter(edicao=ed, volume=vol, pagina__in=[pag.seq - 1, pag.seq],
                                      tipo=Bloco.PARAGRAFO).order_by("ordem"):
            novo, _ = op(b.xml)
            if novo is not None:
                achados.append(b)
        if not achados:
            return None, "trecho não encontrado (ou ambíguo) nessa página"
        if len(achados) > 1:
            return None, f"trecho presente em {len(achados)} blocos"
        return achados[0], None

    # ----------------------------------------------------------------- gravação
    def _executar(self, ed, plano, aplicar):
        """Aplica as operações de cada bloco em sequência. Retorna {pk: (xml_antes, xml_depois)}."""
        alterados = {}
        for b in Bloco.objects.filter(pk__in=plano).order_by("ordem"):
            xml = b.xml
            for op, rotulo in plano[b.pk]:
                novo, motivo = op(xml)
                if novo is None:
                    self.stdout.write(self.style.WARNING(f"  bloco #{b.pk} pulado: {rotulo} — {motivo}"))
                    continue
                self.stdout.write(f"  bloco #{b.pk} (p. {b.pagina}): {rotulo}")
                xml = novo
            if xml != b.xml:
                alterados[b.pk] = (b.xml, xml)
                if aplicar:
                    servicos.salvar_blocos(ed, [b.pk], [{"id": b.pk, "versao": b.versao, "xml": xml}], None,
                                           asteriscos.COMENTARIO, volume=b.volume_id, pagina=b.pagina)
        self.stdout.write(f"  {len(alterados)} bloco(s) alterado(s).")
        return alterados

    def _nova(self, nova, plano, alterados, aplicar):
        derivados = list(Bloco.objects.filter(edicao=nova, origem_id__in=alterados).select_related("origem"))
        copias = [b for b in derivados if b.procedencia == Bloco.COPIA]
        adaptados = [b for b in derivados if b.procedencia == Bloco.ADAPTADO]
        self.stdout.write(f"  {len(copias)} cópia(s) a atualizar, {len(adaptados)} adaptado(s) a conferir.")
        if copias and aplicar:
            servicos_nova.atualizar_copias(nova, ids=[b.pk for b in copias])
        for b in adaptados:
            xml = b.xml
            # a origem só mudou por nossa causa se o editor já tinha conferido a versão anterior
            so_nos = b.origem_versao_vista is not None and b.origem_versao_vista == b.origem.versao - 1
            for op, rotulo in plano[b.origem_id]:
                novo, motivo = op(xml)
                if novo is None:
                    self.stdout.write(self.style.WARNING(
                        f"  adaptado #{b.pk}: {rotulo} — {motivo}; inserir à mão no site"))
                    so_nos = False
                    continue
                self.stdout.write(f"  adaptado #{b.pk}: {rotulo}")
                xml = novo
            if xml != b.xml and aplicar:
                with transaction.atomic():
                    servicos.salvar_blocos(nova, [b.pk], [{"id": b.pk, "versao": b.versao, "xml": xml}], None,
                                           asteriscos.COMENTARIO, volume=b.volume_id, pagina=b.pagina)
                    if so_nos:
                        servicos_nova.marcar_origem_vista(nova, [b.pk])
