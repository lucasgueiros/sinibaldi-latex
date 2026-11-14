"""Configuração do gunicorn (usada pelo systemd: deploy/sinibaldi.service).

Um único processo com várias threads, de propósito: os PDFs grandes compilam numa thread em segundo
plano e o andamento fica num registro em memória (obra/exportacao.py, obra/slides.py). Com vários
processos, a requisição que consulta o andamento poderia cair num processo que não conhece a tarefa.
Pelo mesmo motivo não há max_requests (reciclar o processo mataria a compilação em curso).
"""

import os

# Cada instância (produção, homologação) tem seu socket; o serviço systemd define GUNICORN_BIND.
bind = os.environ.get("GUNICORN_BIND", "unix:/run/sinibaldi/gunicorn.sock")
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 8))
timeout = 120
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "127.0.0.1"
