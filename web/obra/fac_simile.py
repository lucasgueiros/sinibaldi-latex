"""Fac-símile em PDF: páginas do scan original, recortadas sem recomprimir.

O scan de cada volume é um PDF 2-up (`vol1.pdf`, `vol2/vol2.pdf`: duas páginas do livro por folha). Uma vez
por volume, `mutool poster -x 2` divide as folhas e `mutool merge` as põe na ordem do `manifesto.tsv`
(`volN/paginas/manifesto.tsv`: id, impressa, folha, metade, pdf_idx), gerando em cache
`SINIBALDI_CACHE/fac-simile/vN-<assinatura>.pdf`, cuja página k é a de `pdf_idx = k`. O PDF de um trecho
é um `mutool merge` das páginas dele a partir desse arquivo (instantâneo).

O poster corta na orientação visual, mas a ordem das metades depende do `/Rotate` da folha: sem rotação
(vol. 1) sai esquerda, direita; com `/Rotate 90` (vol. 2) sai direita, esquerda. Conferido contra as PNGs.

Nada aqui toca o banco: as funções que rodam em segundo plano (`preparar_*`) só recebem caminhos e índices.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

from . import exportacao
from .models import Bloco, Pagina, Volume

TIMEOUT = 600


class ErroFacSimile(exportacao.ErroExportacao):
    pass


# --------------------------------------------------------------------------- fontes
def scan_original(volume):
    """PDF original (2-up) do volume sob `SINIBALDI_DADOS`, ou None."""
    base = Path(settings.SINIBALDI_DADOS)
    d = volume.diretorio
    for c in (base / d / f"{d}.pdf", base / f"{d}.pdf"):
        if c.is_file():
            return c
    return None


def _caminho_manifesto(volume):
    return Path(settings.SINIBALDI_DADOS) / volume.diretorio / "paginas" / "manifesto.tsv"


def disponivel(volume):
    return (volume is not None and shutil.which("mutool") is not None and scan_original(volume) is not None
            and _caminho_manifesto(volume).is_file())


def manifesto(volume):
    """{id: pdf_idx} e o total de linhas, lidos de `manifesto.tsv`."""
    idx = {}
    with open(_caminho_manifesto(volume), encoding="utf-8") as f:
        next(f, None)
        for linha in f:
            c = linha.rstrip("\n").split("\t")
            if len(c) >= 5 and c[4].isdigit():
                idx[c[0]] = int(c[4])
    return idx


def _assinatura(origem):
    st = origem.stat()
    return hashlib.sha1(f"{origem.name}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:12]


def _dir():
    d = exportacao.dir_cache() / "fac-simile"
    d.mkdir(parents=True, exist_ok=True)
    return d


def caminho_volume(volume):
    """Onde fica (ou ficará) o PDF paginado do volume inteiro."""
    origem = scan_original(volume)
    if origem is None:
        raise ErroFacSimile("O scan original deste volume não está disponível nesta instalação.")
    return _dir() / f"v{volume.numero}-{_assinatura(origem)}.pdf"


def tamanho_aproximado(volume):
    """Tamanho (bytes) do PDF do volume: o do pronto ou, antes de gerar, o do original (quase igual)."""
    try:
        alvo = caminho_volume(volume)
    except ErroFacSimile:
        return None
    return (alvo if alvo.is_file() else scan_original(volume)).stat().st_size


# ------------------------------------------------------------------------- mutool
def _mutool(args, timeout=TIMEOUT):
    try:
        r = subprocess.run(["mutool", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ErroFacSimile("A montagem do fac-símile passou do tempo limite.")
    if r.returncode != 0:
        raise ErroFacSimile("Não foi possível montar o fac-símile em PDF.")
    return r.stdout


def _rotacoes(origem):
    """Lista do /Rotate de cada folha do original (`mutool pages` omite o elemento quando é 0)."""
    saida = _mutool(["pages", str(origem)])
    rot = []
    for pagina in re.split(r"<page\b", saida)[1:]:
        m = re.search(r'<Rotate v="(-?\d+)"', pagina)
        rot.append(int(m.group(1)) % 360 if m else 0)
    if not rot:
        raise ErroFacSimile("Não consegui ler as folhas do scan original.")
    return rot


def _faixas(indices):
    """[1,2,3,7,9,10] -> '1-3,7,9-10' (para o `mutool merge`)."""
    partes, ini, ant = [], None, None
    for i in indices:
        if ini is None:
            ini = ant = i
        elif i == ant + 1:
            ant = i
        else:
            partes.append(f"{ini}-{ant}" if ant != ini else str(ini))
            ini = ant = i
    if ini is not None:
        partes.append(f"{ini}-{ant}" if ant != ini else str(ini))
    return ",".join(partes)


def preparar_volume(origem, destino, total):
    """Gera `destino` (volume paginado, página k = pdf_idx k) a partir do original 2-up. Idempotente."""
    destino = Path(destino)
    with exportacao._Trava(destino.with_suffix(".lock")):
        if destino.is_file() and destino.stat().st_size:
            return destino
        rot = _rotacoes(origem)
        ordem = []  # índice no saída do poster de cada pdf_idx 1..total
        for folha, r in enumerate(rot, 1):
            a, b = 2 * folha - 1, 2 * folha
            ordem.extend((a, b) if r in (0, 270) else (b, a))
        ordem = ordem[:total] if total else ordem
        with tempfile.TemporaryDirectory(dir=destino.parent, prefix="tmp-") as tmp:
            dividido = Path(tmp) / "dividido.pdf"
            _mutool(["poster", "-x", "2", str(origem), str(dividido)])
            parcial = Path(tmp) / "final.pdf"
            _mutool(["merge", "-o", str(parcial), str(dividido), ",".join(map(str, ordem))])
            os.replace(parcial, destino)
    return destino


def preparar_trecho(partes, destino):
    """`partes` = [(origem, destino_volume, total, [pdf_idx…]), …] -> PDF com essas páginas, em ordem."""
    destino = Path(destino)
    with exportacao._Trava(destino.with_suffix(".lock")):
        if destino.is_file() and destino.stat().st_size:
            return destino
        args = ["merge", "-o", None]
        for origem, dvol, total, indices in partes:
            args += [str(preparar_volume(origem, dvol, total)), _faixas(indices)]
        with tempfile.TemporaryDirectory(dir=destino.parent, prefix="tmp-") as tmp:
            parcial = Path(tmp) / "final.pdf"
            args[2] = str(parcial)
            _mutool(args)
            os.replace(parcial, destino)
    return destino


# --------------------------------------------------------- planejamento (usa o banco)
_PB = re.compile(r'<pb\b[^>]*\bn="(-?\d+)"')


def paginas_do_no(no):
    """[(Volume, [seq…])] das páginas em que o nó tem texto, na ordem do nó (uma entrada por volume)."""
    por_vol = {}
    for vol_id, pagina, xml in exportacao.blocos_do_no(no).exclude(tipo=Bloco.CABECALHO).values_list(
            "volume_id", "pagina", "xml"):
        if vol_id is None or pagina is None:
            continue
        s = por_vol.setdefault(vol_id, set())
        s.add(pagina)
        s.update(int(n) for n in _PB.findall(xml))
    vols = Volume.objects.in_bulk(list(por_vol))
    return [(vols[v], sorted(s)) for v, s in por_vol.items() if v in vols]


def plano_volume(volume):
    """(origem, destino, total) do volume inteiro. Levanta ErroFacSimile."""
    if not disponivel(volume):
        raise ErroFacSimile("O fac-símile deste volume não está disponível nesta instalação.")
    return scan_original(volume), caminho_volume(volume), len(manifesto(volume))


def plano_trecho(no):
    """(partes, destino) para `preparar_trecho`. Levanta ErroFacSimile."""
    grupos = paginas_do_no(no)
    if not grupos:
        raise ErroFacSimile("Este trecho não tem páginas do scan associadas.")
    partes, chave = [], []
    for vol, seqs in grupos:
        origem, dvol, total = plano_volume(vol)
        idx = manifesto(vol)
        arq = dict(Pagina.objects.filter(volume=vol, seq__in=seqs).values_list("seq", "arquivo"))
        indices = []
        for s in seqs:
            a = arq.get(s) or (f"{s:04d}" if s >= 0 else "")
            if a in idx:
                indices.append(idx[a])
        if indices:
            indices = sorted(set(indices))
            partes.append((origem, dvol, total, indices))
            chave.append(f"{dvol.name}:{_faixas(indices)}")
    if not partes:
        raise ErroFacSimile("Não achei as páginas deste trecho no scan.")
    nome = hashlib.sha1("|".join(chave).encode()).hexdigest()[:16]
    return partes, _dir() / f"trecho-{nome}.pdf"
