# Ensaio de diagramação — Essencia de Deus

Mesmo trecho em três formatos, para escolher a mancha da nova edição.
Trecho: vol. 2, *Theodicea*, cap. II («Essencia e attributos de Deus»), Art. I, nn. 22–25,
pp. 443–449 do original — corpo curto e notas muito longas (várias passam de uma página),
o caso mais difícil do livro.

| PDF | Papel | Corpo | Notas |
|---|---|---|---|
| `formato-1-livro.pdf` | A5, 148×210 mm | 11 pt | rodapé, 1 coluna, `\footnotesize`, numeração por página `(1)` |
| `formato-2-folha-maior.pdf` | 170×240 mm | 11 pt | rodapé, **2 colunas**, `\footnotesize`, numeração por página |
| `formato-3-notas-no-corpo.pdf` | 160×230 mm | **12 pt**, preto | no corpo, soltas **depois do parágrafo** que as chama; corpo menor, cinza, recuadas, com filete à esquerda |

Fonte: EB Garamond (lualatex). Página do original: `[443]` na margem externa (corpo) ou
discreta no fluxo (dentro de nota).

## Arquivos

- `texto.tex` — o trecho (comum aos três). Base: `revisao/essencia-de-deus/revisado.tex`,
  com os erros de OCR evidentes corrigidos à mão. **Ainda não conferido linha a linha
  contra a imagem.** Omitido `[…]` o fim da nota de 24 c) («Os erros ácerca da
  infinidade…»), cuja fronteira corpo/nota ficou em dúvida na revisão.
- `comum.tex` — fonte, títulos (`\capitulo`, `\artigo`, `\tese`, `\teseB`, `\subp`),
  `\pg`/`\pgn`, cabeçalhos.
- `formato-*.tex` — geometria e tratamento das notas de cada formato.

```bash
cd diagramacao/essencia-de-deus
latexmk -lualatex -outdir=build formato-1-livro.tex   # idem para os outros dois
```

## Notas técnicas

- **Duas colunas**: `dblfnote` entra em laço (`TeX capacity exceeded`) com notas maiores que
  meia página; usei as notas «familiares» do `reledmac` (`\arrangementX[A]{twocol}`,
  `\let\footnote\footnoteA`), que quebram entre páginas sem problema.
- **Notas no corpo**: diferente do `\notascorridas` de `tex/preambulo.tex` (que corta a
  frase no ponto da chamada), aqui a nota entra numa fila e sai no hook `para/after`,
  só na lista vertical principal (`\ifinner` falso) — sem essa guarda a fila era solta
  dentro da rotina de saída quando o parágrafo quebrava de página, e a nota saía
  sobreposta. Se o formato 3 for o escolhido, vale levar esse mecanismo ao preâmbulo.
- `\pg` em modo vertical (antes de título) espera o próximo parágrafo (hook
  `para/begin`), para não cair no pé da página anterior.
