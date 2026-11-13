"""Acesso às imagens do scan (git-ignoradas; vivem sob `settings.SINIBALDI_DADOS`)."""
import os
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404

from .models import Pagina, Volume


def caminho_scan(volume, seq):
    """`SINIBALDI_DADOS/<diretorio>/paginas/NNNN.png` (Path) ou None.

    `volume`: instância de Volume ou o número do volume. `seq`: valor de <pb n>."""
    if not isinstance(volume, Volume):
        volume = Volume.objects.filter(numero=volume).first()
        if volume is None:
            return None
    arquivo = (Pagina.objects.filter(volume=volume, seq=seq).values_list("arquivo", flat=True).first()
               or (f"{seq:04d}" if seq >= 0 else ""))
    if not arquivo:
        return None
    caminho = Path(settings.SINIBALDI_DADOS) / volume.diretorio / "paginas" / f"{arquivo}.png"
    return caminho if caminho.is_file() else None


def scan(request, volume, seq):
    """Serve o PNG da página (cache longo) ou 404."""
    caminho = caminho_scan(volume, seq)
    if caminho is None:
        raise Http404("Scan não encontrado.")
    resp = FileResponse(open(caminho, "rb"), content_type="image/png")
    resp["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


LARGURAS_SCAN = (1000, 1600)


def _gera_jpg(origem, destino, largura):
    from PIL import Image
    with Image.open(origem) as im:
        im.load()
        cinza = im.mode in ("L", "1", "LA") or (im.mode in ("RGB", "P", "RGBA") and _eh_cinza(im))
        im = im.convert("L" if cinza else "RGB")
        if im.width > largura:
            im = im.resize((largura, round(im.height * largura / im.width)), Image.LANCZOS)
        destino.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=destino.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                im.save(f, "JPEG", quality=80, optimize=True)
            os.replace(tmp, destino)  # atômico
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _eh_cinza(im):
    from PIL import ImageChops
    rgb = im.convert("RGB")
    r, g, b = rgb.split()
    return not (ImageChops.difference(r, g).getbbox() or ImageChops.difference(g, b).getbbox())


def scan_jpg(request, volume, seq):
    """JPEG reduzido (`?l=1000|1600`) em cache sob `SINIBALDI_CACHE/scans/`, gerado na 1ª requisição."""
    try:
        largura = int(request.GET.get("l", ""))
    except ValueError:
        raise Http404("Largura inválida.")
    if largura not in LARGURAS_SCAN:
        raise Http404("Largura não permitida.")
    caminho = caminho_scan(volume, seq)
    if caminho is None:
        raise Http404("Scan não encontrado.")
    destino = Path(settings.SINIBALDI_CACHE) / "scans" / f"v{volume}_{caminho.stem}_{largura}.jpg"
    if not destino.is_file() or destino.stat().st_mtime < caminho.stat().st_mtime:
        _gera_jpg(caminho, destino, largura)
    resp = FileResponse(open(destino, "rb"), content_type="image/jpeg")
    resp["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


# ------------------------------------------------------------------ gravuras
_RE_XYWH = re.compile(r"^(\d+),(\d+),(\d+),(\d+)$")
LIMITE_LADO_GRAVURA = 20000


def dimensoes_scan(volume, seq):
    """(largura, altura) em pixels do PNG original da página, ou None (lê só o cabeçalho)."""
    caminho = caminho_scan(volume, seq)
    if caminho is None:
        return None
    from PIL import Image
    try:
        with Image.open(caminho) as im:
            return im.size
    except OSError:
        return None


def recorte_gravura(volume, arquivo, caixa):
    """PNG do recorte `caixa` = (x, y, l, a) da página `arquivo` do volume (número), em cache sob
    `SINIBALDI_CACHE/gravuras/`. Caixa além da borda é aparada. Path ou None (sem scan / caixa vazia)."""
    vol = Volume.objects.filter(numero=volume).first()
    if vol is None or not re.fullmatch(r"[A-Za-z0-9_-]+", arquivo or ""):
        return None
    origem = Path(settings.SINIBALDI_DADOS) / vol.diretorio / "paginas" / f"{arquivo}.png"
    if not origem.is_file():
        return None
    x, y, l, a = caixa
    destino = Path(settings.SINIBALDI_CACHE) / "gravuras" / f"v{volume}_{arquivo}_{x}_{y}_{l}_{a}.png"
    if destino.is_file() and destino.stat().st_mtime >= origem.stat().st_mtime:
        return destino
    from PIL import Image
    with Image.open(origem) as im:
        im.load()
        x2, y2 = min(x + l, im.width), min(y + a, im.height)
        if x >= x2 or y >= y2:
            return None
        rec = im.crop((x, y, x2, y2))
        if rec.mode not in ("L", "RGB"):
            rec = rec.convert("RGB")
        if rec.mode == "RGB" and _eh_cinza(rec):
            rec = rec.convert("L")
        dpi = im.info.get("dpi")
        destino.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=destino.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                rec.save(f, "PNG", optimize=True, **({"dpi": dpi} if dpi else {}))
            os.replace(tmp, destino)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return destino


def gravura(request, volume, arquivo, xywh):
    """Recorte de uma gravura do fac-símile (`/gravura/<vol>/<arquivo>/<x,y,l,a>.png`), cache longo."""
    m = _RE_XYWH.match(xywh)
    if not m:
        raise Http404("Caixa inválida.")
    caixa = tuple(int(v) for v in m.groups())
    if not (caixa[2] and caixa[3]) or max(caixa) > LIMITE_LADO_GRAVURA:
        raise Http404("Caixa inválida.")
    caminho = recorte_gravura(volume, arquivo, caixa)
    if caminho is None:
        raise Http404("Gravura não encontrada.")
    resp = FileResponse(open(caminho, "rb"), content_type="image/png")
    resp["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp
