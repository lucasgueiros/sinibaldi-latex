#!/usr/bin/env bash
# Primeira carga: copia o banco local (web/db.sqlite3: edições, revisões, citações, usuários)
# para o PostgreSQL de uma instância no servidor, que deve estar VAZIA (só migrada).
#
#   deploy/envia-banco.sh <ssh-host> [instância]        (instância padrão: sinibaldi)
#
# dumpdata com chaves naturais (sem contenttypes/permissões/sessões, que a migração do servidor
# já cria) → scp para o servidor → loaddata como o usuário da instância (pede a senha do sudo).
# Alternativa sem o banco local: importar_tei + derivar_* no servidor (web/README.md).
set -euo pipefail
HOST="${1:?uso: envia-banco.sh <ssh-host> [instância]}"
INSTANCE="${2:-sinibaldi}"
[[ "$INSTANCE" =~ ^[a-z][a-z0-9-]{1,40}$ ]] || { echo "Instância inválida: $INSTANCE" >&2; exit 1; }
WEB="$(cd "$(dirname "${BASH_SOURCE[0]}")/../web" && pwd)"
PY="${PYTHON:-$WEB/.venv/bin/python}"
[[ -x "$PY" ]] || PY=python3
DUMP="$(mktemp --suffix=.json.gz)"; trap 'rm -f "$DUMP"' EXIT

echo "==> dumpdata de $WEB/db.sqlite3"
(cd "$WEB" && env -u DB_NAME "$PY" manage.py dumpdata --natural-foreign --natural-primary \
    -e contenttypes -e auth.permission -e sessions -e admin.logentry) | gzip > "$DUMP"
echo "    $(du -h "$DUMP" | cut -f1) comprimido"

REMOTO=".sinibaldi-banco.json.gz"
echo "==> Enviando para $HOST"
scp -q "$DUMP" "$HOST:$REMOTO"

echo "==> loaddata em $INSTANCE"
# O servidor recusa se já houver texto: loaddata por cima misturaria as duas bases.
ssh -t "$HOST" "set -e; U=\$(stat -c %U /srv/$INSTANCE); sudo install -o \$U -m 600 \$HOME/$REMOTO /srv/$INSTANCE/cache/carga.json.gz; rm -f \$HOME/$REMOTO
  n=\$(sudo -u \$U /srv/$INSTANCE/bin/manage shell -c 'from obra.models import Bloco; print(Bloco.objects.count())' | tail -n1)
  if [ \"\$n\" != 0 ]; then echo \"A instância já tem \$n blocos; nada foi carregado.\" >&2; sudo rm -f /srv/$INSTANCE/cache/carga.json.gz; exit 1; fi
  sudo -u \$U /srv/$INSTANCE/bin/manage loaddata /srv/$INSTANCE/cache/carga.json.gz
  sudo rm -f /srv/$INSTANCE/cache/carga.json.gz
  sudo systemctl restart $INSTANCE
  echo 'Banco carregado.'"
