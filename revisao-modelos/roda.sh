#!/usr/bin/env bash
# Comparação de modelos na revisão final: cada modelo revisa os mesmos dois capítulos (mesma
# entrada, mesmo prompt), em sessões claude -p isoladas (tools/revisa_trecho.sh), em paralelo.
#   revisao-modelos/roda.sh [modelos...]        # padrão: opus sonnet haiku
# Depois: python3 revisao-modelos/compara.py
set -uo pipefail
cd "$(dirname "$0")/.."
modelos=("${@:-opus sonnet haiku}"); [[ $# -eq 0 ]] && modelos=(opus sonnet haiku)
declare -A SEL=([vol2]=vol2:existencia-de-deus [vol1]=vol1:divisao-do-ente)
for m in "${modelos[@]}"; do
  for v in vol2 vol1; do
    rm -rf "revisao-modelos/$m/$v"; mkdir -p "revisao-modelos/$m/$v"
    tools/revisa_trecho.sh "${SEL[$v]}" --modelo "$m" --entrada "revisao-modelos/entrada/$v.tex" \
      --saida "revisao-modelos/$m/$v" > "revisao-modelos/$m/$v/log.txt" 2>&1 &
  done
done
wait
echo "pronto: python3 revisao-modelos/compara.py"
