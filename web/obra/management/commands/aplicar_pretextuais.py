"""Grava as peças pré-textuais (obra/pretextuais.py, `volN/pretextuais.json`) nas edições.

Substitui, em cada volume, os blocos do começo (folha de rosto, imprimatur, cartas, prefácio… tal como o OCR
os deixou) por nós `pretextual` com blocos tipados. Na 1916 e nas derivadas (atualizada, nova); as derivadas
com blocos editados à mão no pré-textual são puladas; os blocos novos delas ficam `copia` ligados aos da 1916.
Sem `--aplicar` só relata. Idempotente."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from obra import arvore, pretextuais, servicos
from obra.models import Bloco, Edicao, Volume


class Command(BaseCommand):
    help = "Lista (e, com --aplicar, grava) as peças pré-textuais de cada volume."

    def add_arguments(self, p):
        p.add_argument("--aplicar", action="store_true", help="Grava (sem isso, só relata).")
        p.add_argument("--edicao", action="append", help="slug (repetível); padrão: 1916 e as derivadas")
        p.add_argument("--volume", type=int, action="append", help="1 e/ou 2 (padrão: os dois)")
        p.add_argument("--dados", default=None, help="raiz dos volN/pretextuais.json (padrão: raiz do repositório)")
        p.add_argument("--detalhe", action="store_true")

    def handle(self, *args, aplicar, edicao, volume, dados, detalhe, **opts):
        raiz = Path(dados) if dados else Path(settings.BASE_DIR).parent
        vols = volume or [1, 2]
        arquivos = {}
        for n in vols:
            caminho = raiz / f"vol{n}" / "pretextuais.json"
            if not caminho.exists():
                raise CommandError(f"{caminho} não existe: rode tools/revisa_pretextuais.py --vol vol{n}")
            try:
                arquivos[n] = pretextuais.carregar(caminho)
            except ValueError as e:
                raise CommandError(f"vol{n}: {e}")
            erros = pretextuais.validar(arquivos[n])
            if erros:
                raise CommandError(f"vol{n}: esquema recusa as peças:\n  " + "\n  ".join(erros[:10]))
        ed16 = Edicao.objects.filter(slug="1916").first()
        slugs = edicao or ["1916"] + [e.slug for e in Edicao.ordenadas(Edicao.objects.filter(tipo__in=Edicao.DERIVADAS))]
        if "1916" not in slugs and ed16 is not None:
            slugs = ["1916"] + slugs      # as derivadas se ligam aos blocos da 1916: ela vem sempre primeiro
        for slug in slugs:
            ed = Edicao.objects.filter(slug=slug).first()
            if ed is None:
                raise CommandError(f"Edição '{slug}' não existe.")
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {slug}"))
            for n in vols:
                self._volume(ed, ed16, n, arquivos[n], aplicar, detalhe)
        if not aplicar:
            self.stdout.write("(use --aplicar para gravar)")

    def _volume(self, ed, ed16, n, dados, aplicar, detalhe):
        vol = Volume.objects.get(numero=n)
        xmls = pretextuais.blocos_do_volume(dados)
        atual = pretextuais.regiao(ed, vol.pk, dados["ate"])
        if [b.xml for b in atual] == xmls:
            self.stdout.write(f"  vol. {n}: já aplicado ({len(atual)} blocos).")
            return
        if ed.derivada and any(b.procedencia in (Bloco.ADAPTADO, Bloco.NOVO) for b in atual):
            self.stdout.write(f"  vol. {n}: pulado (blocos editados à mão na {ed.slug}).")
            return
        self.stdout.write(f"  vol. {n}: {len(atual)} bloco(s) do OCR -> {len(dados['pecas'])} peça(s), {len(xmls)} blocos")
        if detalhe:
            for x in xmls:
                self.stdout.write(f"      {x[:150]}")
        if not atual:
            raise CommandError(f"vol. {n}: não achei os blocos do pré-textual na edição {ed.slug}.")
        if not aplicar:
            return
        r = servicos.salvar_blocos(ed, [b.pk for b in atual], [{"id": None, "xml": x} for x in xmls], None,
                                   pretextuais.COMENTARIO, volume=vol.pk, pagina=atual[0].pagina)
        for b, pg in zip(r.blocos, pretextuais.paginas_do_volume(dados)):
            b.pagina = pg
        Bloco.objects.bulk_update(r.blocos, ["pagina"])
        arvore.reconstruir(ed)                      # páginas dos nós vêm dos blocos
        if ed.derivada and ed16 is not None:
            origens = pretextuais.regiao(ed16, vol.pk, dados["ate"])
            if len(origens) == len(r.blocos):
                novos = []
                for novo, origem in zip(r.blocos, origens):
                    novo.origem, novo.procedencia, novo.origem_versao_vista = origem, Bloco.COPIA, origem.versao
                    novos.append(novo)
                Bloco.objects.bulk_update(novos, ["origem", "procedencia", "origem_versao_vista"])
                self.stdout.write(f"    {len(novos)} bloco(s) ligados à 1916 como cópia.")
            else:
                self.stdout.write(self.style.WARNING(
                    f"    não religados à 1916: {len(r.blocos)} blocos aqui, {len(origens)} lá."))
