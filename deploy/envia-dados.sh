#!/usr/bin/env bash
# Envia, da máquina de trabalho para o servidor, os dados que o site lê e que não vão nas versões
# (git-ignorados ou grandes demais): SINIBALDI_DADOS = /srv/<instância>/dados.
#
#   deploy/envia-dados.sh <ssh-host> [instância]        (instância padrão: sinibaldi)
#   deploy/envia-dados.sh vm-academia sinibaldi-hml
#
# Vai: volN/paginas/*.png (imagens do scan, ~3,6 GB), manifesto.tsv e paginas.tsv, os PDFs
# originais (vol1.pdf, vol2/vol2.pdf: fac-símile), volN/volN.corrigido.xml (importar_tei) e
# volN/pretextuais.json. Incremental (rsync): rodar de novo só manda o que mudou.
#
# Em duas etapas, para não exigir sudo sem senha no servidor: rsync para ~/.sinibaldi-dados/ do
# usuário do ssh e, depois, "sudo rsync" dali para /srv/<instância>/dados (pede a senha do sudo).
# Rode da raiz do checkout que tem as imagens (o principal, não um worktree).
set -euo pipefail
HOST="${1:?uso: envia-dados.sh <ssh-host> [instância]}"
INSTANCE="${2:-sinibaldi}"
[[ "$INSTANCE" =~ ^[a-z][a-z0-9-]{1,40}$ ]] || { echo "Instância inválida: $INSTANCE" >&2; exit 1; }
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
ls vol*/paginas/*.png >/dev/null 2>&1 || { echo "Não há imagens em $RAIZ/vol*/paginas/ (rode do checkout principal)." >&2; exit 1; }

LISTA="$(mktemp)"; trap 'rm -f "$LISTA"' EXIT
{
    for v in vol*/; do
        v="${v%/}"
        [[ -d "$v/paginas" ]] || continue
        ls "$v"/paginas/*.png
        for f in "$v/paginas/manifesto.tsv" "$v/paginas/paginas.tsv" "$v/$v.corrigido.xml" "$v/pretextuais.json" \
                 "$v/$v.pdf" "$v.pdf"; do
            [[ -f "$f" ]] && echo "$f"
        done
    done
} > "$LISTA"
echo "==> $(wc -l < "$LISTA") arquivos ($(xargs -d '\n' du -ch < "$LISTA" | tail -n1 | cut -f1)) para $HOST:$INSTANCE"

echo "==> Etapa 1: rsync para ~/.sinibaldi-dados/ em $HOST"
rsync -a --info=progress2 --files-from="$LISTA" ./ "$HOST:.sinibaldi-dados/"

echo "==> Etapa 2: copiar para /srv/$INSTANCE/dados (sudo)"
ssh -t "$HOST" "sudo rsync -a --delete --chown=\$(stat -c %U /srv/$INSTANCE):\$(stat -c %G /srv/$INSTANCE) \
    \$HOME/.sinibaldi-dados/ /srv/$INSTANCE/dados/ && echo 'Dados atualizados em /srv/$INSTANCE/dados.'"
