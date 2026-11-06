# Sinibaldi — *Elementos de Philosophia* em LaTeX

```bash
./compila.sh --lista                              # capítulos disponíveis
./compila.sh existencia-de-deus                   # capítulo com notas de rodapé  -> build/<stem>.pdf
./compila.sh existencia-de-deus --sem-notas       # capítulo SEM notas de rodapé  -> build/<stem>-sem-notas.pdf
./compila.sh existencia-de-deus --notas-corpo     # notas correndo no corpo       -> build/<stem>-notas-corpo.pdf
latexmk -lualatex livro.tex                       # livro inteiro                 -> livro.pdf
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

## Livro inteiro

```bash
latexmk -lualatex livro.tex
```

Cada capítulo entra em `livro.tex` com um `\input{volN/…/<stem>}`.

## Requisitos

TeX Live com `lualatex`, `latexmk`, `fontspec`, `polyglossia`, `sectsty`.
