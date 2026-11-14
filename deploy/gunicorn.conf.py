"""Configuração do gunicorn (usada pelo systemd: deploy/sinibaldi.service).

O trabalho pesado (PDFs, fac-símiles, slides) vai para o worker Celery (deploy/sinibaldi-worker.service,
web/obra/tarefas.py) e o estado dos pedidos fica no Redis: qualquer processo web enxerga qualquer
pedido, então dá para ter vários processos. Threads (gthread) porque um pedido «Preparando…» segura
a sua por até 20 s (exportacao.ESPERA_PADRAO).
"""

import os

# Cada instância (produção, homologação) tem seu socket; o serviço systemd define GUNICORN_BIND.
bind = os.environ.get("GUNICORN_BIND", "unix:/run/sinibaldi/gunicorn.sock")
workers = int(os.environ.get("GUNICORN_WORKERS", 2))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 8))
timeout = 120
graceful_timeout = 30
# recicla os processos de vez em quando (as compilações não rodam mais aqui)
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", 2000))
max_requests_jitter = 200
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "127.0.0.1"
