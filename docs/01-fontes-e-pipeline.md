# Fontes e pipeline de digitalização

## Objetivo do projeto

1. Gerar um **LaTeX do livro** (Sinibaldi, *Elementos de Philosophia* — Logica, Ontologia,
   Cosmologia; 5.ª edição, Roma, 1897, em português pré-1911).
2. A partir desse LaTeX, montar **slides de trechos específicos**, sem duplicar texto (`docs/05`).
3. O número da **página impressa** deve aparecer no texto em LaTeX na forma `[286]`.

O volume é dividido em nós hierárquicos (`volN/parte/secção/capítulo/…`), cada um com o seu
recorte de PDF/texto, o seu `.tex` e o seu slide — ver `docs/05-estrutura-por-no.md`.

## Arquivos

| Arquivo | Papel |
|---|---|
| `vol1.pdf` | Scan original, vol. 1. 462 folhas A4 **paisagem**, 2 páginas do livro por folha. Sem camada de texto. |
| `vol1_div.pdf` | `vol1.pdf` cortado ao meio → 924 páginas A5, uma página do livro cada. Sem camada de texto. |
| `vol1_div_ocr.pdf` | `vol1_div.pdf` após OCRmyPDF 17.11 / Tesseract 5.5 → 924 páginas **com** camada de texto. |
| `vol1.txt` | Texto de `vol1_div_ocr.pdf` via `pdftotext -layout`. OCR antigo, sem latim — só comparação. |
| `vol1_lat.txt` | Texto `por_best+lat` etiquetado (`docs/04`). **Nunca foi gerado** para o vol. 1 (o único artigo transcrito veio de OCR ad-hoc); o plano vale para o vol. 2. |
| `tessdata/` | tessdata local (git-ignored): links do sistema + `lat` (best) e `por_best` (`docs/04`). |
| `vol2.pdf` | Scan do vol. 2 (Psicologia). 413 páginas, ~637×850 pt, **sem** camada de texto. |
| `vol2_div.pdf` | `vol2.pdf` cortado ao meio (páginas rotacionadas) → 826 páginas, uma do livro cada. |
| `vol2_div_ocr.pdf` | `vol2_div.pdf` após `ocrmypdf -l por_best+lat --rotate-pages --deskew`. |
| `vol2_pag.txt` | Texto de `vol2_div_ocr.pdf` etiquetado por página impressa, com `w→u` (`extract_paginado.py --corrige-w`). |

Os PDFs grandes (80–210 MB) são a única cópia do material — nunca sobrescrever no lugar.

## Pipeline usado no vol. 1

```bash
mutool poster -x 2 vol1.pdf vol1_div.pdf          # 1. cortar as folhas 2-up
ocrmypdf -l por vol1_div.pdf vol1_div_ocr.pdf     # 2. OCR em português
pdftotext -layout vol1_div_ocr.pdf vol1.txt       # 3. extrair texto
```

Ferramentas: `mutool` e `pdfseparate` para cortar PDF (**não** há `qpdf` nem `pdftk`); `ocrmypdf`
(17.11, em `.venv/`), `tesseract` 5.5 (tessdata do sistema: `eng lat osd por`), `pdftotext`,
`pdfinfo`, `latexmk`+`lualatex`, TeX Live completo. **Não** há `node`/`marp`/`pandoc`.

Passos 1–2 são demorados. Rodar em background e nunca repetir só para conferir algo — ler `vol1.txt`
ou extrair uma faixa: `pdftotext -layout -f 120 -l 125 vol1_div_ocr.pdf -`.

## Vol. 2 (em andamento)

`vol2_div.pdf` já existe: as folhas do vol. 2 **são** 2-up, mas rotacionadas, então o corte foi
`mutool poster -y 2` (não `-x 2`) → 826 páginas. O OCR foi refeito com o modelo de latim desde o
início (o vol. 1 concluiu em `docs/04` que o ganho vem de `lat`+`por_best`):

```bash
export TESSDATA_PREFIX=$PWD/tessdata TMPDIR=$PWD/ocr_tmp   # ocr_tmp/ em disco real (ver MEMORY.md)
.venv/bin/ocrmypdf -l por_best+lat --rotate-pages --deskew vol2/vol2_div.pdf vol2/vol2_div_ocr.pdf
```

Depois: descobrir o OFFSET de página (`docs/02`), gerar `vol2_pag.txt`
(`extract_paginado.py --corrige-w`) e subdividir em nós (`docs/05`).

## Qualidade do OCR — o texto é bruto

`vol1.txt` **não foi revisado**; a taxa de erro é alta e tudo que for transcrito precisa ser conferido
contra a imagem da página. Armadilhas recorrentes:

- **Ortografia pré-1911 está correta**, não é erro: `philosophia`, `immutavel`, `sciencia`, `elle`.
  Não modernizar a grafia salvo pedido explícito.
- **Citações latinas** de S. Tomás, no corpo e em notas. Refeitas com modelo de latim em
  `vol1_lat.txt` (`docs/04-ocr-latim.md`); melhoraram muito, mas ainda erram.
- Notas de rodapé `(1)`, `(2)` são intercaladas no corpo pelo `pdftotext`; cabeçalhos correntes
  (`METAPHYSICA — PARTE PRIMEIRA — ONTOLOGIA`) e números de página caem no meio do fluxo.
- Parágrafos numerados do autor (`88.`, `89.`, …) são a estrutura do livro e a âncora natural para o
  seccionamento em LaTeX — mas os dígitos deles são frequentemente mal lidos.
- Acentos, `ç` e itálicos são pouco confiáveis; os índices no fim do volume estão quase ilegíveis.
