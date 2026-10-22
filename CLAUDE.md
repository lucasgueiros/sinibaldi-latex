# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Not a software project: this is a **book digitization / re-typesetting workspace**. The goal implied by the
directory name (`sinibaldi-latex`) is to turn scanned PDFs of D. Thiago Sinibaldi's *Elementos de Philosophia*
(Logica – Ontologia – Cosmologia, 5th ed., Roma, 1897, Portuguese) into LaTeX.

There is no build system, no test suite and no source tree yet — only scan inputs and OCR intermediates.
Do not look for one; the "code" here is whatever ad-hoc shell/Python you write to process the PDFs.

## Files

| File | Role |
|---|---|
| `vol1.pdf` | Original scan, vol. 1. 462 pages, A4 **landscape**, two book pages per sheet. No text layer. |
| `vol1_div.pdf` | `vol1.pdf` split down the middle → 924 A5 pages, one book page each. No text layer. |
| `vol1_div_ocr.pdf` | `vol1_div.pdf` after OCRmyPDF 17.11 / Tesseract 5.5 → same 924 pages **with** a text layer. |
| `vol1.txt` | Texto do OCR antigo (`por` fast, sem latim), 924 páginas separadas por form feed. Só para comparação. |
| `vol1_lat.txt` | OCR `por_best+lat` etiquetado — **nunca foi gerado** para o vol. 1 (ver `docs/04`). |
| `tessdata/` | tessdata local, git-ignored (links do sistema + `lat` best + `por_best`). `export TESSDATA_PREFIX=$PWD/tessdata`. |
| `vol2/` | Vol. 2 (Psicologia). `vol2.pdf` (413 pp.) → `vol2_div.pdf` (826 pp., `mutool poster -y 2`) → `vol2_div_ocr.pdf` (`ocrmypdf -l por_best+lat`). Árvore por nó: `docs/05`. |
| `.python-version` | pyenv pin: Python 3.12. `.venv/` (git-ignored) tem `ocrmypdf` e `python-pptx`. |

The large PDFs (80–210 MB) are the only copy of the source material — never overwrite them in place; write
derived files under new names.

`tools/`: `extract_paginado.py` (texto etiquetado por página impressa; `--corrige-w` para `w→u`),
`ocr_paginado.py` (re-OCR `por_best+lat` sob demanda), `corrige_w.py` (whitelist `w→u`),
`corta.py` (recorta um nó → `<stem>.pdf` + `<stem>.txt`), `trecho.py` (extrai `%%>>> id`),
`gera_slides_base.py` (`.tex` → `.slides.base.md`), `md2pptx.py` (`.slides.md` → `.pptx`).

## Pipeline

```bash
# 1. split each 2-up sheet (mutool; no qpdf/pdftk).  -x 2 no vol. 1; -y 2 no vol. 2 (folhas rotacionadas)
mutool poster -x 2 vol1.pdf vol1_div.pdf

# 2. OCR.  Vol. 1 rodou só `-l por`; vol. 2 usa o modelo de latim desde o início (docs/04)
export TESSDATA_PREFIX=$PWD/tessdata TMPDIR=$PWD/ocr_tmp
.venv/bin/ocrmypdf -l por_best+lat --rotate-pages --deskew vol2/vol2_div.pdf vol2/vol2_div_ocr.pdf

# 3. texto etiquetado por página impressa, com w→u
python3 tools/extract_paginado.py vol2/vol2_div_ocr.pdf --offset N --corrige-w > vol2/vol2_pag.txt

# inspecionar uma faixa sem reprocessar nada
pdftotext -layout -f 120 -l 125 vol2/vol2_div_ocr.pdf -
```

Steps 1–2 take a long time; run them in the background and never re-run them just to check something —
read the extracted text or `pdftotext` a page range instead.

Depois do passo 3, subdividir em nós hierárquicos (`vol2/parte/secção/capítulo/…`) com
`tools/corta.py` — cada nó carrega o seu PDF de OCR, `.txt`, `.tex` final e slide. Ver
`docs/05-estrutura-por-no.md`.

## Working with the OCR text

The OCR text (`vol1.txt`, `vol2_pag.txt`, per-node `.txt`) is **raw, uncorrected** and the error rate is
high. Anything transcribed from it must be proofread against the page image, not trusted as-is. Recurring
hazards:

- **Pre-1911 Portuguese orthography** is correct, not a typo: `philosophia`, `theologia`, `immutavel`,
  `sciencia`, `elle`, `nós`. Do **not** modernize spelling unless explicitly asked.
- Long **Latin quotations** from St. Thomas appear inline and in footnotes — the worst-OCR'd part. Vol. 2
  was OCR'd with `por_best+lat` from the start; still needs proofreading. See `docs/04-ocr-latim.md`,
  including the `w` trap: the `lat` model reads `u` as `w`, yet `w` is legitimate in
  `Darwin`/`Newton`/`Wolf`, so the fix is post-processing with a name whitelist (`tools/corrige_w.py`),
  not a character blacklist.
- Footnotes are numbered `(1)`, `(2)` per page and are interleaved into the body text by `pdftotext`;
  running headers (e.g. `38 — METAPHYSICA — PARTE PRIMEIRA — ONTOLOGIA`) and page numbers land mid-stream.
- Numbered paragraphs/theses (`88.`, `89.`, …) are the book's own structure and the natural anchor for
  LaTeX sectioning; digits in them are frequently misread.
- Accents, `ç`, and italics are unreliable; tables of contents at the end are largely garbage.

## Numeração de páginas

O número da página impressa **não** se perde no `pdftotext`: as quebras estão nos form feeds (`\f`) e
o número impresso é aritmético — `impressa = página do PDF − OFFSET` (constante por volume; vol. 1 =
15; **vol. 2 a descobrir** por uma página de cabeçalho legível). Os dígitos do cabeçalho OCR conferem
em só 22% das páginas: **não os use como fonte**. Detalhes em `docs/02-numeracao-de-paginas.md`.

```bash
python3 tools/extract_paginado.py vol2/vol2_div_ocr.pdf --offset N --check     # achar/conferir o offset
python3 tools/extract_paginado.py vol2/vol2_div_ocr.pdf --offset N -f 300 -l 305
```

## LaTeX

O escopo vai até o **PDF do livro**: `livro.tex` + fragmentos por nó (`vol2/…/<stem>.tex`, `\input`),
compilado com `latexmk -lualatex`. `\pg{286}` imprime `[286]`, marcando a quebra de página do
original; `\tese`/`\teseB`/`\sub`/`\subp` marcam a estrutura do autor. `tex/_preview.tex` compila um
nó isolado. Slides: `gera_slides_base.py` → LLM torna didático → `md2pptx.py` (não há beamer/Marp).
Ver `docs/03-latex-e-slides.md` e `docs/05-estrutura-por-no.md`.

## Convenções do projeto

Vale a metodologia global de `~/.claude/CLAUDE.md`: notas estáveis em `docs/` (índice em
`docs/README.md`), planos de tarefa em `.claude/plans/<tema>/`. Consultar `docs/` antes de reabrir
PDF ou reprocessar OCR.
