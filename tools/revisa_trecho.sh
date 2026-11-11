#!/usr/bin/env bash
# Passa um agente LLM (claude -p) na revisão final de um trecho, contra as imagens das páginas.
#
#   tools/revisa_trecho.sh vol2:existencia-de-deus                    # opus (padrão)
#   tools/revisa_trecho.sh vol1:divisao-do-ente --modelo sonnet
#   tools/revisa_trecho.sh vol2:421-430 --modelo haiku --saida /tmp/rev
#   tools/revisa_trecho.sh vol2:t6..t8 --entrada meu.tex              # revisa um .tex já existente
#   tools/revisa_trecho.sh vol2:421-430 --so-prompt                   # só mostra o prompt montado
#
# O que faz:
#   1. tools/trecho.py SELETOR -F tex  (ou copia --entrada) -> SAIDA/entrada.tex
#   2. monta o prompt de tools/prompts/revisao_trecho.md (páginas tiradas dos \pg do .tex)
#   3. roda `claude -p` num diretório temporário FORA do repositório: o agente não herda CLAUDE.md,
#      memória, MCP nem esta sessão; só pode ler o .tex, as imagens (--add-dir) e os recortes que
#      gravar ali.  Com ANTHROPIC_API_KEY no ambiente usa também --bare.
#   4. SAIDA/revisado.tex, SAIDA/relatorio.md (resposta final), SAIDA/resultado.json (custo, turnos,
#      duração, tokens) e, se o trecho cobre um padrão-ouro (docs/07), SAIDA/wer.txt antes/depois.
# Saída padrão: revisao/<seletor>/<modelo>/   Roda da raiz do repositório (ou de qualquer lugar).
set -euo pipefail
cd "$(dirname "$0")/.."
RAIZ=$PWD
sel=${1:?uso: revisa_trecho.sh volN:SELETOR [--modelo opus|sonnet|haiku|ID] [--saida DIR] [--entrada TEX] [--imagens DIR] [--so-prompt]}
shift
modelo=opus; saida=; entrada=; imagens=; so_prompt=
while [[ $# -gt 0 ]]; do
  case $1 in
    --modelo) modelo=$2; shift 2 ;;
    --saida) saida=$2; shift 2 ;;
    --entrada) entrada=$2; shift 2 ;;
    --imagens) imagens=$2; shift 2 ;;
    --so-prompt) so_prompt=1; shift ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done
vol=${sel%%:*}
[[ $vol == vol1 || $vol == vol2 ]] || { echo "o seletor precisa do volume: vol1:… ou vol2:…" >&2; exit 2; }
slug=$(echo "${sel#*:}" | tr -c 'A-Za-z0-9.\n-' '_')
saida=${saida:-revisao/$vol-$slug/$modelo}
mkdir -p "$saida"
saida=$(cd "$saida" && pwd)

# imagens: as do checkout; num worktree (PNGs git-ignorados) cai nas do checkout principal
if [[ -z $imagens ]]; then
  imagens=$RAIZ/$vol/paginas
  if ! ls "$imagens"/0*.png >/dev/null 2>&1; then
    principal=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
    imagens=$principal/$vol/paginas
  fi
fi
ls "$imagens"/0*.png >/dev/null 2>&1 || { echo "sem imagens em $imagens (tools/extrai_paginas.py)" >&2; exit 1; }
imagens=$(cd "$imagens" && pwd)

py=                                         # o agente recorta imagens: primeiro python com PIL
for c in "$RAIZ/.venv/bin/python" "$imagens/../../.venv/bin/python" "$(command -v python3)"; do
  [[ -x $c ]] && "$c" -c 'import PIL' 2>/dev/null && { py=$(cd "$(dirname "$c")" && pwd)/$(basename "$c"); break; }
done
[[ -n $py ]] || { echo "nenhum python com PIL (pip install pillow)" >&2; exit 1; }

# 1. entrada
if [[ -n $entrada ]]; then
  cp "$entrada" "$saida/entrada.tex"
else
  python3 tools/trecho.py "$sel" -F tex -o "$saida/entrada.tex" >&2
fi
paginas=$(grep -o '\\pg{[0-9]*}' "$saida/entrada.tex" | grep -o '[0-9]*' | sort -n | uniq)
p0=$(echo "$paginas" | head -n 1); p1=$(echo "$paginas" | tail -n 1)
[[ -n $p0 ]] || { echo "o .tex não tem \\pg{n}: não sei que páginas revisar" >&2; exit 1; }
desc="$vol, trecho $sel"

# 2. prompt, num diretório de trabalho fora do repositório
trabalho=$(mktemp -d "${TMPDIR:-/tmp}/revisa_trecho.XXXXXX")
mkdir -p "$trabalho/recortes"
cp "$saida/entrada.tex" "$trabalho/trecho.tex"
ARQUIVO=$trabalho/trecho.tex DESCRICAO=$desc P0=$p0 P1=$p1 IMAGENS=$imagens PYTHON=$py \
TMPRECORTES=$trabalho/recortes \
  $py -c 'import os, string, sys; print(string.Template(open(sys.argv[1]).read()).safe_substitute(os.environ))' \
  tools/prompts/revisao_trecho.md > "$saida/prompt.md"
if [[ -n $so_prompt ]]; then cat "$saida/prompt.md"; rm -rf "$trabalho"; exit 0; fi

# 3. agente
extra=(); [[ -n ${ANTHROPIC_API_KEY:-} ]] && extra+=(--bare)
echo ">> $modelo revisando $desc (pp. $p0–$p1) em $trabalho" >&2
inicio=$(date +%s)
(cd "$trabalho" && claude -p "$(cat "$saida/prompt.md")" "${extra[@]}" \
    --model "$modelo" \
    --output-format json \
    --no-session-persistence \
    --strict-mcp-config \
    --permission-mode acceptEdits \
    --add-dir "$imagens" \
    --allowedTools Read Edit Write "Bash($py:*)" \
    --disallowedTools Grep Glob WebFetch WebSearch Task Agent \
  ) > "$saida/resultado.json" || echo "claude saiu com erro (veja $saida/resultado.json)" >&2
cp "$trabalho/trecho.tex" "$saida/revisado.tex"
$py -c 'import json,sys; print(json.load(open(sys.argv[1])).get("result",""))' "$saida/resultado.json" \
  > "$saida/relatorio.md" 2>/dev/null || true
rm -rf "$trabalho"
echo ">> $(( ($(date +%s) - inicio) / 60 )) min; $(diff "$saida/entrada.tex" "$saida/revisado.tex" | grep -c '^>' || true) linhas alteradas" >&2

# 4. WER contra o padrão-ouro, se o trecho cobre algum (docs/07)
{
  for f in entrada revisado; do
    echo "== $f"
    python3 tools/mede_wer.py --vol "$vol" --tex "$saida/$f.tex" -f "$p0" -l "$p1" 2>&1 || true
  done
} > "$saida/wer.txt"
grep -q 'WER' "$saida/wer.txt" && cat "$saida/wer.txt" >&2
echo ">> $saida/revisado.tex  (relatório: relatorio.md, custo/tokens: resultado.json)" >&2
