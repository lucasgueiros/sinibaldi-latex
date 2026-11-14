# Sinibaldi — *Elementos de Philosophia* em LaTeX

```bash
./compila.sh --lista                              # capítulos disponíveis
./compila.sh existencia-de-deus                   # capítulo com notas de rodapé  -> build/<stem>.pdf
./compila.sh existencia-de-deus --sem-notas       # capítulo SEM notas de rodapé  -> build/<stem>-sem-notas.pdf
./compila.sh existencia-de-deus --notas-corpo     # notas correndo no corpo       -> build/<stem>-notas-corpo.pdf
latexmk -lualatex livro.tex                       # livro inteiro                 -> livro.pdf
tools/gera_volume.sh vol2                         # volume inteiro do OCR, com itálico/versalete -> build/vol2.pdf
./compila.sh --limpa                              # apaga auxiliares de build/ (mantém PDFs)
```

Re-digitação em LaTeX dos *Elementos de Philosophia* de D. Thiago Sinibaldi (ortographia original
preservada), a partir dos scans `vol1.pdf` / `vol2/vol2.pdf`. Visão geral e pipeline em
[`CLAUDE.md`](CLAUDE.md); notas detalhadas em [`docs/`](docs/README.md).

## Compilar um capítulo

Sempre da **raiz do repositório**:

```bash
./compila.sh <capitulo> [--sem-notas | --notas-corpo]
```

- `<capitulo>` é o caminho do fragmento (`vol2/02_parte_theodicea/01_cap_existencia-de-deus.tex`,
  com ou sem `.tex`) **ou um pedaço do nome** (`existencia-de-deus`, `theodicea`…). Se o pedaço casar
  com mais de um capítulo, o script lista os candidatos e para.
- Sem opção: notas de rodapé normais, no pé da página.
- `--sem-notas`: suprime todas as notas (chamada e conteúdo) — só o corpo do texto.
- `--notas-corpo`: cada nota corre no corpo, em bloco recuado, logo após o ponto de chamada.
- Saída em `build/` (git-ignorado), com nome `<stem>[-sem-notas|-notas-corpo].pdf`; as três variantes
  convivem sem se sobrescrever.

Por baixo, o script chama `latexmk -lualatex` sobre `tex/_preview.tex` (mesmo preâmbulo do livro)
passando `\def\fragmento{…}` e, conforme a opção, `\def\semnotas{}` ou `\def\notascorridas{}`.

## Exportar a obra em PDF (4 formatos)

```bash
tools/exporta_pdf.sh vol2                        # os 4 formatos -> build/vol2-<formato>.pdf
tools/exporta_pdf.sh vol1 vol2                   # os dois volumes
tools/exporta_pdf.sh vol2 --formato notas-2col   # só um (repetível)
tools/exporta_pdf.sh vol2/02_parte_theodicea/01_cap_existencia-de-deus.tex   # um capítulo
```

| Formato | Papel | Notas |
|---|---|---|
| `sem-notas` | livro 160×230 mm, 11 pt | suprimidas (chamada e conteúdo) |
| `notas-1col` | livro 160×230 mm, 11 pt | rodapé, 1 coluna, 9 pt, numeração por página |
| `notas-2col` | **A4**, 12 pt | rodapé, 2 colunas de alturas iguais, 8,5 pt |
| `notas-corpo` | livro 160×230 mm, 12,5/16 pt | no corpo, depois do parágrafo que as chama |

São os formatos escolhidos em `diagramacao/essencia-de-deus/` (ver o README de lá), generalizados
em `tex/formatos/` (`comum.tex` + um mestre por formato) para receber qualquer fragmento do
`tei2latex.py --puro`. Para `volN`, o `.tex` sai de `volN/volN.corrigido.xml` (refazer com `--regera`).

## Livro inteiro

```bash
latexmk -lualatex livro.tex
```

Cada capítulo entra em `livro.tex` com um `\input{volN/…/<stem>}`.

## Requisitos

TeX Live com `lualatex`, `latexmk`, `fontspec`, `polyglossia`, `sectsty`.
