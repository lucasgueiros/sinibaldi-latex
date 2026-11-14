#!/usr/bin/env bash
# Prepara a instância de HOMOLOGAÇÃO do editor na mesma VM da produção, separada dela:
#
#   usuário sinibaldi-hml · /srv/sinibaldi-hml · /etc/sinibaldi-hml/env
#   esquema sinibaldi no banco da homologação do site (academialeaoxiii_hml), papel sinibaldi_hml
#   serviço sinibaldi-hml · site nginx sinibaldi-hml
#
# Uso (como root, a partir de um clone do repositório na branch homolog):
#
#   sudo LETSENCRYPT_EMAIL=voce@exemplo.com bash deploy/bootstrap-hml.sh
#
# Antes: aponte o DNS de hml.sinibaldi.familiagueiros.com.br para o IP da VM, e instale a
# homologação do site da Academia (deploy/bootstrap-hml.sh de academialeaoxiii.org.br).
# Idempotente, como o bootstrap-vm.sh. Aceita as mesmas variáveis opcionais (RUNNER_USER etc.).
set -euo pipefail
export INSTANCE=sinibaldi-hml
export APP_USER=sinibaldi-hml
export ACADEMIA_INSTANCE="${ACADEMIA_INSTANCE:-academialeaoxiii-hml}"
export DOMAIN="${DOMAIN:-hml.sinibaldi.familiagueiros.com.br}"
export EXTRA_DOMAINS="${EXTRA_DOMAINS:-}"
export NOINDEX="${NOINDEX:-1}"
export BACKUP_HOUR="${BACKUP_HOUR:-4}"
exec bash "$(dirname "${BASH_SOURCE[0]}")/bootstrap-vm.sh" "$@"
