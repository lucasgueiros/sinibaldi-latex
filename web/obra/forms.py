"""Formulários da parte pública."""
from django import forms
from django.core.validators import MaxLengthValidator

from .models import Bloco, Citacao, Fonte, Sugestao

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


# ----------------------------------------------------------------------- citações (área restrita)
class _ComCampos:
    """Põe a classe `campo` (CSS do projeto) em todos os widgets."""

    def _estilizar(self):
        for f in self.fields.values():
            f.widget.attrs["class"] = (f.widget.attrs.get("class", "") + " campo mt-1").strip()


class FonteForm(_ComCampos, forms.ModelForm):
    class Meta:
        model = Fonte
        fields = ["chave", "papel", "entrada", "abreviatura", "autor", "editor", "tradutor", "titulo", "subtitulo",
                  "titulo_maior", "serie", "volume", "edicao", "local", "editora", "ano", "paginas", "periodico",
                  "idioma", "isbn", "doi", "url", "traducao_de", "nota"]
        widgets = {"nota": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["traducao_de"].queryset = Fonte.objects.exclude(papel=Fonte.TRADUCAO)
        if self.instance.pk:
            self.fields["traducao_de"].queryset = self.fields["traducao_de"].queryset.exclude(pk=self.instance.pk)
        self._estilizar()


def _rotulo_fonte(f):
    return f"{f.get_papel_display()}: {f.abreviatura or f.titulo} [{f.chave}]"


class CitacaoForm(_ComCampos, forms.ModelForm):
    class Meta:
        model = Citacao
        fields = ["tipo", "estado", "autor_citado", "obra_citada", "lugar", "fonte", "pagina_fonte", "texto_fonte",
                  "traducao", "pagina_traducao", "texto_traducao", "nota"]
        widgets = {"texto_fonte": forms.Textarea(attrs={"rows": 3}), "texto_traducao": forms.Textarea(attrs={"rows": 3}),
                   "nota": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["fonte"].queryset = Fonte.objects.order_by("papel", "autor", "titulo")
        self.fields["traducao"].queryset = Fonte.objects.filter(papel=Fonte.TRADUCAO).order_by("autor", "titulo")
        self.fields["fonte"].label_from_instance = _rotulo_fonte
        self.fields["traducao"].label_from_instance = _rotulo_fonte
        self._estilizar()

    def clean(self):
        d = super().clean()
        if d.get("fonte"):   # com fonte, a citação está referenciada
            d["estado"] = Citacao.REFERENCIADA
        return d


class CitacoesEmLoteForm(_ComCampos, forms.Form):
    """Mesmos dados para várias citações (ex.: todas as da *Summa* recebem autor, obra e edição)."""
    autor_citado = forms.CharField(required=False, max_length=200)
    obra_citada = forms.CharField(required=False, max_length=300)
    fonte = forms.ModelChoiceField(queryset=Fonte.objects.all(), required=False)
    traducao = forms.ModelChoiceField(queryset=Fonte.objects.filter(papel=Fonte.TRADUCAO), required=False)
    estado = forms.ChoiceField(choices=[("", "— manter —")] + Citacao.ESTADOS, required=False)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["fonte"].label_from_instance = _rotulo_fonte
        self.fields["traducao"].label_from_instance = _rotulo_fonte
        self._estilizar()
