"""Área restrita: revisão da edição 1916/17 e telas das edições derivadas (atualizada, nova)."""
from django.urls import path

from . import views_edicao as v
from . import views_nova as n
from . import views_slides as sl
from . import views_sugestoes as sg

urlpatterns = [
    path("", v.painel, name="painel"),
    path("converter/", v.converter, name="converter"),
    path("historico/", v.historico, name="historico"),
    path("bloco/<int:pk>/historico/", v.historico_bloco, name="historico_bloco"),
    path("sugestoes/", sg.lista, name="sugestoes"),
    path("sugestoes/<int:pk>/acao/", sg.acao, name="sugestao_acao"),
    path("1916/vol/<int:numero>/", v.paginas, name="paginas"),
    path("1916/vol/<int:numero>/pag/<sint:seq>/", v.revisar, name="revisar"),
    path("1916/vol/<int:numero>/pag/<sint:seq>/gravar/", v.gravar, name="gravar"),
    # slides
    path("slides/", sl.lista, name="slides_lista"),
    path("slides/<slug:slug>/<str:xml_id>/", sl.editor, name="slides_editor"),
    path("slides/<slug:slug>/<str:xml_id>/salvar/", sl.salvar, name="slides_salvar"),
    path("slides/<slug:slug>/<str:xml_id>/regenerar/", sl.regenerar, name="slides_regenerar"),
    path("slides/<slug:slug>/<str:xml_id>/descartar/", sl.descartar, name="slides_descartar"),
    path("slides/<slug:slug>/<str:xml_id>/restaurar/", sl.restaurar, name="slides_restaurar"),
    # edições derivadas da 1916 (atualizada, nova): por último, pois <slug>/ casaria com as rotas acima
    path("<slug:slug>/", n.estrutura, name="nova_estrutura"),
    path("<slug:slug>/partes/aplicar/", n.aplicar_ordem, name="nova_aplicar_ordem"),
    path("<slug:slug>/no/<str:xml_id>/", n.editar_no, name="nova_no"),
    path("<slug:slug>/no/<str:xml_id>/acao/", n.acao_no, name="nova_no_acao"),
    path("<slug:slug>/no/<str:xml_id>/mover/", n.mover, name="nova_mover"),
    path("<slug:slug>/trecho/<int:ordem_ini>/", n.editar_trecho, name="nova_trecho"),
    path("<slug:slug>/gravar/", n.gravar, name="nova_gravar"),
    path("<slug:slug>/bloco/acao/", n.acao_bloco, name="nova_bloco_acao"),
    path("<slug:slug>/pendencias/", n.pendencias, name="nova_pendencias"),
    path("<slug:slug>/pendencias/acao/", n.acao_pendencias, name="nova_pendencias_acao"),
    path("<slug:slug>/visibilidade/", v.visibilidade, name="visibilidade"),
]
