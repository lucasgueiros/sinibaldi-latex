#!/usr/bin/env bash
# Compila UM capítulo (nó volN/.../<stem>.tex) a partir da raiz do repositório.
#
#   ./compila.sh <capitulo> [--sem-notas | --notas-corpo]
#   ./compila.sh --lista      (capítulos disponíveis)
#   ./compila.sh --limpa      (apaga auxiliares de build/, mantém os PDFs)
#
# <capitulo>: caminho do .tex (com ou sem extensão) ou um pedaço do nome, p. ex.
# "existencia-de-deus".  Saída em build/<stem>.pdf (ou <stem>-sem-notas.pdf,
# <stem>-notas-corpo.pdf).  Usa tex/_preview.tex: mesmo preâmbulo do livro.
set -euo pipefail
cd "$(dirname "$0")"

lista() { find vol* -name '*.tex' -not -path '*/.*' 2>/dev/null | sort; }
uso() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-1}"; }

modo=normal; alvo=
for a in "$@"; do
  case "$a" in
    --sem-notas)   modo=sem-notas ;;
    --notas-corpo) modo=notas-corpo ;;
    --lista|-l)    lista; exit 0 ;;
    --limpa)       [[ -d build ]] && find build -type f ! -name '*.pdf' -delete; exit 0 ;;
    -h|--help)     uso 0 ;;
    -*)            echo "opção desconhecida: $a" >&2; uso ;;
    *)             [[ -z $alvo ]] || { echo "só um capítulo por vez" >&2; exit 1; }; alvo=$a ;;
  esac
done
[[ -n $alvo ]] || uso

# resolve o capítulo: caminho exato, ou busca por pedaço do nome
alvo=${alvo%.tex}
if [[ -f $alvo.tex ]]; then
  tex=$alvo.tex
else
  mapfile -t achados < <(lista | grep -F -- "$alvo" || true)
  case ${#achados[@]} in
    0) echo "nenhum capítulo casa com '$alvo'. Disponíveis:" >&2; lista >&2; exit 1 ;;
    1) tex=${achados[0]} ;;
    *) echo "'$alvo' é ambíguo:" >&2; printf '  %s\n' "${achados[@]}" >&2; exit 1 ;;
  esac
fi

stem=$(basename "$tex" .tex)
pretex="\\def\\fragmento{${tex%.tex}}"
job=$stem
case $modo in
  sem-notas)   pretex+='\def\semnotas{}';      job+=-sem-notas ;;
  notas-corpo) pretex+='\def\notascorridas{}'; job+=-notas-corpo ;;
esac

echo ">> $tex  ->  build/$job.pdf"
latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=build \
  -jobname="$job" -usepretex="$pretex" tex/_preview.tex
echo ">> pronto: build/$job.pdf"
