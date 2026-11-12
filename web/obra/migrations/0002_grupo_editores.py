from django.db import migrations

GRUPO = "editores"


def criar_grupo(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes

    config = apps.get_app_config("obra")
    config.models_module = True  # create_permissions ignora apps sem models_module
    try:
        create_contenttypes(config, verbosity=0, apps=apps)
        create_permissions(config, verbosity=0, apps=apps)
    finally:
        config.models_module = None
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    grupo, _ = Group.objects.get_or_create(name=GRUPO)
    codigos = [f"{acao}_bloco" for acao in ("add", "change", "delete")]
    grupo.permissions.set(Permission.objects.filter(content_type__app_label="obra", codename__in=codigos))


def remover_grupo(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name=GRUPO).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("obra", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [migrations.RunPython(criar_grupo, remover_grupo)]
