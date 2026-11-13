"""Formulários da parte pública."""
from django import forms
from django.core.validators import MaxLengthValidator

from .models import Bloco, Sugestao

LIMITE_TRECHO = 2000
LIMITE_SUGESTAO = 5000
LIMITE_COMENTARIO = 2000


class SugestaoForm(forms.ModelForm):
    """Sugestão de correção. `bloco` é opcional; se vier, tem de ser da mesma edição e conter texto de leitura."""

    # campo-isca: humanos não o veem; robôs costumam preenchê-lo
    site = forms.CharField(required=False)
    bloco = forms.ModelChoiceField(queryset=Bloco.objects.none(), required=False,
                                   error_messages={"invalid_choice": "Trecho inválido para esta edição."})

    class Meta:
        model = Sugestao
        fields = ["bloco", "trecho", "sugestao", "comentario", "nome", "email"]

    def __init__(self, *args, edicao, **kw):
        super().__init__(*args, **kw)
        self.edicao = edicao
        self.fields["bloco"].queryset = Bloco.objects.filter(edicao=edicao)
        # os limites viram `maxlength` no HTML e erro de validação no servidor
        for nome, limite in (("trecho", LIMITE_TRECHO), ("sugestao", LIMITE_SUGESTAO),
                             ("comentario", LIMITE_COMENTARIO)):
            self.fields[nome].max_length = limite
            self.fields[nome].validators.append(MaxLengthValidator(limite))

    def clean_bloco(self):
        b = self.cleaned_data.get("bloco")
        if b is not None and (b.procedencia == Bloco.SUPRIMIDO or b.tipo == Bloco.CABECALHO):
            raise forms.ValidationError("Este trecho não aceita sugestões.")
        return b

    def clean(self):
        dados = super().clean()
        if self.errors:
            return dados
        trecho = (dados.get("trecho") or "").strip()
        sugestao = (dados.get("sugestao") or "").strip()
        comentario = (dados.get("comentario") or "").strip()
        if not sugestao and not comentario:
            raise forms.ValidationError("Informe o texto corrigido ou um comentário.")
        if trecho and trecho == sugestao and not comentario:
            raise forms.ValidationError("Nada foi alterado: o texto proposto é igual ao trecho.")
        return dados

    def save(self, commit=True):
        s = super().save(commit=False)
        s.edicao = self.edicao
        s.bloco_versao = s.bloco.versao if s.bloco_id else None
        if commit:
            s.save()
        return s
