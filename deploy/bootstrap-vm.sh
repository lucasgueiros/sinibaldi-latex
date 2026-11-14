#!/usr/bin/env bash
# Preparação do editor de *Elementos de Philosophia* na VM do site da Academia Leão XIII
# (Ubuntu 22.04), uma única vez, como root, a partir de um clone do repositório:
#
#   sudo LETSENCRYPT_EMAIL=voce@exemplo.com bash deploy/bootstrap-vm.sh
#
# Pressupõe o site da Academia já instalado na VM (o bootstrap-vm.sh de academialeaoxiii.org.br):
# usa o MESMO PostgreSQL e o MESMO banco dele, com papel e esquema próprios (DB_USER, DB_SCHEMA).
# O papel do editor só enxerga o seu esquema; as tabelas do site não são tocadas. O papel do site
# recebe leitura do esquema, para o backup diário dele (pg_dump do banco) continuar completo.
#
# É idempotente: pode ser executado de novo (por exemplo, para reinstalar release.sh,
# emitir o certificado depois de apontar o DNS ou devolver ao papel do editor a posse das suas
# tabelas depois de uma cópia de banco). Não sobrescreve /etc/<instância>/env.
#
# Homologação: deploy/bootstrap-hml.sh (chama este script).
#
# Variáveis opcionais:
#   INSTANCE           nome da instância (padrão: sinibaldi = produção). Define /srv/<INSTANCE>,
#                      /etc/<INSTANCE>/env, os serviços <INSTANCE> (gunicorn), <INSTANCE>-worker
#                      (Celery) e <INSTANCE>-redis (broker do Celery, só socket unix) e o site do nginx
#   APP_USER           usuário do sistema dono da instância (padrão: sinibaldi)
#   ACADEMIA_INSTANCE  instância do site da Academia cujo banco é usado (padrão: academialeaoxiii);
#                      o banco e o papel do site vêm de /etc/<ACADEMIA_INSTANCE>/env
#   DB_NAME            banco (padrão: o DB_NAME da Academia)
#   DB_USER            papel do editor no PostgreSQL (padrão: INSTANCE com "-" trocado por "_")
#   DB_SCHEMA          esquema do editor dentro do banco (padrão: sinibaldi)
#   NOINDEX=1          envia "X-Robots-Tag: noindex" (homologação não deve aparecer em buscadores)
#   BACKUP_HOUR        hora do backup diário (padrão: 3; minuto 45, depois do da Academia)
#   DOMAIN             domínio principal (padrão: sinibaldi.familiagueiros.com.br)
#   EXTRA_DOMAINS      outros nomes, separados por espaço, redirecionados ao principal;
#                      também entram no certificado
#   LETSENCRYPT_EMAIL  se definido, emite o certificado HTTPS (o DNS já deve apontar para a VM)
#   RUNNER_USER        usuário do serviço do GitHub Actions runner DESTE repositório (padrão: detectado)
#   SKIP_FIRST_RELEASE=1  não publicar a versão do clone atual
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Execute como root (sudo)." >&2; exit 1; }

INSTANCE="${INSTANCE:-sinibaldi}"
[[ "$INSTANCE" =~ ^[a-z][a-z0-9-]{1,40}$ ]] || { echo "INSTANCE inválido: $INSTANCE" >&2; exit 1; }
DOMAIN="${DOMAIN:-sinibaldi.familiagueiros.com.br}"
EXTRA_DOMAINS="${EXTRA_DOMAINS:-}"
SERVER_NAMES="$(echo "$DOMAIN $EXTRA_DOMAINS" | xargs)"

# O runner que atende este repositório (um runner é registrado por repositório: o do site da
# Academia não pega os jobs daqui). Prefere a unidade cujo nome cita "sinibaldi".
detect_runner_user() {
    local unit user units
    units="$(systemctl list-units --all --plain --no-legend 'actions.runner.*' 2>/dev/null | awk '{print $1}')"
    for unit in $(echo "$units" | grep -i sinibaldi) ; do
        user="$(systemctl show -p User --value "$unit")"
        [[ -n "$user" ]] && { echo "$user"; return; }
    done
    echo "${SUDO_USER:-}"
}
RUNNER_USER="${RUNNER_USER:-$(detect_runner_user)}"
[[ -n "$RUNNER_USER" && "$RUNNER_USER" != "root" ]] && id "$RUNNER_USER" >/dev/null 2>&1 \
    || { echo "Não identifiquei o usuário do GitHub runner; informe RUNNER_USER=<usuário>." >&2; exit 1; }
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="/srv/$INSTANCE"
APP_USER="${APP_USER:-sinibaldi}"
ENV_DIR="/etc/$INSTANCE"
ENV_FILE="$ENV_DIR/env"
BACKUP_HOUR="${BACKUP_HOUR:-3}"
EXTRA_HEADERS=""
[[ "${NOINDEX:-0}" == "1" ]] && EXTRA_HEADERS='add_header X-Robots-Tag "noindex, nofollow" always;'
CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"

# Banco do site da Academia
ACADEMIA_INSTANCE="${ACADEMIA_INSTANCE:-academialeaoxiii}"
ACADEMIA_ENV="/etc/$ACADEMIA_INSTANCE/env"
env_get() { sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -n1; }
ACADEMIA_DB_USER="$(env_get "$ACADEMIA_ENV" DB_USER)"
DB_NAME="${DB_NAME:-$(env_get "$ACADEMIA_ENV" DB_NAME)}"
[[ -n "$DB_NAME" ]] || { echo "Não achei o banco da Academia em $ACADEMIA_ENV; instale o site antes ou informe DB_NAME." >&2; exit 1; }
DB_USER="${DB_USER:-${INSTANCE//-/_}}"
DB_SCHEMA="${DB_SCHEMA:-sinibaldi}"
for v in DB_NAME DB_USER DB_SCHEMA; do
    [[ "${!v}" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || { echo "$v inválido: ${!v}" >&2; exit 1; }
done
[[ -z "$ACADEMIA_DB_USER" || "$ACADEMIA_DB_USER" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || { echo "DB_USER da Academia inválido." >&2; exit 1; }

log() { printf '\n\033[1;31m==>\033[0m [%s] %s\n' "$INSTANCE" "$*"; }

log "Pacotes do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
# Redis: cada instância roda o seu (<INSTANCE>-redis.service). O redis-server.service do pacote não
# é usado; se o pacote entrar agora, ele é desligado — se já estava instalado (o site da Academia
# pode usá-lo), fica como está.
REDIS_NOVO=0; dpkg -s redis-server >/dev/null 2>&1 || REDIS_NOVO=1
# TeX (LuaLaTeX + EB Garamond/Cinzel dos slides) e mutool: PDFs, slides e fac-símile gerados pelo site
apt-get install -y -q python3 python3-venv python3-dev build-essential libpq-dev \
    postgresql postgresql-client nginx certbot curl git rsync ca-certificates \
    mupdf-tools latexmk texlive-luatex texlive-latex-recommended texlive-latex-extra \
    texlive-lang-portuguese texlive-fonts-extra fonts-dejavu-core redis-server
if [[ "$REDIS_NOVO" == 1 ]]; then systemctl disable --now redis-server >/dev/null 2>&1 || true; fi

log "Usuário $APP_USER e diretórios"
id "$APP_USER" >/dev/null 2>&1 || adduser --system --group --home "$BASE" --shell /bin/bash "$APP_USER"
usermod -aG www-data,systemd-journal "$APP_USER"
install -d -o "$APP_USER" -g "$APP_USER" -m 755 "$BASE" "$BASE/releases" "$BASE/static" "$BASE/dados"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$BASE/backups" "$BASE/cache"
install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$BASE/redis"
install -d -o root -g root -m 755 "$BASE/bin"

log "Ambiente Python"
[[ -x "$BASE/venv/bin/python" ]] || sudo -u "$APP_USER" python3 -m venv "$BASE/venv"
sudo -u "$APP_USER" "$BASE/venv/bin/pip" install --quiet --upgrade pip wheel

log "PostgreSQL: esquema $DB_SCHEMA no banco $DB_NAME"
systemctl enable --now postgresql
psql_db() { sudo -u postgres psql -v ON_ERROR_STOP=1 -q -d "$DB_NAME" "$@"; }
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 \
    || { echo "O banco $DB_NAME não existe (o site da Academia está instalado?)." >&2; exit 1; }
NEW_DB_PASSWORD=""
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
    NEW_DB_PASSWORD="$(openssl rand -hex 24)"
    sudo -u postgres psql -q -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$NEW_DB_PASSWORD'"
fi
psql_db <<SQL
GRANT CONNECT ON DATABASE $DB_NAME TO $DB_USER;
CREATE SCHEMA IF NOT EXISTS $DB_SCHEMA AUTHORIZATION $DB_USER;
ALTER SCHEMA $DB_SCHEMA OWNER TO $DB_USER;
REVOKE ALL ON SCHEMA $DB_SCHEMA FROM PUBLIC;
ALTER ROLE $DB_USER IN DATABASE $DB_NAME SET search_path = $DB_SCHEMA;
-- Depois de copiar o banco (ex.: sync-hml-from-prod.sh do site), as tabelas podem ter outro dono.
-- ALTER TABLE leva junto as sequências das colunas identity.
DO \$\$
DECLARE r record;
BEGIN
    FOR r IN SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = '$DB_SCHEMA' AND c.relkind IN ('r', 'p', 'v', 'm')
               AND pg_get_userbyid(c.relowner) <> '$DB_USER'
    LOOP
        EXECUTE format('ALTER %s %I.%I OWNER TO %I',
                       CASE r.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'TABLE' END,
                       '$DB_SCHEMA', r.relname, '$DB_USER');
    END LOOP;
END
\$\$;
SQL
if [[ -n "$ACADEMIA_DB_USER" && "$ACADEMIA_DB_USER" != "$DB_USER" ]]; then
    # leitura para o pg_dump do site (sem ela o backup da Academia falharia no esquema do editor)
    psql_db <<SQL
GRANT USAGE ON SCHEMA $DB_SCHEMA TO $ACADEMIA_DB_USER;
GRANT SELECT ON ALL TABLES IN SCHEMA $DB_SCHEMA TO $ACADEMIA_DB_USER;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA $DB_SCHEMA TO $ACADEMIA_DB_USER;
ALTER DEFAULT PRIVILEGES FOR ROLE $DB_USER IN SCHEMA $DB_SCHEMA GRANT SELECT ON TABLES TO $ACADEMIA_DB_USER;
ALTER DEFAULT PRIVILEGES FOR ROLE $DB_USER IN SCHEMA $DB_SCHEMA GRANT SELECT ON SEQUENCES TO $ACADEMIA_DB_USER;
SQL
fi

log "Variáveis de ambiente ($ENV_FILE)"
install -d -o root -g "$APP_USER" -m 750 "$ENV_DIR"
# Broker e resultados do Celery: o Redis da instância, pelo socket unix (sem senha: só o usuário
# da instância abre o socket)
BROKER_URL="redis+socket:///run/$INSTANCE-redis/redis.sock"
if [[ ! -f "$ENV_FILE" ]]; then
    [[ -n "$NEW_DB_PASSWORD" ]] || { echo "O papel $DB_USER já existe mas $ENV_FILE não; recrie a senha manualmente." >&2; exit 1; }
    IP="$(hostname -I | awk '{print $1}')"
    HTTPS=false; [[ -f "$CERT" ]] && HTTPS=true
    cat > "$ENV_FILE" <<ENV
SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n/+=')
DEBUG=0
ALLOWED_HOSTS=$(echo "$SERVER_NAMES" | tr ' ' ','),$IP,localhost
CSRF_TRUSTED_ORIGINS=https://$DOMAIN,http://$DOMAIN,http://$IP
DJANGO_HTTPS=$HTTPS
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$NEW_DB_PASSWORD
DB_HOST=localhost
DB_PORT=5432
DB_SCHEMA=$DB_SCHEMA
STATIC_ROOT=$BASE/static
SINIBALDI_DADOS=$BASE/dados
SINIBALDI_CACHE=$BASE/cache
CELERY_BROKER_URL=$BROKER_URL
EMAIL_HOST=localhost
EMAIL_PORT=25
EMAIL_USE_TLS=false
DEFAULT_FROM_EMAIL=contato@$DOMAIN
ENV
fi
# instâncias criadas antes do worker Celery: acrescenta o broker (sem tocar no resto do arquivo)
grep -q '^CELERY_BROKER_URL=' "$ENV_FILE" \
    || printf '\n# broker do Celery (Redis da instância)\nCELERY_BROKER_URL=%s\n' "$BROKER_URL" >> "$ENV_FILE"
chown root:"$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

log "Redis da instância ($ENV_DIR/redis.conf)"
sed "s/__INSTANCE__/$INSTANCE/g" "$SRC/deploy/redis.conf" > "$ENV_DIR/redis.conf"
chown root:"$APP_USER" "$ENV_DIR/redis.conf"
chmod 640 "$ENV_DIR/redis.conf"

log "Scripts de publicação"
install -o root -g root -m 755 "$SRC/deploy/release.sh" "$BASE/bin/release"
install -o root -g root -m 755 "$SRC/deploy/manage.sh" "$BASE/bin/manage"

log "Permissões sudo (CI e reinício do serviço)"
SUDOERS="/etc/sudoers.d/$INSTANCE"
cat > "$SUDOERS" <<SUDO
# O GitHub runner só pode publicar versões (como $APP_USER); $APP_USER só pode reiniciar os serviços.
$RUNNER_USER ALL=($APP_USER) NOPASSWD: $BASE/bin/release
$APP_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart $INSTANCE, /usr/bin/systemctl reload $INSTANCE, /usr/bin/systemctl restart $INSTANCE-worker
SUDO
chmod 440 "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

log "Serviços systemd (gunicorn, worker Celery, Redis)"
install_unit() {   # install_unit <modelo em deploy/> <nome da unidade>
    sed "s/__INSTANCE__/$INSTANCE/g; s/__APP_USER__/$APP_USER/g" "$SRC/deploy/$1" \
        > "/etc/systemd/system/$2.service"
    chmod 644 "/etc/systemd/system/$2.service"
}
install_unit sinibaldi.service "$INSTANCE"
install_unit sinibaldi-worker.service "$INSTANCE-worker"
install_unit sinibaldi-redis.service "$INSTANCE-redis"
systemctl daemon-reload
systemctl enable "$INSTANCE" "$INSTANCE-worker" "$INSTANCE-redis" >/dev/null
# o Redis sobe já (reiniciado, para ler um redis.conf novo); web e worker sobem na publicação
systemctl restart "$INSTANCE-redis"
if [[ -e "$BASE/current" ]]; then
    # instância já publicada: o worker (talvez recém-instalado) e o web com o broker novo. Uma
    # versão anterior ao Celery não tem o worker: ele sobe na próxima publicação (release.sh).
    if [[ -f "$BASE/current/web/sinibaldi/celery.py" && -x "$BASE/venv/bin/celery" ]]; then
        systemctl restart "$INSTANCE-worker"
    fi
    if systemctl is-active --quiet "$INSTANCE"; then systemctl restart "$INSTANCE"; fi
fi

log "nginx"
# Instala o site sem tocar nos outros sites do servidor (o da Academia, inclusive). Se a configuração
# resultante não passar no "nginx -t", restaura a anterior e aborta, sem deixar o nginx quebrado.
NGINX_SITE="/etc/nginx/sites-available/$INSTANCE"
install_nginx() {
    local backup=""
    if [[ -f "$NGINX_SITE" ]]; then backup="$(mktemp)"; cp "$NGINX_SITE" "$backup"; fi
    sed "s/__SERVER_NAMES__/$SERVER_NAMES/g; s/__DOMAIN__/$DOMAIN/g; s/__INSTANCE__/$INSTANCE/g; s|# __EXTRA_HEADERS__|$EXTRA_HEADERS|" \
        "$1" > "$NGINX_SITE"
    ln -sfn "$NGINX_SITE" "/etc/nginx/sites-enabled/$INSTANCE"
    if ! nginx -t -q; then
        echo "Configuração do nginx inválida; restaurando a anterior." >&2
        if [[ -n "$backup" ]]; then cp "$backup" "$NGINX_SITE"; else rm -f "$NGINX_SITE" "/etc/nginx/sites-enabled/$INSTANCE"; fi
        nginx -t -q && systemctl reload nginx
        exit 1
    fi
    [[ -n "$backup" ]] && rm -f "$backup"
    systemctl reload nginx || systemctl restart nginx
}
mkdir -p /var/www/html
systemctl enable --now nginx >/dev/null
if [[ -f "$CERT" ]]; then install_nginx "$SRC/deploy/nginx.conf"; else install_nginx "$SRC/deploy/nginx-http.conf"; fi

if [[ ! -f "$CERT" && -n "${LETSENCRYPT_EMAIL:-}" ]]; then
    log "Certificado HTTPS (Let's Encrypt)"
    CERT_ARGS=(); for d in $SERVER_NAMES; do CERT_ARGS+=(-d "$d"); done
    if certbot certonly --webroot -w /var/www/html "${CERT_ARGS[@]}" \
        --email "$LETSENCRYPT_EMAIL" --agree-tos --non-interactive; then
        install_nginx "$SRC/deploy/nginx.conf"
    else
        echo "Não foi possível emitir o certificado (o DNS aponta para esta VM?). O site segue em HTTP." >&2
    fi
fi

if [[ -f "$CERT" ]]; then
    sed -i 's/^DJANGO_HTTPS=.*/DJANGO_HTTPS=true/' "$ENV_FILE"
    mkdir -p /etc/letsencrypt/renewal-hooks/deploy
    printf '#!/bin/sh\nsystemctl reload nginx\n' > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
    chmod 755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
    systemctl is-active --quiet "$INSTANCE" && systemctl restart "$INSTANCE"
fi

log "Backup diário ($BACKUP_HOUR:45)"
cat > "/etc/cron.d/$INSTANCE" <<CRON
45 $BACKUP_HOUR * * * $APP_USER $BASE/current/deploy/backup.sh $BASE >> $BASE/backups/backup.log 2>&1
CRON

if [[ "${SKIP_FIRST_RELEASE:-0}" != "1" && ! -e "$BASE/current" ]]; then
    log "Primeira publicação"
    cd "$SRC"
    git config --global --add safe.directory "$SRC" 2>/dev/null || true
    if git rev-parse HEAD >/dev/null 2>&1; then
        SHA="$(git rev-parse HEAD)"
        git archive --format=tar HEAD web tools tex deploy | sudo -u "$APP_USER" "$BASE/bin/release" "$SHA"
    else
        SHA="$(date +%s | sha1sum | cut -c1-12)"
        tar -c --exclude=.venv --exclude=node_modules --exclude=cache --exclude='db.sqlite3*' web tools tex deploy \
            | sudo -u "$APP_USER" "$BASE/bin/release" "$SHA"
    fi
fi

log "Pronto"
cat <<MSG
Site: http$([[ -f "$CERT" ]] && echo s)://$DOMAIN  (ou http://$(hostname -I | awk '{print $1}'))
Banco: $DB_NAME, esquema $DB_SCHEMA (papel $DB_USER)
Serviços: $INSTANCE (gunicorn), $INSTANCE-worker (Celery), $INSTANCE-redis (broker, /run/$INSTANCE-redis/redis.sock)

Próximos passos (deploy/README.md):
  1. da máquina de trabalho, envie os scans e o TEI:   deploy/envia-dados.sh <ssh-host> $INSTANCE
  2. carregue o texto (importar_tei/derivar_* ou um dump do banco local) e crie o administrador:
       sudo -u $APP_USER $BASE/bin/manage createsuperuser
Atualizações automáticas: GitHub Actions (.github/workflows/ci-cd.yml):
  master → sinibaldi · homolog → sinibaldi-hml
MSG
