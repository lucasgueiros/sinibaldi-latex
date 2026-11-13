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
encolhe (15 → 9 pt) para caber em até 2–3 linhas. O enunciado acima de ~5 linhas encolhe sozinho (mín. 0,55).

## Orçamento medido (quadro 16:9, título de 1–2 linhas)

- Parágrafo: 8 linhas × ~68 caracteres (≈ 540).
- `rotulados` (12,5/15 pt): ~64 caracteres/linha; 10 linhas com título de 1 linha, 9 com título de 2 linhas
  (silogismo Maior 4 + Menor 3 + Conclusão 1 cabe sempre).
- `topicos`: ~66 caracteres/linha; 6 itens de 1 linha ou 3 de 2 linhas.
- `enunciado` (16/20,5 pt): ~56 caracteres/linha; até 5 linhas sem encolher (sem parágrafo); com 3 linhas
  sobram ~3 linhas de parágrafo.
