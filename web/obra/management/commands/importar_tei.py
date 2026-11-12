"""Importa volN/volN.<fonte>.xml para a edição diplomática "1916"."""
import csv
import time
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from lxml import etree

from obra import arvore, tei
from obra.models import Bloco, Edicao, Pagina, Revisao, Volume
from obra.models import PASSO_ORDEM

import uuid

VOLUMES = {
    1: ("Logica – Ontologia – Cosmologia", 1917),
    2: ("Anthropologia – Theodicea – Moral", 1916),
}
BASE_ORDEM = 10 ** 9  # volume N ocupa [N*BASE, (N+1)*BASE): permite reimportar um volume isolado


def localizar(diretorio, nome):
    for raiz in (Path(settings.SINIBALDI_DADOS), Path(settings.RAIZ_REPO)):
        p = raiz / diretorio / nome
        if p.is_file():
            return p
    return None


def ler_impressas(diretorio):
    p = localizar(diretorio, "paginas/paginas.tsv")
    if p is None:
        return {}
    with open(p, encoding="utf-8", newline="") as f:
        leitor = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        cab = next(leitor)
        i_id, i_imp = cab.index("id"), cab.index("impressa")
        return {r[i_id]: r[i_imp] for r in leitor if len(r) > i_imp}


class Command(BaseCommand):
    help = "Importa o TEI corrigido dos volumes para a edição diplomática (slug 1916)."

    def add_arguments(self, p):
        p.add_argument("--volume", type=int, nargs="+", default=[1, 2])
        p.add_argument("--fonte", default="corrigido", help="volN.<fonte>.xml (padrão: corrigido)")
        p.add_argument("--recriar", action="store_true", help="apaga os blocos do volume antes de importar")

    def handle(self, *args, volume, fonte, recriar, **opts):
        t0 = time.time()
        edicao, _ = Edicao.objects.get_or_create(slug="1916", defaults=dict(
            titulo="Edição diplomática (1916/17)", tipo=Edicao.DIPLOMATICA,
            descricao="Transcrição fiel da edição impressa (4.ª ed. do vol. 2, 1916; 5.ª do vol. 1, 1917)."))
        rel_total = tei.Relatorio()
        for num in volume:
            if num not in VOLUMES:
                raise CommandError(f"Volume desconhecido: {num}")
            self.importar(edicao, num, fonte, recriar, rel_total)
        n_nos = len(arvore.reconstruir(edicao))
        por_nivel = Counter(edicao.nos.values_list("nivel", flat=True))
        self.stdout.write("\n== Relatório ==")
        self.stdout.write(str(rel_total))
        self.stdout.write(f"Nós: {n_nos} " + ", ".join(f"{k}={v}" for k, v in por_nivel.items()))
        self.stdout.write(self.style.SUCCESS(f"Concluído em {time.time() - t0:.1f} s."))

    @transaction.atomic
    def importar(self, edicao, num, fonte, recriar, rel_total):
        titulo, ano = VOLUMES[num]
        dir_ = f"vol{num}"
        vol, _ = Volume.objects.update_or_create(numero=num, defaults=dict(titulo=titulo, ano=ano, diretorio=dir_))
        if Bloco.objects.filter(edicao=edicao, volume=vol).exists():
            if not recriar:
                raise CommandError(f"O volume {num} já foi importado; use --recriar para refazer.")
            Bloco.objects.filter(edicao=edicao, volume=vol).delete()
            Revisao.objects.filter(edicao=edicao, volume=vol, acao=Revisao.IMPORTAR).delete()
            Pagina.objects.filter(volume=vol).delete()
        fonte_xml = localizar(dir_, f"vol{num}.{fonte}.xml")
        if fonte_xml is None:
            raise CommandError(f"Não achei {dir_}/vol{num}.{fonte}.xml em {settings.SINIBALDI_DADOS} nem em {settings.RAIZ_REPO}.")
        self.stdout.write(f"Vol. {num}: lendo {fonte_xml}")
        arvore_xml = etree.parse(str(fonte_xml))
        rel = tei.Relatorio()
        dados = tei.achatar(arvore_xml, numero=num, relatorio=rel)
        base = num * BASE_ORDEM
        Bloco.objects.bulk_create([
            Bloco(edicao=edicao, ordem=base + i * PASSO_ORDEM, tipo=d.tipo, xml=d.xml, volume=vol, pagina=d.pagina,
                  procedencia=Bloco.COPIA)
            for i, d in enumerate(dados, 1)
        ], batch_size=1000)
        impressas = ler_impressas(dir_)
        paginas = [
            Pagina(volume=vol, seq=seq, arquivo=arq, impressa=impressas.get(arq, str(seq)))
            for seq, arq in sorted(rel.paginas.items())
        ]
        Pagina.objects.bulk_create(paginas, batch_size=1000)
        Revisao.objects.create(
            edicao=edicao, acao=Revisao.IMPORTAR, lote=uuid.uuid4(), volume=vol,
            comentario=f"Importação de {fonte_xml.name}: {len(dados)} blocos, {len(paginas)} páginas.")
        tipos = Counter(d.tipo for d in dados)
        self.stdout.write(f"  {len(dados)} blocos ({', '.join(f'{k}={v}' for k, v in tipos.items())}); "
                          f"{len(paginas)} páginas")
        rel_total.desembrulhados.update(rel.desembrulhados)
        rel_total.descartados.update(rel.descartados)
        rel_total.avisos.extend(f"vol. {num}: {a}" for a in rel.avisos)
