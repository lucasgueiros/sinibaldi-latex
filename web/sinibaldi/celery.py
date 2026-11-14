"""App Celery: gera PDFs, fac-símiles e slides fora do processo web (`obra/tarefas.py`).

Worker:  celery -A sinibaldi worker -l info -c 2      (de dentro de web/)
Configuração em `settings.py` (prefixo CELERY_); broker padrão no sistema de arquivos, Redis por
`CELERY_BROKER_URL=redis://…`.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sinibaldi.settings")

app = Celery("sinibaldi")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["obra"], related_name="tarefas")
