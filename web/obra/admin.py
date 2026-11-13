from django.contrib import admin

from .models import (Apresentacao, ApresentacaoRevisao, Bloco, Citacao, Edicao, Fonte, No, Pagina, Revisao, Sugestao,
                     Volume)


@admin.register(Edicao)
class EdicaoAdmin(admin.ModelAdmin):
    list_display = ("slug", "titulo", "tipo", "publica")
    list_editable = ("publica",)
    list_filter = ("tipo", "publica")


@admin.register(Volume)
class VolumeAdmin(admin.ModelAdmin):
    list_display = ("numero", "titulo", "ano", "diretorio")


@admin.register(Pagina)
class PaginaAdmin(admin.ModelAdmin):
    list_display = ("volume", "seq", "impressa", "estado", "revisada_por", "revisada_em")
    list_filter = ("volume", "estado")
    search_fields = ("impressa",)
    raw_id_fields = ("revisada_por",)


@admin.register(Bloco)
class BlocoAdmin(admin.ModelAdmin):
    list_display = ("pk", "edicao", "ordem", "tipo", "volume", "pagina", "procedencia", "versao", "resumo")
    list_filter = ("edicao", "tipo", "procedencia", "volume")
    search_fields = ("xml",)
    raw_id_fields = ("origem", "criado_por", "atualizado_por")
    ordering = ("edicao", "ordem")

    @admin.display(description="xml")
    def resumo(self, obj):
        return obj.xml[:80]


@admin.register(Revisao)
class RevisaoAdmin(admin.ModelAdmin):
    list_display = ("pk", "criado_em", "edicao", "acao", "autor", "bloco", "lote")
    list_filter = ("edicao", "acao")
    raw_id_fields = ("bloco", "autor")
    readonly_fields = ("criado_em",)


@admin.register(Sugestao)
class SugestaoAdmin(admin.ModelAdmin):
    list_display = ("pk", "criado_em", "edicao", "no_xml_id", "estado", "nome", "resolvida_por")
    list_filter = ("estado", "edicao")
    search_fields = ("trecho", "sugestao", "comentario", "nome", "email")
    raw_id_fields = ("bloco", "resolvida_por")
    readonly_fields = ("criado_em",)


@admin.register(No)
class NoAdmin(admin.ModelAdmin):
    list_display = ("xml_id", "edicao", "nivel", "n", "rotulo", "titulo", "ordem_ini", "ordem_fim")
    list_filter = ("edicao", "nivel", "volume")
    search_fields = ("xml_id", "rotulo", "titulo")
    raw_id_fields = ("pai",)


@admin.register(Apresentacao)
class ApresentacaoAdmin(admin.ModelAdmin):
    list_display = ("xml_id", "edicao", "titulo", "editada", "versao", "atualizado_por", "atualizado_em")
    list_filter = ("edicao", "editada")
    search_fields = ("xml_id", "titulo")
    raw_id_fields = ("criado_por", "atualizado_por")


@admin.register(ApresentacaoRevisao)
class ApresentacaoRevisaoAdmin(admin.ModelAdmin):
    list_display = ("pk", "criado_em", "edicao", "xml_id", "acao", "autor")
    list_filter = ("edicao", "acao")
    raw_id_fields = ("autor",)


@admin.register(Fonte)
class FonteAdmin(admin.ModelAdmin):
    list_display = ("chave", "papel", "autor", "titulo", "ano")
    list_filter = ("papel", "entrada")
    search_fields = ("chave", "titulo", "autor", "abreviatura")


@admin.register(Citacao)
class CitacaoAdmin(admin.ModelAdmin):
    list_display = ("xml_id", "tipo", "estado", "volume", "pagina", "autor_citado", "fonte", "ativa")
    list_filter = ("estado", "tipo", "ativa", "volume")
    search_fields = ("xml_id", "texto", "referencia_autor", "autor_citado", "obra_citada")
    raw_id_fields = ("fonte", "traducao", "atualizado_por")
