# Numeração de páginas: o problema e a solução

## O problema relatado

Depois de `mutool poster` → `ocrmypdf` → `pdftotext`, "perdeu-se o número das páginas": o `vol1.txt`
é um fluxo contínuo e os números impressos que aparecem nele vêm do OCR do cabeçalho, quase sempre
corrompidos (`1s6`, `%66`, `s66`, `Bs7`).

## Constatação: a informação **não** foi perdida

Duas coisas separadas foram confundidas:

1. **Onde cada página começa** — isso está preservado. `pdftotext` insere um **form feed (`\f`)** a
   cada quebra de página. `vol1.txt` tem 924 blocos + um `\f` final, batendo exatamente com as 924
   páginas de `vol1_div_ocr.pdf`. Nenhuma reextração é necessária.
2. **Qual é o número impresso naquela página** — isso não precisa vir do OCR. A relação com o índice
   da página no PDF é **constante**.

## O mapeamento (vol. 1)

```
página impressa = página do PDF − 15
```

Verificado em amostras limpas espalhadas por todo o volume:

| pdf | cabeçalho OCR | impressa |
|---|---|---|
| 21 | `6  ... INTRODUCÇÃO` | 6 |
| 41 | `26 ... LOGICA` | 26 |
| 121 | `106 ... LÓGICA SECÇÃO SEGUNDA` | 106 |
| 361 | `346 ... METAPHYSICA` | 346 |
| 601 | `586 ... COSMOLOGIA` | 586 |
| 881 | `s66 ... METAPHYSICA` | 866 |

Coerente nas pontas: a página impressa 1 é o pdf 16 (início da `INTRODUCÇÃO`), e a última página do
corpo é a impressa 909 = pdf 924. A numeração é **contínua** por todo o volume (Logica, Ontologia e
Cosmologia não reiniciam a contagem).

**Front matter** (pdf 1–15) tem numeração romana própria: `pdf 13 = XIV`, `pdf 15 = XVI`, logo
`romano = pdf + 1`. Baseado em apenas duas amostras legíveis — confiança baixa, mas são 15 páginas de
prefácio, de pouco impacto.

## Por que não ler o número do OCR

O número calculado confere literalmente com o cabeçalho OCR em apenas **200 de 909 páginas (22%)** —
os dígitos do cabeçalho são a parte pior digitalizada da página (fonte pequena, perto da margem, borda
da folha cortada pelo `mutool poster`). Portanto:

> A aritmética é a fonte de verdade; o OCR do cabeçalho serve só para conferência.

## A alternativa proposta: `tools/extract_paginado.py`

Extrai o texto já **etiquetado por página**, derivando o número impresso do índice do PDF:

```bash
# volume inteiro, etiquetado
python3 tools/extract_paginado.py vol1_div_ocr.pdf > vol1_pag.txt

# reaproveitando o vol1.txt que já existe (não roda pdftotext de novo)
python3 tools/extract_paginado.py vol1.txt --from-txt -f 300 -l 302

# conferir o mapeamento contra o OCR (relatório de divergências)
python3 tools/extract_paginado.py vol1.txt --from-txt --check
```

Saída:

```
<<<PAG 285 pdf=300>>>
... texto da página ...
<<<PAG 286 pdf=301>>>
```

Front matter sai como `<<<PAG fm-XIV pdf=13>>>`. O parâmetro `--offset` (padrão 15) e `--offset-fm`
(padrão −1) permitem reusar o script no vol. 2, depois de descobrir o offset dele pelo mesmo método:
achar uma página com cabeçalho legível e subtrair.

## Alternativas descartadas

- **`pdftotext -f N -l N` em laço** (uma chamada por página): funciona e é imune a `\f`, mas são 924
  invocações sobre um PDF de 100 MB — muito mais lento, sem ganho.
- **hOCR/ALTO do Tesseract** (`ocrmypdf --sidecar` + coordenadas): daria para localizar e remover o
  cabeçalho corrente pela posição na página, e não só por heurística de texto. Vale se a limpeza dos
  cabeçalhos/rodapés virar gargalo na revisão; hoje é complexidade desnecessária.
- **Confiar no número OCR** com correção por vizinhança (interpolar a partir das páginas legíveis):
  reinventa, com risco, o que a aritmética já dá de graça.
