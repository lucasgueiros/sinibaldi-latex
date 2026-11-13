"""`{% static_v 'js/site.js' %}`: URL de `{% static %}` com `?v=<mtime>`, para o navegador não
reaproveitar uma cópia antiga do arquivo depois de um deploy/rebuild (o `static` puro não versiona)."""
from pathlib import Path

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_v(caminho):
    url = static(caminho)
    arquivo = finders.find(caminho)
    if arquivo:
        try:
            url += ("&" if "?" in url else "?") + "v=%x" % int(Path(arquivo).stat().st_mtime)
        except OSError:
            pass
    return url
