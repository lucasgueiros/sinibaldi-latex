from django.urls import include, path, register_converter

from . import scans

app_name = "obra"


class InteiroComSinal:
    """Inteiro possivelmente negativo (as páginas preliminares do vol. 1 têm n < 0)."""
    regex = r"-?[0-9]+"

    def to_python(self, valor):
        return int(valor)

    def to_url(self, valor):
        return str(int(valor))


register_converter(InteiroComSinal, "sint")

urlpatterns = [
    path("scan/<int:volume>/<sint:seq>.png", scans.scan, name="scan"),
    path("edicao-colaborativa/", include("obra.urls_edicao")),
    path("", include("obra.urls_publico")),
]
