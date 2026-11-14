#!/usr/bin/env bash
# Atalho para comandos do Django numa instância. Instalado em /srv/<instância>/bin/manage.
#   sudo -u sinibaldi     /srv/sinibaldi/bin/manage createsuperuser
#   sudo -u sinibaldi-hml /srv/sinibaldi-hml/bin/manage importar_tei
set -euo pipefail
BASE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
INSTANCE="$(basename "$BASE")"
set -a; . "/etc/$INSTANCE/env"; set +a
export HOME="$BASE"
cd "$BASE/current/web"
exec "$BASE/venv/bin/python" manage.py "$@"
