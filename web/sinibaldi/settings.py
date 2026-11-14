"""Configuração do editor colaborativo de *Elementos de Philosophia*."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # .../web
RAIZ_REPO = BASE_DIR.parent                                # raiz do repositório

# Raiz dos dados (volN/*.xml, volN/paginas/*.png). Configurável: as imagens
# do scan são git-ignoradas e podem viver em outro checkout.
SINIBALDI_DADOS = Path(os.environ.get("SINIBALDI_DADOS", RAIZ_REPO))
SINIBALDI_CACHE = Path(os.environ.get("SINIBALDI_CACHE") or (BASE_DIR / "cache"))

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-inseguro-troque-em-producao")
DEBUG = os.environ.get("DEBUG", "1") not in ("0", "", "false", "False")
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "obra",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "sinibaldi.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "obra.contexto.edicoes",
            ],
        },
    },
]

WSGI_APPLICATION = "sinibaldi.wsgi.application"

# Vários processos (gunicorn -w N, worker Celery, comandos) no mesmo SQLite: WAL deixa ler enquanto
# outro grava; IMMEDIATE pega a trava de escrita no início da transação (sem "database is locked"
# na promoção leitura→escrita) e `timeout` espera a vez em vez de falhar.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 30,
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
        },
    }
}

# ---------------------------------------------------------------- Celery (obra/tarefas.py)
# PDFs (LaTeX), fac-símiles e slides são gerados por um worker:  celery -A sinibaldi worker -c 2
# Sem CELERY_BROKER_URL, fila e resultados ficam em arquivos (SINIBALDI_CACHE/celery/): basta uma
# máquina, sem serviço extra. Em produção: CELERY_BROKER_URL=redis://localhost:6379/0 (o
# resultado vai para o mesmo Redis, salvo CELERY_RESULT_BACKEND).
TESTANDO = sys.argv[1:2] == ["test"]
_DIR_CELERY = SINIBALDI_CACHE / "celery"
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "")
if TESTANDO:
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
    CELERY_TASK_ALWAYS_EAGER = True          # os testes de fila de verdade sobem um worker (tests/base.py)
elif CELERY_BROKER_URL:
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
else:
    for _d in ("fila", "controle", "resultados"):
        (_DIR_CELERY / _d).mkdir(parents=True, exist_ok=True)
    CELERY_BROKER_URL = "filesystem://"
    CELERY_BROKER_TRANSPORT_OPTIONS = {
        "data_folder_in": str(_DIR_CELERY / "fila"),
        "data_folder_out": str(_DIR_CELERY / "fila"),
        "control_folder": str(_DIR_CELERY / "controle"),   # padrão seria ./control, no diretório atual
    }
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", f"file://{_DIR_CELERY / 'resultados'}")
CELERY_TASK_SERIALIZER = CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_TRACK_STARTED = True             # STARTED visível a todos os processos web
CELERY_TASK_ACKS_LATE = True                 # worker que morre no meio: a tarefa volta à fila
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1        # tarefas longas: não reservar outras atrás de uma compilação
CELERY_RESULT_EXPIRES = 24 * 3600
CELERY_TASK_TIME_LIMIT = 3600                # o PDF do volume leva minutos; nada legítimo passa de 1 h
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Compilações LaTeX simultâneas na máquina inteira (todos os processos: worker, comandos). Ver
# `exportacao.vaga_pdf`.
SINIBALDI_PDF_SIMULTANEOS = int(os.environ.get("SINIBALDI_PDF_SIMULTANEOS", "2"))

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Recife"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "entrar"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "entrar"
