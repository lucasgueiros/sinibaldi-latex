#!/bin/sh
# Revisão Haiku de uma faixa de páginas impressas do vol. 2:  revisao/roda_faixa.sh A B [args extras do revisa_paginas]
# Saída em revisao/vol2/A-B/.  Retoma de onde parou.
cd "$(dirname "$0")/.." || exit 1
A=$1; B=$2; shift 2
D=revisao/vol2/$A-$B
mkdir -p "$D"
[ -s "$D/entrada.xml" ] || python3 tools/trecho.py vol2:$A-$B -F tei -o "$D/entrada.xml" || exit 1
python3 tools/revisa_paginas.py "$D/entrada.xml" --vol vol2 --saida "$D" \
  --volume vol2/vol2.corrigido.xml --paralelo 3 "$@" >> "$D/log.txt" 2>&1
