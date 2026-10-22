# Árvore por nó: dividir o volume antes de montar o livro

Cada volume é subdividido **recursivamente** — livro inteiro → parte → secção →
capítulo → subsecção — e cada nó é trabalhado isolado. Alguns nós existem só
para virar slides; outros entram no livro. A subdivisão é feita conforme a
densidade do conteúdo pede: não há profundidade fixa.

## Convenção de pastas

```
vol2/
  vol2.pdf  vol2_div.pdf  vol2_div_ocr.pdf   # binários pesados (git-ignored)
  vol2_pag.txt                                # texto INTEIRO etiquetado por página impressa (+ w→u)
  estrutura.tsv                               # manifesto: um nó por linha
  00_pretextuais/
  02_secao_corpo-alma-uniao/
    02_secao_corpo-alma-uniao.pdf  .txt        # o nó "secção" também tem o seu recorte
    01_cap_corpo-humano/
      01_cap_corpo-humano.pdf                   # PDF só deste capítulo (camada de texto preservada)
      01_cap_corpo-humano.txt                   # fatia de vol2_pag.txt deste capítulo
      01_cap_corpo-humano.tex                   # LaTeX final, fragmento \input-ável (sem \documentclass)
      01_cap_corpo-humano.slides.base.md        # base gerada por script (texto do livro literal)
      01_cap_corpo-humano.slides.md             # versão didática do LLM  ← fonte versionada
      01_cap_corpo-humano.pptx                  # entregável (derivado)
```

- Pasta de nó = `NN_slug/`. `NN` de dois dígitos garante a ordem no `ls`; `slug`
  sem acento, minúsculo, com hífen.
- Os arquivos de trabalho **repetem o stem da pasta** (`NN_slug.pdf`, `.txt`,
  `.tex`, `.slides.md`, …), então os ~6 arquivos de um nó ficam juntos no `ls` e
  cada um se identifica sozinho.
- Um nó que **não** for subdividido pode ter os arquivos direto na pasta do pai
  (`02_secao_x/03_cap_c.tex`), sem criar subpasta — a convenção de nome funciona
  nos dois casos.
- **Versionado:** `*.tex`, `*.slides.md`, `estrutura.tsv`.
  **Git-ignored (reproduzível):** `*.pdf` de recorte, `*.txt`, `*.slides.base.md`, `*.pptx`.

## `estrutura.tsv`

Um nó por linha, `caminho  pág_ini  pág_fim` (páginas **impressas**; `#` começa
comentário). Construído aos poucos, à medida que se decide descer um nível.

```
# caminho relativo à raiz do repo          pág_ini  pág_fim
vol2/02_secao_corpo-alma-uniao                    3       96
vol2/02_secao_corpo-alma-uniao/01_cap_corpo-humano    3   28
vol2/02_secao_corpo-alma-uniao/02_cap_alma-humana   29   64
```

Fonte das faixas: os cabeçalhos correntes (`SECÇÃO II — CAPITULO III — …`, já
visíveis no texto etiquetado) e o índice impresso no fim do volume.

## `tools/corta.py` — recorta um nó (substitui o iLovePDF manual)

```bash
# offset do vol. 2: descobrir por docs/02 (impressa + offset = índice pdf)
python3 tools/corta.py vol2/02_secao_x/01_cap_y 3 28 --offset 12
python3 tools/corta.py --tsv vol2/estrutura.tsv --offset 12
python3 tools/corta.py --tsv vol2/estrutura.tsv --offset 12 --only vol2/02_secao_x
```

Para cada nó grava, dentro da pasta, `<stem>.pdf`
(`mutool merge -o … vol2_div_ocr.pdf p0-p1`, camada de texto preservada) e
`<stem>.txt` (fatia de `vol2_pag.txt` entre os marcadores `<<<PAG>>>`). É
idempotente. `--raw` quando as páginas dadas já forem índices do PDF (miolo
pré-textual romano).

## Da faixa ao LaTeX

1. `python3 tools/corta.py …` → `<stem>.pdf` + `<stem>.txt`.
2. Revisar o `.txt` contra as imagens do `<stem>.pdf` (o OCR erra muito; latim
   de S. Tomás sempre conferir — `docs/04`).
3. Escrever `<stem>.tex` como **fragmento** (`\pg{n}` em cada quebra de página;
   seccionar pelos parágrafos numerados do autor). Macros disponíveis no
   preâmbulo comum: `\tese`, `\teseB`, `\sub`, `\subp` (`tex/preambulo.tex`).
4. Marcar com `%%>>> id` / `%%<<< id` os trechos que irão para slides.
5. Pré-visualizar isolado:
   ```bash
   latexmk -lualatex -usepretex='\def\fragmento{vol2/02_secao_x/01_cap_y/01_cap_y.tex}' tex/_preview.tex
   # notas correndo no corpo: acrescentar \def\notascorridas{} ao -usepretex
   ```
6. No livro: `\input{vol2/02_secao_x/01_cap_y/01_cap_y.tex}` na ordem de
   `estrutura.tsv`.

## Slides

```bash
python3 tools/gera_slides_base.py vol2/02_secao_x/01_cap_y/01_cap_y.tex
#   -> 01_cap_y.slides.base.md : um slide por trecho %%>>>, texto do livro em citação
# LLM: mantém o texto citado EXATO, acrescenta título/tópicos/explicação didática,
#      salva como 01_cap_y.slides.md  (fonte versionada)
.venv/bin/python tools/md2pptx.py vol2/02_secao_x/01_cap_y/01_cap_y.slides.md
#   -> 01_cap_y.pptx
```

Não há Marp nem pandoc na máquina; o `.pptx` sai do `md2pptx.py` (python-pptx).
A fonte a versionar e reeditar é sempre o `.slides.md`.
