# Fontes e pipeline de digitalização

## Objetivo do projeto

1. Gerar um **LaTeX do livro** (Sinibaldi, *Elementos de Philosophia* — Logica, Ontologia,
   Cosmologia; 5.ª edição, Roma, 1897, em português pré-1911).
2. A partir desse LaTeX, montar **slides (beamer) de trechos específicos**, sem duplicar texto.
3. O número da **página impressa** deve aparecer no texto em LaTeX na forma `[286]`.

## Arquivos

| Arquivo | Papel |
|---|---|
| `vol1.pdf` | Scan original, vol. 1. 462 folhas A4 **paisagem**, 2 páginas do livro por folha. Sem camada de texto. |
| `vol1_div.pdf` | `vol1.pdf` cortado ao meio → 924 páginas A5, uma página do livro cada. Sem camada de texto. |
| `vol1_div_ocr.pdf` | `vol1_div.pdf` após OCRmyPDF 16.7 / Tesseract 5.5 → 924 páginas **com** camada de texto. |
| `vol1.txt` | Texto de `vol1_div_ocr.pdf` via `pdftotext -layout`. OCR antigo, sem latim — só comparação. |
| `vol1_lat.txt` | **Texto de trabalho.** OCR refeito com `por_best+lat`, etiquetado por página (`docs/04`). |
| `tessdata/` | tessdata local: links do sistema + `lat` e `por_best` baixados (`docs/04`). |
| `vol2.pdf` | Scan do vol. 2. 413 páginas, ~637×850 pt, **sem** camada de texto. Ainda não cortado nem OCR'd. |

Os PDFs grandes (80–210 MB) são a única cópia do material — nunca sobrescrever no lugar.

## Pipeline usado no vol. 1

```bash
mutool poster -x 2 vol1.pdf vol1_div.pdf          # 1. cortar as folhas 2-up
ocrmypdf -l por vol1_div.pdf vol1_div_ocr.pdf     # 2. OCR em português
pdftotext -layout vol1_div_ocr.pdf vol1.txt       # 3. extrair texto
```

Ferramentas disponíveis: `mutool`, `ocrmypdf`, `tesseract` (tessdata: `eng`, `por`, `osd` apenas),
`pdftotext`, `pdfinfo`, TeX Live completo. **Não** há `qpdf` nem `pdftk`.

Passos 1–2 são demorados. Rodar em background e nunca repetir só para conferir algo — ler `vol1.txt`
ou extrair uma faixa: `pdftotext -layout -f 120 -l 125 vol1_div_ocr.pdf -`.

## Para o vol. 2

Antes de repetir o pipeline, conferir se as páginas também são 2-up (o tamanho de página é diferente
do vol. 1); se não forem, pular o `mutool poster`.

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
