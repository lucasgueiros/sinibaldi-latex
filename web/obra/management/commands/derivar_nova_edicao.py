"""Cria a edição "nova" a partir da diplomática, reordenando as PARTES."""
import re
import unicodedata

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from lxml import etree

from obra import arvore
from obra.models import PASSO_ORDEM, Bloco, Edicao

ORDEM_PARTES = ["Lógica", "Cosmologia", "Antropologia", "Ontologia", "Teodiceia", "Moral"]
PALAVRAS = {
    "logica": 0, "cosmologia": 1, "anthropologia": 2, "antropologia": 2, "ontologia": 3,
    "theodicea": 4, "teodiceia": 4, "theodiceia": 4, "teodicea": 4, "moral": 5, "ethica": 5, "etica": 5,
}


def normalizar(txt):
    s = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]+", " ", s)


def classificar(textos):
    """Posição da parte na ordem nova a partir dos títulos, ou None."""
    for palavra in normalizar(" ".join(textos)).split():
        if palavra in PALAVRAS:
            return PALAVRAS[palavra]
    return None


def texto(xml):
    return "".join(etree.fromstring(xml.encode("utf-8")).itertext())


class Command(BaseCommand):
    help = "Deriva a edição 'nova' da '1916' (cópia dos blocos, sem cabeçalhos correntes), reordenando as partes."

    def add_arguments(self, p):
        p.add_argument("--recriar", action="store_true")

    @transaction.atomic
    def handle(self, *args, recriar, **opts):
        try:
            orig = Edicao.objects.get(slug="1916")
        except Edicao.DoesNotExist:
            raise CommandError("Importe a edição 1916 antes (importar_tei).")
        nova, criada = Edicao.objects.get_or_create(slug="nova", defaults=dict(
            titulo="Nova edição", tipo=Edicao.NOVA,
            descricao="Edição revista e reorganizada; cada bloco aponta para a origem na edição de 1916."))
        if nova.blocos.exists():
            if not recriar:
                raise CommandError("A edição 'nova' já tem blocos; use --recriar.")
            nova.blocos.all().delete()
            nova.nos.all().delete()

        blocos = list(orig.blocos.exclude(tipo=Bloco.CABECALHO).order_by("ordem"))
        # --- segmentos: prelúdio de cada volume + um por <milestone unit="parte">
        segmentos = []  # dicts: blocos, rank, rotulo, vol, prelude
        for i, b in enumerate(blocos):
            novo_vol = not segmentos or segmentos[-1]["vol"] != b.volume_id
            e_parte = False
            if b.tipo == Bloco.MARCO:
                e_parte = etree.fromstring(b.xml.encode("utf-8")).get("unit") == "parte"
            if novo_vol or e_parte:
                titulos = []
                if e_parte:
                    for c in blocos[i + 1:i + 6]:
                        if c.tipo == Bloco.TITULO:
                            titulos.append(texto(c.xml))
                        elif c.tipo != Bloco.CABECALHO:
                            break
                seg = dict(blocos=[], vol=b.volume_id, prelude=not e_parte, titulos=titulos,
                           rank=classificar(titulos) if e_parte else None)
                segmentos.append(seg)
            segmentos[-1]["blocos"].append(b)

        avisos = []
        anterior = None
        for s in segmentos:
            if s["prelude"]:
                s["chave"] = -1
                if s["blocos"]:
                    avisos.append(f"Prelúdio do volume pk={s['blocos'][0].volume_id} ({len(s['blocos'])} blocos) "
                                  "mantido no início, na ordem original (sem marco de parte antes dele; no vol. 1 "
                                  "isso inclui Lógica e Ontologia, ainda não separadas).")
                continue
            if s["rank"] is None:
                s["chave"] = anterior if anterior is not None else -1
                avisos.append(f"Parte não classificada {' / '.join(s['titulos'])!r} "
                              f"({len(s['blocos'])} blocos): segue a anterior.")
            else:
                s["chave"] = s["rank"]
                anterior = s["rank"]
        ordenados = sorted(range(len(segmentos)), key=lambda i: (segmentos[i]["chave"], i))
        vistos = {}
        for i in ordenados:
            s = segmentos[i]
            if s["rank"] is not None:
                vistos.setdefault(s["rank"], []).append(i)
        for r, lst in vistos.items():
            if len(lst) > 1:
                avisos.append(f"{ORDEM_PARTES[r]}: {len(lst)} segmentos (os extras podem ser índices/sumários do OCR).")

        novos, pos = [], 0
        for i in ordenados:
            for b in segmentos[i]["blocos"]:
                pos += 1
                novos.append(Bloco(
                    edicao=nova, ordem=pos * PASSO_ORDEM, tipo=b.tipo, xml=b.xml, volume_id=b.volume_id,
                    pagina=b.pagina, origem=b, procedencia=Bloco.COPIA))
        Bloco.objects.bulk_create(novos, batch_size=1000)
        arvore.reconstruir(nova)

        self.stdout.write(f"Edição 'nova': {len(novos)} blocos em {len(segmentos)} segmentos.")
        self.stdout.write("Ordem das partes:")
        for i in ordenados:
            s = segmentos[i]
            nome = ORDEM_PARTES[s["rank"]] if s["rank"] is not None else ("(prelúdio)" if s["prelude"] else "(?)")
            self.stdout.write(f"  {nome:14} vol.{s['blocos'][0].volume_id} {len(s['blocos']):5} blocos  "
                              f"{' / '.join(s['titulos'])}")
        for a in avisos:
            self.stdout.write(self.style.WARNING("Aviso: " + a))
