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
corpo, num bloco recuado que interrompe a leitura.

## Pré-visualizar um nó isolado

`tex/_preview.tex` compila **um** fragmento com o mesmo preâmbulo do livro:

```bash
latexmk -lualatex -usepretex='\def\fragmento{vol2/02_secao_x/01_cap_y/01_cap_y.tex}' tex/_preview.tex
```

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
