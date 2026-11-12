"""Área restrita: revisão da edição 1916/17 e telas da nova edição."""
from django.urls import path

from . import views_edicao as v

urlpatterns = [
    path("", v.painel, name="painel"),
    path("converter/", v.converter, name="converter"),
    path("historico/", v.historico, name="historico"),
    path("bloco/<int:pk>/historico/", v.historico_bloco, name="historico_bloco"),
    path("1916/vol/<int:numero>/", v.paginas, name="paginas"),
    path("1916/vol/<int:numero>/pag/<sint:seq>/", v.revisar, name="revisar"),
    path("1916/vol/<int:numero>/pag/<sint:seq>/gravar/", v.gravar, name="gravar"),
]
