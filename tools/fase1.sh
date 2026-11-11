#!/usr/bin/env bash
# Fase 1 completa: PDF -> PNG por pagina -> OCR (txt/tsv/hocr) -> paginas.tsv -> TEI bruto.
#
#   tools/fase1.sh vol2 [--primeira N --ultima M]   # intervalo de FOLHAS, para teste
#
# Retomavel: cada etapa pula o que ja existe.  Roda da raiz do repositorio.
set -euo pipefail
cd "$(dirname "$0")/.."
vol=${1:?uso: fase1.sh vol1|vol2 [--primeira N] [--ultima M]}
shift
case $vol in
  vol1) pdf=vol1.pdf;      offset=15; titulo="Elementos de Philosophia, vol. 1 (Logica, Ontologia, Cosmologia)"; ano=1917 ;;
  vol2) pdf=vol2/vol2.pdf; offset=-1; titulo="Elementos de Philosophia, vol. 2 (Antropologia, Theodicea, Moral)"; ano=1916 ;;
  *) echo "volume desconhecido: $vol" >&2; exit 2 ;;
esac
[[ -f $pdf ]] || { echo "falta $pdf" >&2; exit 1; }
if [[ -z ${TESSDATA_PREFIX:-} && -d tessdata ]]; then export TESSDATA_PREFIX=$PWD/tessdata; fi
pasta=$vol/paginas
python3 tools/extrai_paginas.py "$pdf" -o "$pasta" --offset "$offset" "$@"
python3 tools/ocr_paginas.py "$pasta"
python3 tools/paginas2tei.py "$pasta" -o "$vol/$vol.xml" --titulo "$titulo" --ano "$ano"
