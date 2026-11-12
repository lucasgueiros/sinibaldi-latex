#!/usr/bin/env bash
# Comparação de modelos, revisão POR PÁGINA (tools/revisa_paginas.py: uma chamada de 1 turno por página).
#   revisao-modelos/roda_por_pagina.sh [modelos...]      # padrão: haiku sonnet opus
# vol. 2: capítulo inteiro (o ouro cobre 421-442).  vol. 1: o ouro só cobre 331-334, então Haiku faz o
# capítulo inteiro e os outros só esses pedaços (--so), para não pagar páginas que não dá para medir.
# Retoma: pedaços já gravados em revisao-modelos/por-pagina/<m>/<vol>/paginas/ não são refeitos.
# Depois: python3 revisao-modelos/compara.py revisao-modelos/por-pagina
set -uo pipefail
cd "$(dirname "$0")/.."
modelos=("$@"); [[ $# -eq 0 ]] && modelos=(haiku sonnet opus)
for m in "${modelos[@]}"; do
  (
    python3 tools/revisa_paginas.py revisao-modelos/entrada/vol2.tex --vol vol2 --modelo "$m" \
      --saida "revisao-modelos/por-pagina/$m/vol2" --paralelo 3
    so=(--so 331-334); [[ $m == haiku ]] && so=()
    python3 tools/revisa_paginas.py revisao-modelos/entrada/vol1.tex --vol vol1 --modelo "$m" \
      --saida "revisao-modelos/por-pagina/$m/vol1" --paralelo 3 "${so[@]}"
  ) > "revisao-modelos/por-pagina/$m.log" 2>&1 &
done
wait
grep -h '^>> .*pedaços' revisao-modelos/por-pagina/*.log
echo "pronto: python3 revisao-modelos/compara.py revisao-modelos/por-pagina"
