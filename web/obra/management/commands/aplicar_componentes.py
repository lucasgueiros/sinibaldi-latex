"""Converte nos componentes próprios: o sumário de cada capítulo (`<argument>`, obra/sumarios.py) e o
aparato do fim de cada volume (nó `anexo` com `anexo-titulo`/`indice`, obra/anexos.py).

Aplica na 1916 e depois nas derivadas (atualizada, nova; os blocos editados à mão nelas são pulados);
nas derivadas, os blocos resultantes voltam a apontar para os da 1916 e ficam `copia` quando o texto coincide."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from obra import anexos, leitura, servicos, servicos_nova, sumarios
from obra.models import Bloco, Edicao


class Command(BaseCommand):
    help = "Lista (e, com --aplicar, grava) a conversão dos sumários de capítulo e do aparato final."

    def add_arguments(self, p):
        p.add_argument("--aplicar", action="store_true", help="Grava (sem isso, só relata).")
        p.add_argument("--edicao", action="append", help="slug (repetível); padrão: 1916 e as derivadas")
        p.add_argument("--detalhe", action="store_true", help="mostra o XML resultante")

    def handle(self, *args, aplicar, edicao, detalhe, **opts):
        slugs = edicao or ["1916"] + [e.slug for e in Edicao.ordenadas(Edicao.objects.filter(tipo__in=Edicao.DERIVADAS))]
        nova = Edicao.objects.filter(slug="nova", tipo=Edicao.NOVA).first()
        ed16 = Edicao.objects.filter(slug="1916").first()
        if nova and ed16 and "nova" in slugs:
            # antes de converter a 1916 (que remove os marcos fantasmas, origem dos da nova)
            regioes = [a.blocos for a in anexos.detectar(ed16)]
            if regioes:
                if aplicar:
                    n = servicos_nova.reunir_anexos(nova, regioes)
                    self.stdout.write(f"nova: {n} bloco(s) do aparato final reunidos no fim da edição.")
                else:
                    self.stdout.write("nova: o aparato final será antes reunido no fim da edição "
                                      "(a reordenação de partes pode tê-lo espalhado).")
        for slug in slugs:
            ed = Edicao.objects.filter(slug=slug).first()
            if ed is None:
                raise CommandError(f"Edição '{slug}' não existe.")
            self.stdout.write(self.style.MIGRATE_HEADING(f"== {slug}"))
            self._edicao(ed, aplicar, detalhe)

    def _pular(self, ed, blocos):
        """Nas derivadas, não reescreve o que um editor já mexeu."""
        return ed.derivada and any(b.procedencia in (Bloco.ADAPTADO, Bloco.NOVO) for b in blocos)

    def _edicao(self, ed, aplicar, detalhe):
        arv = leitura.Arvore(ed)
        tocados = []
        n_sum = n_anexo = pulados = 0
        for a in sumarios.detectar(ed):
            xmls = sumarios.componente(a)
            if not xmls or (len(a.blocos) == 1 and xmls == [a.blocos[0].xml]):
                continue
            no = arv.cobrindo(a.blocos[0].ordem)
            if self._pular(ed, a.blocos):
                pulados += 1
                self.stdout.write(f"  pulado (editado na nova): {no.xml_id if no else '?'}")
                continue
            n_sum += 1
            self.stdout.write(f"  sumário {no.xml_id if no else '?'}: {len(a.blocos)} bloco(s) -> "
                              + " + ".join("head" if x.startswith("<head") else "argument" for x in xmls)
                              + (f" [título: {a.titulo_embutido}]" if xmls[0].startswith("<head") else ""))
            if detalhe:
                for x in xmls:
                    self.stdout.write(f"      {x}")
            if aplicar:
                novos = [{"id": None, "xml": x} for x in xmls[:-1]] + [{"id": a.blocos[0].pk, "xml": xmls[-1]}]
                r = servicos.salvar_blocos(ed, [b.pk for b in a.blocos], novos, None, sumarios.COMENTARIO,
                                           volume=a.blocos[0].volume_id, pagina=a.blocos[0].pagina)
                tocados += r.blocos
        for a in anexos.detectar(ed):
            novos = anexos.componente(a)
            marcos = sum(1 for b in a.blocos if b.tipo == Bloco.MARCO)
            if self._pular(ed, a.blocos):
                pulados += 1
                self.stdout.write(f"  pulado (editado na nova): anexo {a.tipo} do vol. {a.volume_numero}")
                continue
            n_anexo += 1
            tipos = {}
            for n in novos[2:]:
                t = ("indice" if 'type="indice"' in n["xml"] else "anexo-titulo" if 'type="anexo-titulo"' in n["xml"]
                     else "inalterado")
                tipos[t] = tipos.get(t, 0) + 1
            self.stdout.write(f"  anexo v{a.volume_numero}.{a.tipo}: {len(a.blocos)} bloco(s), {marcos} marco(s) "
                              f"fantasma removido(s); {tipos}")
            if aplicar:
                r = servicos.salvar_blocos(ed, [b.pk for b in a.blocos], novos, None, anexos.COMENTARIO,
                                           volume=a.blocos[0].volume_id, pagina=a.blocos[0].pagina)
                tocados += r.blocos
        self.stdout.write(f"  {n_sum} sumário(s), {n_anexo} anexo(s), {pulados} pulado(s).")
        if aplicar and ed.derivada and tocados:
            n = religar(ed, [b.pk for b in tocados])
            self.stdout.write(f"  {n} bloco(s) de {ed.slug} religados à 1916 como cópia.")
        if not aplicar:
            self.stdout.write("  (use --aplicar para gravar)")


@transaction.atomic
def religar(nova, pks):
    """Blocos da nova reescritos por este comando: `copia` quando o XML coincide com o da origem; os
    criados (sem origem) ganham como origem o bloco da 1916 equivalente — o que antecede a origem do
    bloco seguinte, se o XML for o mesmo."""
    ed16 = Edicao.objects.get(slug="1916")
    feitos = []
    for b in Bloco.objects.filter(pk__in=pks).select_related("origem").order_by("-ordem"):
        if b.origem_id is None:
            seg = (Bloco.objects.filter(edicao=nova, ordem__gt=b.ordem, origem__isnull=False)
                   .exclude(tipo=Bloco.CABECALHO).order_by("ordem").select_related("origem").first())
            if seg is None:
                continue
            cand = (Bloco.objects.filter(edicao=ed16, ordem__lt=seg.origem.ordem).exclude(tipo=Bloco.CABECALHO)
                    .order_by("-ordem").first())
            if cand is None or cand.xml != b.xml:
                continue
            b.origem = cand
        if b.origem.xml == b.xml:
            b.procedencia = Bloco.COPIA
            b.origem_versao_vista = b.origem.versao
            feitos.append(b)
    Bloco.objects.bulk_update(feitos, ["origem", "procedencia", "origem_versao_vista"])
    return len(feitos)
