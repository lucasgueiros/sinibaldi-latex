# Ensaio de diagramação — Essencia de Deus

O mesmo trecho em três formatos, para escolher a mancha da nova edição.
Trecho: vol. 2, *Theodicea*, cap. II («Essencia e attributos de Deus»), Art. I inteiro,
nn. 22–26, pp. 443–450 do original. O corpo é curto e as notas são enormes (cerca de 5×
o corpo; várias passam de uma página): é o caso mais difícil do livro.

| PDF | Papel | Corpo | Notas |
|---|---|---|---|
| `formato-1-livro.pdf` | livro padrão, 160×230 mm | 11 pt | rodapé, 1 coluna, 9 pt, numeração por página `(1)`; área de notas ≤ 84 % da mancha |
| `formato-2-folha-maior.pdf` | A4, 210×297 mm | 12 pt | rodapé, **2 colunas** de alturas iguais, 8,5 pt, numeração por página |
| `formato-3-notas-no-corpo.pdf` | livro padrão, 160×230 mm | **12,5/16 pt**, preto, recuado 8 mm dos dois lados | no corpo, soltas **depois do parágrafo** que as chama, largura toda, 8,5/10,5 pt, cinza escuro, sem filete |

Fonte: EB Garamond (lualatex). Página do original: `[443]` na margem externa (corpo) ou
discreta no fluxo (dentro de nota).

## Arquivos

- `texto.tex` — o trecho (comum aos três). Base: `revisao/essencia-de-deus/revisado.tex`,
  com os erros de OCR evidentes corrigidos à mão. **Ainda não conferido linha a linha
  contra a imagem.** A fronteira corpo/nota foi conferida na imagem (`vol2/vol2.pdf`,
  folhas 223–225): os dois blocos que começam com `*` («Os erros ácerca da infinidade…»,
  p. 446; «Todos os philosophos…», pp. 449–450) estão em letra de nota, como apêndices
  sem número das notas de 24 c) e do n. 25, e ficam dentro dessas notas.
- `comum.tex` — fonte, títulos (`\capitulo`, `\artigo`, `\tese`, `\teseB`, `\subp`),
  `\pg`/`\pgn`, `\asterisco`, cabeçalhos.
- `formato-*.tex` — geometria e tratamento das notas de cada formato.

```bash
cd diagramacao/essencia-de-deus
latexmk -lualatex -outdir=build formato-1-livro.tex   # idem para os outros dois
```

## Notas técnicas

- **Corpo em toda página (formatos 1 e 2).** Sem limite, o TeX enche páginas inteiras só
  com nota. `\dimen\footins` limita a área de notas e o resto da nota passa para a página
  seguinte. Fração ajustável: `lualatex "\def\fracaonotas{0.8}\input{formato-1-livro}"`.
  No formato 1 testei de 0,55 a 0,88 contando o corpo por página (palavras com caixa
  alta no `pdftotext -bbox`): 0,84 é o valor que deixa corpo nas 7 páginas, com 57 a 182
  palavras cada. Abaixo disso o corpo acaba antes e sobram páginas só de nota; acima,
  volta a haver página sem corpo. No A4 as 4 páginas têm corpo com qualquer valor.
- **Margem:** `\marginnote`, não `\marginpar`. `\marginpar` é float e, com notas retidas
  de uma página para outra, o LaTeX aborta com «Float(s) lost».
- **Duas colunas:** o `dblfnote` entra em laço com notas maiores que meia página, por isso
  usei as notas «familiares» do `reledmac` (`\arrangementX[A]{twocol}`). O
  `\rigidbalance` dele corta em altura/2 e completa a coluna curta com `\vfil`, então com
  um número ímpar de linhas a da direita ficava com uma linha a menos. Foi substituído:
  corta, mede as duas colunas e, quando a diferença é de até 1,5 linha, estica a mais
  curta usando uma folga mínima na entrelinha (+0,35 pt) e entre parágrafos. Diferença
  maior só acontece na última página das notas, onde fica o `\vfil`.
- **Notas no corpo:** diferente do `\notascorridas` de `tex/preambulo.tex`, que corta a
  frase no ponto da chamada, aqui a nota entra numa fila e sai no hook `para/after`,
  só na lista vertical principal (`\ifinner` falso).
- **`\pg` antes de `\tese`/`\teseB`/`\subp`** fica pendente e é solto por eles, para não
  cair no pé da página anterior. Antes de texto comum, abre o parágrafo ali mesmo. Um
  hook `para/begin` com `\marginnote` comia o recuo do parágrafo.
