"""Parte pública: navegação e downloads."""
from django.urls import path

from . import views_publico as v

urlpatterns = [
    path("", v.inicio, name="inicio"),
    path("sobre/", v.sobre, name="sobre"),
    path("edicao/<slug:slug>/", v.edicao, name="edicao"),
    path("edicao/<slug:slug>/busca/", v.busca, name="busca"),
    path("edicao/<slug:slug>/volume/<int:numero>/baixar/xml/", v.baixar_volume, name="baixar_volume"),
    path("edicao/<slug:slug>/<str:xml_id>/", v.no, name="no"),
    path("edicao/<slug:slug>/<str:xml_id>/baixar/<str:formato>/", v.baixar, name="baixar"),
    path("fac-simile/<int:volume>/<sint:seq>/", v.facsimile, name="facsimile"),
]
