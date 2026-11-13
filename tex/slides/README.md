# Tema de slides — Academia Leão XIII

`academia-slides.sty` (beamer 16:9, lualatex) com a identidade do site: pergaminho, moldura de filete duplo,
Cinzel (títulos) + EB Garamond (texto), cruz `✠` (DejaVu Sans), crimson/ouro. `logo.pdf` é o selo vetorial.

```latex
\documentclass[aspectratio=169,11pt]{beamer}
\usepackage{academia-slides}
\slidesmeta{Obra}{Autor}{Trecho}
```

## Compilar

```bash
cd tex/slides
TEXINPUTS=$PWD//: latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=/tmp/slides exemplo.tex
```

`exemplo.tex` mostra todas as telas e ambientes (inclusive casos de estresse).

## Telas

- `\slidecapa{título}{subtítulo}{referência}` — capa (selo grande, autor/obra de `\slidesmeta`); argumentos podem ser vazios.
- `\slidesecao{rótulo}{título}` — divisória em fundo crimson escuro.
- `\begin{slide}{tipo}{título}{referência}` … `\end{slide}` — tela com corpo. Tipos: `tese`, `definicao`,
  `divisao`, `argumento`, `objecao`, `resposta`, `corolario`, `escolio`, `observacao`, `citacao`, `texto`
  (sem etiqueta; tipo desconhecido vira `texto`). Cada tipo tem etiqueta em Cinzel e barra lateral própria.
  A referência vai no rodapé com logo, nome da obra e número da página.

## Corpo

`enunciado` (caixa de filete duplo, corpo maior), `topicos` (✠, aninha 1 nível), `citacao` (barra dourada, itálico),
`rotulados` + `\rot{rótulo}{texto}` (silogismo/subdivisões; em `argumento` a linha `Conclusão` fica em negrito),
`\continua` ("(continua)" no fim do corpo).

## Transbordo

O frame usa `allowframebreaks`: o que não cabe passa para um quadro seguinte, com o mesmo título e a marca
"continuação n" na etiqueta. Limite: `enunciado` é uma caixa indivisível (não quebra); título muito longo
encolhe (16 → 9 pt) para caber em até 2–3 linhas.
