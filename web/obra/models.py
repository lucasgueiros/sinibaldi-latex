"""Modelos da obra.

O documento é uma **sequência plana de blocos** (`Bloco`, ordenados por `ordem`
dentro de uma `Edicao`); a hierarquia (`No`) é derivada dos blocos `marco`.
"""
from django.conf import settings
from django.db import models

from . import esquema

PASSO_ORDEM = 1024  # folga entre `ordem` de blocos vizinhos


class Edicao(models.Model):
    DIPLOMATICA = "diplomatica"
    NOVA = "nova"
    TIPOS = [(DIPLOMATICA, "Diplomática"), (NOVA, "Nova edição")]

    slug = models.SlugField(unique=True)
    titulo = models.CharField(max_length=200)
    tipo = models.CharField(max_length=12, choices=TIPOS, default=DIPLOMATICA)
    descricao = models.TextField(blank=True)

    class Meta:
        verbose_name = "edição"
        verbose_name_plural = "edições"

    def __str__(self):
        return self.titulo


class Volume(models.Model):
    numero = models.PositiveSmallIntegerField(unique=True)
    titulo = models.CharField(max_length=200)
    ano = models.PositiveSmallIntegerField(null=True, blank=True)
    diretorio = models.CharField(max_length=40, help_text="Pasta sob SINIBALDI_DADOS (vol1, vol2).")

    class Meta:
        ordering = ["numero"]

    def __str__(self):
        return f"Vol. {self.numero} — {self.titulo}"


class Pagina(models.Model):
    NAO_REVISADA = "nao_revisada"
    REVISADA = "revisada"
    VALIDADA = "validada"
    ESTADOS = [(NAO_REVISADA, "Não revisada"), (REVISADA, "Revisada"), (VALIDADA, "Validada")]

    volume = models.ForeignKey(Volume, on_delete=models.CASCADE, related_name="paginas")
    seq = models.IntegerField(help_text="Valor de <pb n> (pode ser negativo no vol. 1).")
    arquivo = models.CharField(max_length=40, blank=True, help_text="Radical da imagem (0034, f001).")
    impressa = models.CharField(max_length=20, blank=True)
    estado = models.CharField(max_length=14, choices=ESTADOS, default=NAO_REVISADA)
    revisada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    revisada_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["volume", "seq"]
        constraints = [models.UniqueConstraint(fields=["volume", "seq"], name="pagina_unica")]

    def __str__(self):
        return f"vol. {self.volume.numero}, p. {self.impressa or self.seq}"


class Bloco(models.Model):
    MARCO, TITULO, PARAGRAFO, SUMARIO, CABECALHO = "marco", "titulo", "paragrafo", "sumario", "cabecalho"
    TIPOS = [
        (MARCO, "Marco de divisão"),
        (TITULO, "Título"),
        (PARAGRAFO, "Parágrafo"),
        (SUMARIO, "Sumário"),
        (CABECALHO, "Cabeçalho corrente"),
    ]
    COPIA, ADAPTADO, NOVO, SUPRIMIDO = "copia", "adaptado", "novo", "suprimido"
    PROCEDENCIAS = [(COPIA, "Cópia"), (ADAPTADO, "Adaptado"), (NOVO, "Novo"), (SUPRIMIDO, "Suprimido")]

    edicao = models.ForeignKey(Edicao, on_delete=models.CASCADE, related_name="blocos")
    ordem = models.BigIntegerField()
    tipo = models.CharField(max_length=10, choices=TIPOS)
    xml = models.TextField(help_text="Um elemento do dialeto de fragmento (obra/esquema.py).")
    volume = models.ForeignKey(Volume, null=True, blank=True, on_delete=models.PROTECT, related_name="blocos")
    pagina = models.IntegerField(null=True, blank=True, help_text="seq do scan onde o bloco começa.")
    origem = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="derivados",
        help_text="Bloco da edição 1916 de que este deriva (nova edição).",
    )
    procedencia = models.CharField(max_length=10, choices=PROCEDENCIAS, default=COPIA)
    origem_versao_vista = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Versão do bloco de origem (1916) contra a qual este bloco foi adaptado ou que o editor já conferiu.",
    )
    versao = models.PositiveIntegerField(default=1)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["edicao", "ordem"]
        indexes = [
            models.Index(fields=["edicao", "ordem"], name="bloco_edicao_ordem"),
            models.Index(fields=["edicao", "volume", "pagina"], name="bloco_edicao_pagina"),
        ]

    def __str__(self):
        return f"#{self.pk} {self.tipo} {self.xml[:50]}"

    @property
    def html(self):
        from . import tei
        return tei.fragmento_para_html(self.xml)


class Revisao(models.Model):
    CRIAR, EDITAR, REMOVER, MOVER, IMPORTAR = "criar", "editar", "remover", "mover", "importar"
    ACOES = [(CRIAR, "Criar"), (EDITAR, "Editar"), (REMOVER, "Remover"), (MOVER, "Mover"), (IMPORTAR, "Importar")]

    bloco = models.ForeignKey(Bloco, null=True, blank=True, on_delete=models.SET_NULL, related_name="revisoes")
    edicao = models.ForeignKey(Edicao, on_delete=models.CASCADE, related_name="revisoes")
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="revisoes_obra"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    acao = models.CharField(max_length=10, choices=ACOES)
    xml_antes = models.TextField(blank=True)
    xml_depois = models.TextField(blank=True)
    comentario = models.TextField(blank=True)
    lote = models.UUIDField(db_index=True)
    volume = models.ForeignKey(Volume, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    pagina = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em", "-pk"]
        verbose_name = "revisão"
        verbose_name_plural = "revisões"

    def __str__(self):
        return f"{self.get_acao_display()} #{self.bloco_id} por {self.autor}"


class No(models.Model):
    """Árvore derivada (cache de navegação). Reconstruída por `arvore.reconstruir`.

    Faixa de blocos: `ordem_ini <= Bloco.ordem < ordem_fim` (fim EXCLUSIVO; o
    último nó de um volume usa `arvore.ORDEM_MAX` quando vai até o fim)."""

    NIVEIS = [(k, v) for k, v in esquema.NIVEIS.items()]

    edicao = models.ForeignKey(Edicao, on_delete=models.CASCADE, related_name="nos")
    pai = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="filhos")
    nivel = models.CharField(max_length=10, choices=NIVEIS)
    n = models.CharField(max_length=20, blank=True)
    xml_id = models.CharField(max_length=80)
    rotulo = models.CharField(max_length=200, blank=True)
    titulo = models.CharField(max_length=300, blank=True)
    posicao = models.PositiveIntegerField(default=0)
    ordem_ini = models.BigIntegerField()
    ordem_fim = models.BigIntegerField()
    volume = models.ForeignKey(Volume, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    pagina_ini = models.IntegerField(null=True, blank=True)
    pagina_fim = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["edicao", "ordem_ini"]
        constraints = [models.UniqueConstraint(fields=["edicao", "xml_id"], name="no_xml_id_unico")]
        indexes = [models.Index(fields=["edicao", "ordem_ini"], name="no_edicao_ordem")]
        verbose_name = "nó"
        verbose_name_plural = "nós"

    def __str__(self):
        return " ".join(x for x in (self.rotulo, self.titulo) if x) or self.xml_id


class Apresentacao(models.Model):
    """Fonte dos slides de um trecho, salva depois de gerada ou corrigida pelo site.

    Identifica o trecho por `(edicao, xml_id)` e NÃO por FK para `No`: os nós são um cache que
    `arvore.reconstruir` apaga e recria. Sem registro, os slides são os automáticos (nada é gravado)."""

    edicao = models.ForeignKey(Edicao, on_delete=models.CASCADE, related_name="apresentacoes")
    xml_id = models.CharField(max_length=80)
    titulo = models.CharField(max_length=300, blank=True, help_text="Título do trecho (para listagens).")
    fonte = models.TextField(help_text="Fonte corrente dos slides (formato de tools/gera_slides.py).")
    fonte_gerada = models.TextField(blank=True, help_text="Última fonte produzida automaticamente.")
    chave_texto = models.CharField(max_length=40, blank=True,
                                   help_text="`exportacao._versao` do nó quando a fonte foi gerada.")
    editada = models.BooleanField(default=False, help_text="A fonte difere da gerada automaticamente.")
    versao = models.PositiveIntegerField(default=1, help_text="+1 a cada gravação (concorrência otimista).")
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-atualizado_em"]
        constraints = [models.UniqueConstraint(fields=["edicao", "xml_id"], name="apresentacao_unica")]
        verbose_name = "apresentação"
        verbose_name_plural = "apresentações"

    def __str__(self):
        return f"Slides de {self.edicao.slug}/{self.xml_id}"


class ApresentacaoRevisao(models.Model):
    """Histórico da fonte dos slides. Também por `(edicao, xml_id)`: sobrevive a "descartar"."""

    GERAR, EDITAR, REGENERAR, RESTAURAR, DESCARTAR = "gerar", "editar", "regenerar", "restaurar", "descartar"
    ACOES = [(GERAR, "Gerar"), (EDITAR, "Editar"), (REGENERAR, "Gerar de novo"), (RESTAURAR, "Restaurar"),
             (DESCARTAR, "Descartar")]

    edicao = models.ForeignKey(Edicao, on_delete=models.CASCADE, related_name="+")
    xml_id = models.CharField(max_length=80)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    criado_em = models.DateTimeField(auto_now_add=True)
    acao = models.CharField(max_length=10, choices=ACOES)
    fonte = models.TextField(help_text="Fonte resultante (em `descartar`, a fonte que foi descartada).")

    class Meta:
        ordering = ["-criado_em", "-pk"]
        indexes = [models.Index(fields=["edicao", "xml_id"], name="apresrev_edicao_xml")]
        verbose_name = "revisão de apresentação"
        verbose_name_plural = "revisões de apresentações"

    def __str__(self):
        return f"{self.get_acao_display()} {self.edicao_id}/{self.xml_id} por {self.autor}"
