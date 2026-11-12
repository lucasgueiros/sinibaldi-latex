#!/usr/bin/env bash
# Revisão POR PÁGINA sobre o TEI (tools/revisa_paginas.py: uma chamada de 1 turno por pedaço), medida
# nos padrões-ouro.  Entradas: revisao-modelos/entrada/volN.xml (tools/trecho.py … -F tei).
#   revisao-modelos/roda_por_pagina.sh [modelos...]      # padrão: haiku
# vol. 2: capítulo inteiro (o ouro cobre 421-442).  vol. 1: capítulo inteiro de Haiku; outros modelos só
# os pedaços que o ouro (331-334) cobre (--so), para não pagar páginas que não dá para medir.
# Retoma: pedaços já gravados em revisao-modelos/por-pagina-xml/<m>/<vol>/paginas/ não são refeitos.
# Depois: python3 revisao-modelos/compara.py revisao-modelos/por-pagina-xml
# (A rodada sobre o .tex, de antes da mudança para TEI, está em revisao-modelos/por-pagina/.)
set -uo pipefail
cd "$(dirname "$0")/.."
modelos=("$@"); [[ $# -eq 0 ]] && modelos=(haiku)
saida=revisao-modelos/por-pagina-xml
mkdir -p "$saida"
for m in "${modelos[@]}"; do
  (
    python3 tools/revisa_paginas.py revisao-modelos/entrada/vol2.xml --vol vol2 --modelo "$m" \
      --saida "$saida/$m/vol2" --paralelo 3
    so=(--so 331-334); [[ $m == haiku ]] && so=()
    python3 tools/revisa_paginas.py revisao-modelos/entrada/vol1.xml --vol vol1 --modelo "$m" \
      --saida "$saida/$m/vol1" --paralelo 3 "${so[@]}"
  ) > "$saida/$m.log" 2>&1 &
done
wait
grep -h '^>> .*pedaços' "$saida"/*.log
echo "pronto: python3 revisao-modelos/compara.py $saida"
