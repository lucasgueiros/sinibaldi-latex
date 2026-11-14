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



def _env_bool(nome, padrao=False):
    v = os.environ.get(nome)
    return padrao if v is None else v.strip().lower() not in ("0", "", "false", "no", "nao", "não")


def _env_lista(nome, padrao=""):
    return [x.strip() for x in os.environ.get(nome, padrao).split(",") if x.strip()]


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-inseguro-troque-em-producao")
DEBUG = _env_bool("DEBUG", True)
ALLOWED_HOSTS = _env_lista("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver")
CSRF_TRUSTED_ORIGINS = _env_lista("CSRF_TRUSTED_ORIGINS")

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

# PostgreSQL se DB_NAME estiver definido; senão SQLite local (desenvolvimento).
# No servidor, o editor fica no MESMO banco do site da Academia, num esquema próprio (DB_SCHEMA,
# padrão "sinibaldi"): as tabelas não se misturam com as do site (nem auth_user, django_migrations…)
# e entram no backup diário do banco. Ver deploy/README.md.
if os.environ.get("DB_NAME"):
    DB_SCHEMA = os.environ.get("DB_SCHEMA", "sinibaldi")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["DB_NAME"],
            "USER": os.environ.get("DB_USER", ""),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", ""),
            "PORT": os.environ.get("DB_PORT", ""),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {"options": f"-c search_path={DB_SCHEMA}"} if DB_SCHEMA else {},
        }
    }
else:
    # Vários processos (gunicorn -w N, worker Celery, comandos) no mesmo SQLite: WAL deixa ler
    # enquanto outro grava; IMMEDIATE pega a trava de escrita no início da transação (sem "database
    # is locked" na promoção leitura→escrita) e `timeout` espera a vez em vez de falhar.
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
STATIC_ROOT = Path(os.environ.get("STATIC_ROOT") or (BASE_DIR / "staticfiles"))
if not DEBUG:
    # nomes com hash: o nginx serve /static/ com cache longo ("immutable")
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "entrar"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "entrar"

# --------------------------------------------------------------------------- produção
# Atrás do nginx (deploy/nginx.conf), que termina o TLS e envia X-Forwarded-Proto.
if _env_bool("DJANGO_HTTPS"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", 60 * 60 * 24 * 30))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    # HSTS só no próprio host: o domínio-pai (familiagueiros.com.br) tem outros sites; sem preload.
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# Cookies com nome próprio: o editor e o site da Academia podem ficar sob o mesmo domínio-pai.
SESSION_COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "sinibaldi_sessionid")
CSRF_COOKIE_NAME = os.environ.get("CSRF_COOKIE_NAME", "sinibaldi_csrftoken")

EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 25))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "webmaster@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
ADMINS = [("Admin", e) for e in _env_lista("DJANGO_ADMINS")]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "WARNING")},
    "loggers": {"django": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "WARNING"),
                           "propagate": False}},
}
