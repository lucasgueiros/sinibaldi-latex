"""Três edições: rediagramação (1916), atualizada e nova (esta, escondida da parte pública)."""
from django.db import migrations, models


def ajustar(apps, schema_editor):
    Edicao = apps.get_model("obra", "Edicao")
    Edicao.objects.filter(tipo="nova").update(publica=False)
    Edicao.objects.filter(slug="1916", titulo="Edição diplomática (1916/17)").update(
        titulo="Rediagramação do texto de 1916/17")


def desfazer(apps, schema_editor):
    Edicao = apps.get_model("obra", "Edicao")
    Edicao.objects.filter(slug="1916", titulo="Rediagramação do texto de 1916/17").update(
        titulo="Edição diplomática (1916/17)")


class Migration(migrations.Migration):

    dependencies = [
        ("obra", "0006_nivel_anexo"),
    ]

    operations = [
        migrations.AddField(
            model_name="edicao",
            name="publica",
            field=models.BooleanField(default=True, help_text="Desmarcada, a edição some da parte pública (só editores a veem).", verbose_name="pública"),
        ),
        migrations.AlterField(
            model_name="edicao",
            name="tipo",
            field=models.CharField(choices=[("diplomatica", "Rediagramação do texto de 1916/17"), ("atualizada", "Edição atualizada"), ("nova", "Nova edição")], default="diplomatica", max_length=12),
        ),
        migrations.RunPython(ajustar, desfazer),
    ]
