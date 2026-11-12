"""Acesso às imagens do scan (git-ignoradas; vivem sob `settings.SINIBALDI_DADOS`)."""
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
