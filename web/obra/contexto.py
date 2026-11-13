"""Context processor: as edições que aparecem no menu do cabeçalho (só as públicas, salvo para editores)."""
from django.utils.functional import SimpleLazyObject

from .models import Edicao


def edicoes(request):
    user = getattr(request, "user", None)
    # preguiçoso e memorizado: uma consulta por requisição, só se o template usar
    return {"edicoes_menu": SimpleLazyObject(lambda: Edicao.visiveis(user))}
