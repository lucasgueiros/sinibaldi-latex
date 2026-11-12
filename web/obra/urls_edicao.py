"""Área restrita: revisão da edição 1916/17 e telas da nova edição."""
from django.urls import path

from . import views_edicao as v
from . import views_nova as n

urlpatterns = [
    path("", v.painel, name="painel"),
    path("converter/", v.converter, name="converter"),
    path("historico/", v.historico, name="historico"),
    path("bloco/<int:pk>/historico/", v.historico_bloco, name="historico_bloco"),
    path("1916/vol/<int:numero>/", v.paginas, name="paginas"),
    path("1916/vol/<int:numero>/pag/<sint:seq>/", v.revisar, name="revisar"),
    path("1916/vol/<int:numero>/pag/<sint:seq>/gravar/", v.gravar, name="gravar"),
    # nova edição
    path("nova/", n.estrutura, name="nova_estrutura"),
    path("nova/partes/aplicar/", n.aplicar_ordem, name="nova_aplicar_ordem"),
    path("nova/no/<str:xml_id>/", n.editar_no, name="nova_no"),
    path("nova/no/<str:xml_id>/acao/", n.acao_no, name="nova_no_acao"),
    path("nova/no/<str:xml_id>/mover/", n.mover, name="nova_mover"),
    path("nova/trecho/<int:ordem_ini>/", n.editar_trecho, name="nova_trecho"),
    path("nova/gravar/", n.gravar, name="nova_gravar"),
    path("nova/bloco/acao/", n.acao_bloco, name="nova_bloco_acao"),
    path("nova/pendencias/", n.pendencias, name="nova_pendencias"),
    path("nova/pendencias/acao/", n.acao_pendencias, name="nova_pendencias_acao"),
]
