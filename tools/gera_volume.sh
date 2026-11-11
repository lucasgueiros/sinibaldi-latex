#!/usr/bin/env bash
# Cadeia completa de UM volume, das páginas OCR ao PDF, com a formatação medida na imagem:
#
#   tools/gera_volume.sh vol2                       # volume inteiro  -> build/vol2.pdf
#   tools/gera_volume.sh vol2 -f 421 -l 442         # um trecho       -> build/vol2-421-442.pdf
#   tools/gera_volume.sh vol1 --imagens DIR         # PNGs em outro lugar (p. ex. o checkout principal)
#   tools/gera_volume.sh vol2 --sem-pdf             # para no .tex
#
# Etapas (cada uma pula o que já está feito quando dá):
#   0. imagens <id>.png          tools/extrai_paginas.py   (só se faltam; ~10 min/volume)
#   1. formatação <id>.fmt.tsv   tools/formatacao.py       (itálico/versalete/negrito; cache de medidas)
#   2. TEI estruturado           tools/estruturar_tei.py   -> volN/volN.estruturado.xml (+ <hi rend>)
#   3. correção do OCR           tools/corrige_ocr.py      -> volN/volN.corrigido.xml + volN/correcoes.tsv
#   4. LaTeX                     tools/tei2latex.py --puro -> build/volN[-P-Q].tex
#   5. PDF                       latexmk -lualatex tex/_preview.tex -> build/volN[-P-Q].pdf
# Roda da raiz do repositório.
set -euo pipefail
cd "$(dirname "$0")/.."
vol=${1:?uso: gera_volume.sh vol1|vol2 [-f P -l P] [--imagens DIR] [--sem-pdf]}
shift
case $vol in
  vol1) pdf=vol1.pdf;      offset=15; ano=1917; titulo="Elementos de Philosophia, vol. 1 (Logica, Ontologia, Cosmologia)" ;;
  vol2) pdf=vol2/vol2.pdf; offset=-1; ano=1916; titulo="Elementos de Philosophia, vol. 2 (Antropologia, Theodicea, Moral)" ;;
  *) echo "volume desconhecido: $vol" >&2; exit 2 ;;
esac
de=; ate=; imagens=$vol/paginas; pdf_final=1
while [[ $# -gt 0 ]]; do
  case $1 in
    -f) de=$2; shift 2 ;;
    -l) ate=$2; shift 2 ;;
    --imagens) imagens=$2; shift 2 ;;
    --sem-pdf) pdf_final=; shift ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done
faixa=(); sufixo=
[[ -n $de ]] && faixa+=(-f "$de")
[[ -n $ate ]] && faixa+=(-l "$ate")
[[ -n $de$ate ]] && sufixo="-${de:-ini}-${ate:-fim}"
job=$vol$sufixo
py=python3; [[ -x .venv/bin/python ]] && .venv/bin/python -c 'import numpy, lxml, PIL' 2>/dev/null && py=.venv/bin/python

echo ">> 0. imagens ($imagens)"
if ! ls "$imagens"/*.png >/dev/null 2>&1 || [[ $(ls "$imagens"/*.png | wc -l) -lt $(($(wc -l < $vol/paginas/manifesto.tsv) - 1)) && -z $de$ate ]]; then
  [[ -f $pdf ]] || { echo "faltam imagens e o scan $pdf" >&2; exit 1; }
  $py tools/extrai_paginas.py "$pdf" -o "$imagens" --offset "$offset"
fi

echo ">> 1. formatação"
$py tools/formatacao.py "$vol/paginas" --imagens "$imagens" "${faixa[@]}"

echo ">> 2. TEI estruturado"
xml=$vol/$vol.estruturado.xml
[[ -n $sufixo ]] && xml=build/$job.estruturado.xml
mkdir -p build
$py tools/estruturar_tei.py "$vol/paginas" -o "$xml" --ano "$ano" --titulo "$titulo" "${faixa[@]}"

echo ">> 3. correção do OCR"
cor=${xml%.estruturado.xml}.corrigido.xml
$py tools/corrige_ocr.py "$xml" -o "$cor"

echo ">> 4. LaTeX"
$py tools/tei2latex.py "$cor" --puro -o "build/$job.tex"
[[ -n $pdf_final ]] || { echo ">> pronto: build/$job.tex"; exit 0; }

echo ">> 5. PDF"
latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=build -jobname="$job" \
  -usepretex="\\def\\fragmento{build/$job}" tex/_preview.tex >"build/$job.latexmk.log" 2>&1 \
  || { tail -40 "build/$job.latexmk.log" >&2; echo "latexmk falhou: build/$job.log" >&2; exit 1; }
echo ">> pronto: build/$job.pdf ($(pdfinfo "build/$job.pdf" | awk '/^Pages/{print $2}') páginas)"
