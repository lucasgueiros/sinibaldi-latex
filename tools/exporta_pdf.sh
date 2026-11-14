#!/usr/bin/env bash
# Exporta a obra (um volume inteiro, ou qualquer fragmento .tex) em PDF nos 4 formatos de
# diagramação (tex/formatos/, derivados de diagramacao/essencia-de-deus/):
#
#   sem-notas    livro 160×230 mm, só o corpo
#   notas-1col   livro 160×230 mm, notas de rodapé em 1 coluna
#   notas-2col   A4, notas de rodapé em 2 colunas balanceadas
#   notas-corpo  livro 160×230 mm, notas no corpo, depois do parágrafo que as chama
#
#   tools/exporta_pdf.sh vol2                       # os 4 formatos  -> build/vol2-<formato>.pdf
#   tools/exporta_pdf.sh vol1 vol2                  # os dois volumes
#   tools/exporta_pdf.sh vol2 --formato notas-2col  # um formato só (repetível)
#   tools/exporta_pdf.sh vol2/02_parte_theodicea/01_cap_existencia-de-deus.tex
#   tools/exporta_pdf.sh vol2 --regera              # refaz build/vol2.tex do TEI corrigido
#
# volN: usa volN/volN.corrigido.xml -> tools/tei2latex.py --puro -> build/volN.tex (gerado se
# faltar).  Saída em build/ (git-ignorado).  Roda da raiz do repositório.
set -euo pipefail
cd "$(dirname "$0")/.."

todos=(sem-notas notas-1col notas-2col notas-corpo)
formatos=(); alvos=(); regera=
while [[ $# -gt 0 ]]; do
  case $1 in
    --formato) formatos+=("$2"); shift 2 ;;
    --regera)  regera=1; shift ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)        echo "opção desconhecida: $1" >&2; exit 2 ;;
    *)         alvos+=("$1"); shift ;;
  esac
done
[[ ${#alvos[@]} -gt 0 ]] || { echo "uso: tools/exporta_pdf.sh vol1|vol2|<fragmento.tex> [--formato F]... [--regera]" >&2; exit 2; }
[[ ${#formatos[@]} -gt 0 ]] || formatos=("${todos[@]}")
for f in "${formatos[@]}"; do
  [[ -f tex/formatos/formato-$f.tex ]] || { echo "formato desconhecido: $f (${todos[*]})" >&2; exit 2; }
done

py=python3; [[ -x .venv/bin/python ]] && py=.venv/bin/python
mkdir -p build

for alvo in "${alvos[@]}"; do
  titulo="elementos de philosophia"
  case $alvo in
    vol1|vol2)
      stem=$alvo; frag=build/$alvo
      if [[ -n $regera || ! -f build/$alvo.tex ]]; then
        echo ">> $alvo: TEI corrigido -> build/$alvo.tex"
        $py tools/tei2latex.py "$alvo/$alvo.corrigido.xml" --puro -o "build/$alvo.tex"
      fi
      titulo="elementos de philosophia · vol. ${alvo#vol}" ;;
    *)
      alvo=${alvo%.tex}
      [[ -f $alvo.tex ]] || { echo "não existe: $alvo.tex" >&2; exit 1; }
      stem=$(basename "$alvo"); frag=$alvo ;;
  esac
  for f in "${formatos[@]}"; do
    job=$stem-$f
    echo ">> $alvo [$f] -> build/$job.pdf"
    latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=build -jobname="$job" \
      -usepretex="\\def\\fragmento{$frag}\\def\\titulocorrente{$titulo}" \
      "tex/formatos/formato-$f.tex" >"build/$job.latexmk.log" 2>&1 \
      || { tail -30 "build/$job.latexmk.log" >&2; echo "latexmk falhou: build/$job.log" >&2; exit 1; }
    echo "   pronto: build/$job.pdf ($(pdfinfo "build/$job.pdf" | awk '/^Pages/{print $2}') páginas, $(pdfinfo "build/$job.pdf" | awk '/Page size/{print $3"×"$5" pt"}'))"
  done
done
