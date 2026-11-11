# Arquitetura LaTeX (livro → PDF) e slides

Os slides **não** saem do LaTeX: um script monta a base a partir dos trechos marcados no `.tex`
(texto do livro literal), um LLM torna a base didática, e `tools/md2pptx.py` gera o `.pptx`. Não
há beamer. Ver a seção "Slides" no fim e `docs/05-estrutura-por-no.md`.

## Marca de página impressa

Definida em `tex/preambulo.tex`:

```latex
\newcommand{\pg}[1]{\,{\footnotesize\textbf{[#1]}}\,}
```

`\pg{286}` imprime `[286]` no fluxo do texto, na posição exata onde a página virava no original.
Os números vêm de `tools/extract_paginado.py` (ver `docs/02-numeracao-de-paginas.md`) — nunca do OCR
do cabeçalho. Sendo uma macro única, a aparência (margem, sobrescrito, cinza) muda depois sem tocar
no texto.

## Macros de estrutura do autor

`tex/preambulo.tex` também define (promovidas de um artigo transcrito à mão):

- `\tese{n}{título}` — enunciado de tese numerada correndo com o texto (segue travessão);
- `\teseB{n}{título}` — idem, em linha própria (quando vêm subdivisões `a)`, `b)`…);
- `\sub{a}{rubrica}` / `\subp{a}` — subdivisão com / sem rubrica em itálico.

Notas: por omissão saem no pé; com `\def\notascorridas{}` (via `-usepretex`) passam a correr no
corpo, num bloco recuado que interrompe a leitura; com `\def\semnotas{}` são suprimidas por
inteiro (chamada e conteúdo).

## Pré-visualizar um nó isolado

Atalho da raiz: `./compila.sh <capitulo> [--sem-notas | --notas-corpo]` → `build/<stem>[-…].pdf`
(ver `README.md`). Por baixo, `tex/_preview.tex` compila **um** fragmento com o mesmo preâmbulo do
livro:

```bash
latexmk -lualatex -usepretex='\def\fragmento{vol2/02_secao_x/01_cap_y/01_cap_y.tex}' tex/_preview.tex
```

### Compilar o fragmento avulso

Cada fragmento começa com um guarda que, se o arquivo for o documento principal (botão do editor,
`lualatex <stem>.tex` de dentro da pasta do nó), carrega `tex/avulso.tex` (classe + preâmbulo) e
fecha o documento no `\csname fimavulso\endcsname` final; dentro do livro/`_preview` não faz nada:

```latex
% !TEX program = lualatex
\ifdefined\pg\else\IfFileExists{tex/avulso.tex}{\input{tex/avulso}}{\input{../../tex/avulso}}\fi
...
\csname fimavulso\endcsname
```

Use **lualatex**. Com pdflatex o avulso também compila (preâmbulo alternativo inputenc/babel), mas só
para conferência. Livro inteiro: `latexmk -lualatex livro.tex`, com um `\input` por fragmento.

## Compilação

`lualatex` (Unicode + `fontspec`/`polyglossia`), via `latexmk`:

```bash
latexmk -lualatex livro.tex
```

Prova de conceito compilando hoje: `livro.tex` com `tex/exemplo-ontologia.tex`, exibindo `[37]` e `[38]`.

## Trechos nomeados

Trechos que serão usados depois (para os slides em PPTX, ou para citação) podem ser delimitados por
guardas em comentário no próprio `.tex`:

```latex
%%>>> ente-immutavel
\pg{37}\textbf{87. O ente immutavel...} --- ...
%%<<< ente-immutavel
```

`python3 tools/trecho.py tex/exemplo-ontologia.tex ente-immutavel` imprime o bloco. As guardas são
comentários LaTeX e não afetam a compilação. É só um atalho para recortar uma passagem do texto
revisado sem copiar e colar do meio do arquivo — o que se faz com o recorte depois é problema de
quem monta os slides.

## Fluxo de trabalho da transcrição

1. `python3 tools/corta.py <caminho-do-nó> <pág_ini> <pág_fim> --offset N` para recortar a faixa
   (gera `<stem>.pdf` + `<stem>.txt`; ver `docs/05`).
2. Revisar o `.txt` contra a imagem (`pdftotext` não substitui olhar a página).
3. Escrever `<caminho-do-nó>/<stem>.tex` como fragmento `\input`-ável, inserindo `\pg{n}` em cada
   quebra de página do original.

O seccionamento natural segue os parágrafos numerados do autor (`87.`, `88.`, …), não a paginação.

## Slides

```bash
python3 tools/gera_slides_base.py <caminho-do-nó>/<stem>.tex     # -> <stem>.slides.base.md
#   um slide por trecho %%>>> id, com o texto do livro em citação
# LLM: mantém o texto citado EXATO, acrescenta título/tópicos/explicação, salva <stem>.slides.md
.venv/bin/python tools/md2pptx.py <caminho-do-nó>/<stem>.slides.md   # -> <stem>.pptx
```

A fonte a versionar e reeditar é o `.slides.md`; `.slides.base.md` e `.pptx` são reproduzíveis.

## TEI → LaTeX (dois passos)

`tools/estruturar_tei.py <volN>/paginas -o <volN>/<volN>.estruturado.xml [-f P -l P]` lê o
`manifesto.tsv` e o `.tsv` do tesseract de cada página (geometria) e produz o TEI estruturado:
`div` parte/seccao/capitulo/artigo/tese, `head`, `argument`, `label`, `hi rend="bold"`, `fw`,
`pb` e notas `<note>` **no ponto da chamada** (com `<pb/>` interno quando atravessam páginas).
Separação corpo × notas por geometria (entrelinha calibrada por volume), não por texto.
Tudo que a heurística não fecha vai para `<saida>.alertas.tsv` (revisão F6).

`tools/tei2latex.py <xml> [-f P -l P] [-o x.tex] [--puro] [--grafia original|atual]` converte o TEI
(estruturado, ou o bruto de `paginas2tei.py`) no dialeto de `tex/preambulo.tex`:
`\pg`, `\pgn`, `\tese`, `\footnote`, `\chapter*`/`\section*`, `latim`. Sem `--puro`, o `.tex`
compila avulso (`tex/avulso.tex`). Limitações conhecidas do estruturador: página com corpo
retomado depois de nota (alerta `vao-nas-notas`), tese cujo número o OCR leu mal (alerta
`tese-fora-de-sequencia`; a tese vira `<p>`), itálico/latim ainda não marcados (fase F6).
