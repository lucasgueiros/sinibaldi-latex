"""Acesso às imagens do scan (git-ignoradas; vivem sob `settings.SINIBALDI_DADOS`)."""
import os
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
