# Revisão do OCR: línguas estrangeiras (latim)

## O problema

O OCR original rodou com `-l por` apenas, e o sistema só tinha tessdata `eng`, `por`, `osd`. O livro é
denso em **citações latinas** de S. Tomás (corpo e notas de rodapé), que ficaram a parte pior
reconhecida de `vol1.txt`.

Além disso, o `por.traineddata` do Debian é a variante **fast** (1,9 MB), menos precisa que a **best**
(8,2 MB).

## O que foi feito

`tessdata/` local (sem `sudo`, não mexe no sistema), com links para o tessdata do sistema mais:

- `lat.traineddata` — modelo de latim, de `tessdata_best`;
- `por_best.traineddata` — português na variante *best*.

```bash
export TESSDATA_PREFIX=$PWD/tessdata     # necessário para o tesseract enxergar os dois
tesseract --list-langs                   # eng lat osd por por_best
```

**Armadilha:** com `TESSDATA_PREFIX` apontando para o `tessdata/` local, o `ocrmypdf` quebra logo no
início com `read_params_file: Can't open hocr` / `TesseractConfigError` — ele chama
`tesseract … hocr txt`, e `hocr`/`txt` são *arquivos de config* que o tesseract procura em
`tessdata/configs/`. A pasta local não tinha isso. Solução: linkar do sistema também
`configs`, `tessconfigs` e `pdf.ttf`, não só os `.traineddata`.

## Medição (não é achismo)

Amostras: pdf 335 (impressa 320) e pdf 618 (impressa 603), as páginas com mais latim do volume.

| configuração | conf. média | palavras conf.<60 |
|---|---|---|
| `por` (linha de base, gerou `vol1.txt`) | 82,3 | 96 |
| `por_best` | 82,1 | 101 |
| **`por_best+lat`** | **86,9** | **62** |
| `lat` sozinho | 82,0 | 97 |

Na pdf 618: `por` 79,7 / 94 → `por_best+lat` 85,0 / 73. A ordem das línguas (`lat+por_best`) não muda
nada. Note que `por_best` sozinho **não** ajuda: o ganho vem do modelo de latim.

Confiança não é acurácia, então conferi o texto. Correções reais no latim:

| `por` | `por_best+lat` |
|---|---|
| `nibil` | `nihil` |
| `potertiale` | `potentiale` |
| `sequilur` | `sequitur` |
| `alind im eo` | `aliud in eo` |
| `muanifestum` | `manifestum` |
| `vportet` | `oportet` |
| `guinditas` | `quidditas` |
| `negue` | `neque` |
| `De poê., q. t` | `De pot., q. 1` |

## Confiança não ordena qualidade

Testei também `por+lat` (português *fast* + latim *best*): confiança **melhor** que `por_best+lat`
(88,0 e 50 palavras abaixo de 60, contra 86,9 e 62). No texto, porém, é **pior** no que interessa:

| | `por_best+lat` | `por+lat` |
|---|---|---|
| referência tomista | `q. 3, a. 4` (correta) | `q. 1, a. 4` |
| termo técnico | `quidditas` | `guwidditas` |
| | `sit alid` | `sil altud` |

Por isso a escolha final é **`por_best+lat`**, e por isso toda configuração candidata foi conferida
no texto, não só pela métrica de confiança.

## A armadilha do `w`

O modelo `lat` introduz um erro próprio: lê `u` como `w` (`hwmanae`, `pwrwm`, `veceptwm`). A letra `w`
não existe no alfabeto latino, então toda ocorrência em citação é erro.

Testei `-c tessedit_char_blacklist=wW`: funciona com o LSTM (zera os `w`), mas **não** é a melhor
opção. Comparando as duas saídas, só 4 linhas divergem, e a substituição ingênua `w→u` ganha em 3
delas (`acíualitas` vs `acinalitas`, `acíu` vs `acix`, `infinituis` vs `infinituir`); o blacklist só
ganha numa (`receptum` vs `veceptum`).

Decisivo: **`w` é legítimo no livro** — `Darwin` (26×), `Newton` (11×), `Wolf` (10×), `Edwards` (9×).
Um blacklist global destruiria esses nomes. Por isso a correção é pós-processamento com whitelist de
nomes próprios (`NOMES_COM_W` em `tools/corrige_w.py`, usado por `ocr_paginado.py` e por
`extract_paginado.py --corrige-w`), não blacklist no OCR.

Curiosidade útil: a confusão `u`→`w` **já existia** na linha de base — `vol1.txt` tem `wma` (21×),
`wniversal` (15×), `wm` (12×), `ow` (17×). A correção vale para os dois OCRs.

## Por que não refazer o `ocrmypdf`

Refazer o PDF pesquisável com `ocrmypdf` custa ~100 s de CPU por página (rasterização, processamento
de imagem e reempacotamento) — e ainda entrega um PDF, não o texto etiquetado que a transcrição usa.

Como o que o projeto precisa é o **texto** para transcrever em LaTeX — e `vol1_div_ocr.pdf` já serve
para conferir na imagem —, `tools/ocr_paginado.py` roda `pdftoppm | tesseract` direto, em paralelo:

```bash
TESSDATA_PREFIX=$PWD/tessdata python3 tools/ocr_paginado.py vol1_div.pdf -o vol1_lat.txt --jobs 8
```

Custo medido: **25 páginas em 4,4 min com `--jobs 6`**, ou seja ≈ **2,7 h** para as 924 páginas. O
gargalo é o modelo `lat` na variante *best*, que é lento. Roda em background sem atrapalhar.

A saída já vem etiquetada (`<<<PAG 320 pdf=335>>>`), com a numeração de
`docs/02-numeracao-de-paginas.md`, e com o `w→u` aplicado.

> **Como não medir**: `tesseract img.png /dev/null -l ...` não mede nada — o tesseract acrescenta
> `.txt` ao nome de saída, falha na hora e "termina" em 0,7 s. Uma estimativa de 5 min para o volume
> saiu daí. Sempre medir com um caminho de saída válido.

## Estado dos arquivos de texto

- `vol1.txt` — OCR antigo (`por` fast), **sem** latim. Mantido para comparação.
- `vol1_lat.txt` — **nunca foi gerado.** O único artigo do vol. 1 transcrito até agora
  (`Artigo III.tex`) saiu de um OCR ad-hoc por artigo, não deste pipeline.

## Vol. 2

O PDF pesquisável do vol. 2 já foi feito com `ocrmypdf -l por_best+lat` (o modelo de latim desde o
início), então `tools/ocr_paginado.py` passa a ser o recurso **sob demanda** para páginas em que o
latim ainda sair ruim. A correção `w→u` no texto do volume inteiro vem de
`extract_paginado.py --corrige-w`. O `tessdata/` (links do sistema + `lat` best + `por_best`) foi
reconstruído; é git-ignored.

## Limites

- O latim melhorou muito, mas não está limpo: `conírahuntur` (por `contrahuntur`), `esl`, `sil`,
  `Lerminatam` persistem. Revisão humana contra a imagem continua obrigatória.
- O `lat.traineddata` é treinado em latim de tipografia moderna; este livro é de 1897, com itálico
  pesado nas citações, o que explica o resto do erro.
- Grego, se houver no volume, continua sem modelo (`grc` não foi instalado). Não encontrei ocorrências
  relevantes, mas não fiz varredura exaustiva.

## Nota de desempenho

Cada processo do `tesseract` é multithread por padrão. Rodando N páginas em paralelo, isso
oversubscreve os núcleos (observei *load average* 34 numa máquina de 8). `tools/ocr_paginado.py` fixa
`OMP_THREAD_LIMIT=1` em cada worker; o paralelismo vem do `--jobs`.
