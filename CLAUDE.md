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
| `vol1_div_ocr.pdf` | `vol1_div.pdf` after OCRmyPDF 16.7 / Tesseract 5.5 → same 924 pages **with** a text layer. |
| `vol1.txt` | Texto do OCR antigo (`por` fast, sem latim), 924 páginas separadas por form feed. Só para comparação. |
| `vol1_lat.txt` | **Texto a usar.** OCR refeito com `por_best+lat`, etiquetado por página, com `w→u` corrigido. |
| `tessdata/` | tessdata local (links do sistema + `lat` e `por_best` baixados). Exportar `TESSDATA_PREFIX=$PWD/tessdata`. |
| `vol2.pdf` | Original scan, vol. 2. 413 pages, ~637×850 pt, **no text layer** — not yet split or OCR'd. |
| `.python-version` | pyenv pin: Python 3.11. No `pyproject.toml`/venv exists yet. |

The large PDFs (80–210 MB) are the only copy of the source material — never overwrite them in place; write
derived files under new names.

## Pipeline

Vol. 1 was produced by the chain below (reconstructed from PDF metadata — reuse it for vol. 2, whose page
layout must be checked first: it may or may not be 2-up like vol. 1).

```bash
# 1. split each 2-up landscape sheet into two portrait pages (mutool is the available tool; no qpdf/pdftk)
mutool poster -x 2 vol1.pdf vol1_div.pdf

# 2. OCR in Portuguese (only eng/por/osd tessdata are installed)
ocrmypdf -l por --rotate-pages --deskew vol1_div.pdf vol1_div_ocr.pdf

# 3. extract text keeping the printed layout (this is what vol1.txt looks like)
pdftotext -layout vol1_div_ocr.pdf vol1.txt

# inspect a page range without re-running anything expensive
pdftotext -layout -f 120 -l 125 vol1_div_ocr.pdf -
```

Steps 1–2 take a long time on these files; run them in the background and never re-run them just to check
something — read `vol1.txt` or extract a page range instead.

## Working with the OCR text

`vol1_lat.txt` is **raw, uncorrected OCR** and the error rate is high. Anything transcribed from it must be
proofread against the page image, not trusted as-is. Recurring hazards:

- **Pre-1911 Portuguese orthography** is correct, not a typo: `philosophia`, `theologia`, `immutavel`,
  `sciencia`, `elle`, `nós`. Do **not** modernize spelling unless explicitly asked.
- Long **Latin quotations** from St. Thomas appear inline and in footnotes. The OCR was redone with a
  Latin model (`por_best+lat` → `vol1_lat.txt`) and improved a lot, but still needs proofreading. See
  `docs/04-ocr-latim.md`, including the `w` trap: the `lat` model reads `u` as `w`, yet `w` is
  legitimate in `Darwin`/`Newton`/`Wolf`, so the fix is post-processing with a name whitelist, not a
  character blacklist.
- Footnotes are numbered `(1)`, `(2)` per page and are interleaved into the body text by `pdftotext`;
  running headers (e.g. `38 — METAPHYSICA — PARTE PRIMEIRA — ONTOLOGIA`) and page numbers land mid-stream.
- Numbered paragraphs/theses (`88.`, `89.`, …) are the book's own structure and the natural anchor for
  LaTeX sectioning; digits in them are frequently misread.
- Accents, `ç`, and italics are unreliable; tables of contents at the end are largely garbage.

## Numeração de páginas

O número da página impressa **não** se perde no `pdftotext`: as quebras estão nos form feeds (`\f`) e
o número impresso é aritmético — `impressa = página do PDF − 15` no vol. 1 (constante do início ao
fim). Os dígitos do cabeçalho OCR conferem em só 22% das páginas: **não os use como fonte**.
Detalhes e verificação em `docs/02-numeracao-de-paginas.md`.

```bash
python3 tools/extract_paginado.py vol1.txt --from-txt -f 300 -l 305   # texto etiquetado por página
python3 tools/extract_paginado.py vol1.txt --from-txt --check         # conferir o offset
```

## LaTeX

O escopo vai até o **PDF do livro**: `livro.tex` + fontes em `tex/`, compilado com
`latexmk -lualatex`. `\pg{286}` imprime `[286]` no fluxo do texto, marcando a quebra de página do
original. Os **slides serão feitos em PPTX por LLM** a partir do texto revisado — não existe pipeline
LaTeX → slides e não se deve construir um. Ver `docs/03-latex-e-slides.md`.

## Convenções do projeto

Vale a metodologia global de `~/.claude/CLAUDE.md`: notas estáveis em `docs/` (índice em
`docs/README.md`), planos de tarefa em `.claude/plans/<tema>/`. Consultar `docs/` antes de reabrir
PDF ou reprocessar OCR.
