#!/usr/bin/env bash
# Publica uma versão do editor. Instalado pelo bootstrap em /srv/<instância>/bin/release
# (dono root, não editável pelo CI) e executado como o usuário dono da instância:
#
#   git archive --format=tar HEAD web tools tex deploy | sudo -n -u sinibaldi /srv/sinibaldi/bin/release <commit-sha>
#   git archive --format=tar HEAD web tools tex deploy | sudo -n -u sinibaldi-hml /srv/sinibaldi-hml/bin/release <commit-sha>
#
# Só essas quatro pastas vão para o servidor: web/ (o Django), tools/ e tex/ (a conversão
# TEI → LaTeX → PDF e os slides, que o site chama) e deploy/ (gunicorn, backup). Os scans e o TEI
# ficam em SINIBALDI_DADOS (deploy/envia-dados.sh), fora das versões.
#
# A instância é deduzida do local onde o script está instalado (/srv/<instância>/bin/release):
# serviço <instância>, variáveis em /etc/<instância>/env, socket em /run/<instância>/.
#
# Passos: extrai o código em releases/<sha>, instala as dependências, roda check/migrate/collectstatic,
# troca o link "current", reinicia o gunicorn e verifica a saúde. Se a verificação falhar,
# volta para a versão anterior. (Migrações já aplicadas não são desfeitas.)
set -euo pipefail

SHA="${1:?uso: release <commit-sha>  (código em tar pela entrada padrão)}"
[[ "$SHA" =~ ^[0-9a-f]{7,40}$ ]] || { echo "SHA inválido: $SHA" >&2; exit 2; }

BASE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
INSTANCE="$(basename "$BASE")"
VENV="$BASE/venv"
REL="$BASE/releases/$SHA"
KEEP=5
SERVICE="$INSTANCE"
SOCKET="/run/$INSTANCE/gunicorn.sock"
ENV_FILE="/etc/$INSTANCE/env"
APP_USER="$(stat -c %U "$BASE")"

[[ -f "$ENV_FILE" ]] || { echo "Instância desconhecida: $ENV_FILE não existe." >&2; exit 2; }
[[ "$(id -un)" == "$APP_USER" ]] || { echo "Execute como o usuário $APP_USER." >&2; exit 2; }

log() { printf '\n==> %s\n' "$*"; }

log "Extraindo $SHA ($INSTANCE)"
rm -rf "$REL.tmp"
mkdir -p "$REL.tmp"
tar -x -C "$REL.tmp"
[[ -f "$REL.tmp/web/manage.py" ]] || { echo "O pacote não tem web/manage.py." >&2; rm -rf "$REL.tmp"; exit 2; }
rm -rf "$REL"
mv "$REL.tmp" "$REL"

set -a
# shellcheck disable=SC1091
. "$ENV_FILE"
set +a
export HOME="$BASE"

cd "$REL/web"
log "Dependências"
"$VENV/bin/pip" install --quiet --disable-pip-version-check -r requirements.txt

log "Verificações e migrações"
# collectstatic primeiro: gera o manifesto dos estáticos (nomes com hash), usado pelos templates.
"$VENV/bin/python" manage.py collectstatic --noinput --verbosity 0
"$VENV/bin/python" manage.py check --deploy --fail-level ERROR
"$VENV/bin/python" manage.py migrate --noinput

PREV="$(readlink -f "$BASE/current" 2>/dev/null || true)"

switch_to() {
    ln -sfn "$1" "$BASE/current.new"
    mv -T "$BASE/current.new" "$BASE/current"
    sudo -n /usr/bin/systemctl restart "$SERVICE"
}

healthy() {
    local host="${ALLOWED_HOSTS%%,*}" code
    for _ in $(seq 1 20); do
        sleep 1
        code="$(curl -s -o /dev/null -w '%{http_code}' --unix-socket "$SOCKET" \
            -H "Host: $host" -H "X-Forwarded-Proto: https" http://localhost/ || true)"
        [[ "$code" == "200" ]] && return 0
    done
    echo "Verificação de saúde falhou (HTTP $code)." >&2
    return 1
}

log "Ativando a versão $SHA"
switch_to "$REL"
if ! healthy; then
    if [[ -n "$PREV" && -d "$PREV" && "$PREV" != "$REL" ]]; then
        log "Revertendo para $(basename "$PREV")"
        switch_to "$PREV"
    fi
    journalctl -u "$SERVICE" -n 50 --no-pager 2>/dev/null || true
    exit 1
fi

log "Limpando versões antigas (mantém $KEEP)"
cd "$BASE/releases"
{ ls -1t | grep -vx "$(basename "$REL")" | grep -v "\.tmp$" | tail -n +"$KEEP" | xargs -r rm -rf --; } || true

log "Publicado: $SHA"
