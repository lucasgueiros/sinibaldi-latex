#!/usr/bin/env bash
# (Opcional) Copia o esquema do editor e os dados do scan da PRODUÇÃO para a HOMOLOGAÇÃO,
# substituindo o que houver na homologação. A produção só é lida; o resto do banco (o site da
# Academia) não é tocado. Como root:
#
#   sudo bash deploy/sync-hml-from-prod.sh
#
# Depois da cópia, roda as migrações da versão em homologação (que pode estar à frente da master).
# Os usuários do editor passam a ser os mesmos da produção (mesmas senhas).
#
# Nota: o sync-hml-from-prod.sh do site da Academia copia o banco inteiro (com este esquema) e
# deixa as tabelas com o dono errado; depois dele, rode "sudo bash deploy/bootstrap-hml.sh" daqui,
# que devolve a posse ao papel do editor, ou este script.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Execute como root (sudo)." >&2; exit 1; }

PROD=sinibaldi
HML=sinibaldi-hml
env_get() { sed -n "s/^$2=//p" "/etc/$1/env" | tail -n1; }

PROD_DB="$(env_get $PROD DB_NAME)"
PROD_SCHEMA="$(env_get $PROD DB_SCHEMA)"; PROD_SCHEMA="${PROD_SCHEMA:-sinibaldi}"
HML_DB="$(env_get $HML DB_NAME)"
HML_SCHEMA="$(env_get $HML DB_SCHEMA)"; HML_SCHEMA="${HML_SCHEMA:-sinibaldi}"
HML_DB_USER="$(env_get $HML DB_USER)"
HML_USER="$(stat -c %U /srv/$HML)"
[[ -n "$PROD_DB" && -n "$HML_DB" && "$PROD_DB" != "$HML_DB" ]] || { echo "Bancos não identificados." >&2; exit 1; }
[[ "$PROD_SCHEMA" == "$HML_SCHEMA" ]] || { echo "Esquemas diferentes ($PROD_SCHEMA × $HML_SCHEMA): não suportado." >&2; exit 1; }

read -r -p "Substituir o esquema '$HML_SCHEMA' do banco '$HML_DB' e os dados da homologação pelos da produção? [s/N] " ok
[[ "$ok" =~ ^[sS]$ ]] || exit 1

echo "==> Esquema $PROD_DB.$PROD_SCHEMA → $HML_DB.$HML_SCHEMA"
systemctl stop "$HML" "$HML-worker"
DUMP="$(mktemp)"; trap 'rm -f "$DUMP"' EXIT
chmod 644 "$DUMP"
sudo -u postgres pg_dump -Fc -n "$PROD_SCHEMA" "$PROD_DB" > "$DUMP"
sudo -u postgres psql -v ON_ERROR_STOP=1 -q -d "$HML_DB" -c "DROP SCHEMA IF EXISTS $HML_SCHEMA CASCADE"
sudo -u postgres pg_restore --no-owner --no-acl --role="$HML_DB_USER" -d "$HML_DB" "$DUMP"

echo "==> Dados do scan"
rsync -a --delete --chown="$HML_USER:$HML_USER" "/srv/$PROD/dados/" "/srv/$HML/dados/"
rm -rf "/srv/$HML/cache/"*
# os resultados de tarefas no Redis apontam para arquivos do cache que acabaram de sair
if systemctl is-active --quiet "$HML-redis"; then
    sudo -u "$HML_USER" redis-cli -s "/run/$HML-redis/redis.sock" FLUSHALL >/dev/null
fi

echo "==> Permissões"
# o pg_restore com --role já deixa tudo com o papel da homologação; refaz o que o --no-acl e o
# DROP SCHEMA levaram (leitura para o backup do site, como no bootstrap-vm.sh)
ACAD_HML_USER="$(env_get academialeaoxiii-hml DB_USER 2>/dev/null || true)"
{
    echo "REVOKE ALL ON SCHEMA $HML_SCHEMA FROM PUBLIC;"
    if [[ -n "$ACAD_HML_USER" && "$ACAD_HML_USER" != "$HML_DB_USER" ]]; then
        echo "GRANT USAGE ON SCHEMA $HML_SCHEMA TO $ACAD_HML_USER;"
        echo "GRANT SELECT ON ALL TABLES IN SCHEMA $HML_SCHEMA TO $ACAD_HML_USER;"
        echo "GRANT SELECT ON ALL SEQUENCES IN SCHEMA $HML_SCHEMA TO $ACAD_HML_USER;"
        echo "ALTER DEFAULT PRIVILEGES FOR ROLE $HML_DB_USER IN SCHEMA $HML_SCHEMA GRANT SELECT ON TABLES TO $ACAD_HML_USER;"
        echo "ALTER DEFAULT PRIVILEGES FOR ROLE $HML_DB_USER IN SCHEMA $HML_SCHEMA GRANT SELECT ON SEQUENCES TO $ACAD_HML_USER;"
    fi
} | sudo -u postgres psql -v ON_ERROR_STOP=1 -q -d "$HML_DB"

echo "==> Migrações da versão em homologação"
sudo -u "$HML_USER" "/srv/$HML/bin/manage" migrate --noinput
systemctl start "$HML" "$HML-worker"
echo "Pronto."
