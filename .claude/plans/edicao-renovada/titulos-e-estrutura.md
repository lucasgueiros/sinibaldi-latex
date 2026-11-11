# Títulos → `estrutura.tsv` → formatação (o TSV manda)

Parte de `plano.md`, fase F4. Substitui o "reconstruir o índice" da primeira versão do plano. O
índice impresso deixa de ser a fonte e passa a ser **conferência**.

## Princípio

1. `tools/titulos.py` **detecta** os títulos nas páginas e **propõe** o `estrutura.tsv`.
2. Depois de revisado, o `estrutura.tsv` é a **única fonte da estrutura**. O gerador de
   LaTeX/HTML não decide nada sozinho: lê o TSV e formata.
3. Para corrigir um título errado, perdido ou inventado, **muda-se uma linha do TSV** e
   regenera-se. Nunca se edita o título no `.tex`.
4. Rodar `titulos.py` de novo **não sobrescreve** um TSV revisado: ele grava `estrutura.proposta.tsv`
   e um diff contra o atual, para incorporar só o que se quiser.

## O que distingue um título (medido na p. 421)

Corpo: entrelinha ~52 px, x_size ~42, linha cheia (largura ~1290), margem esquerda.

| linha | sinal | tipo |
|---|---|---|
| `CAPITULO PRIMEIRO` | x_size **78**, centrada, versal | capítulo (rótulo) |
| `EXISTENCIA DE DEUS` | centrada, largura 518, versal, sem serifa | capítulo (título) |
| `SUMMARIO: — … — …` | versalete inicial, corpo menor, recuo francês | sumário do capítulo |
| `ARTIGO I.` | centrada, curta (239), versal + numeral romano | artigo (rótulo) |
| `Demonstrabilidade da existencia de Deus.` | centrada, negrito decorado | artigo (título) |
| `6. A existencia de Deus póde ser …` | `^\d+\.` + negrito sem serifa até o 1.º `—` | tese numerada |
| `5. Divisão da Theodicea.` | idem | tese (o prólogo também numera) |
| `——•——` | ornamento centrado | separador (fim de bloco) |
| `PROLOGO 421` / `422 METAPHYSICA — PARTE QUARTA — THEODICEA` | 1.ª linha, x_size 31 | cabeçalho corrente |

## Classificação: `tools/titulos.py`

Para cada linha do corpo, a partir do JSON da página (F2), o script calcula características
**relativas à página** (margem e corpo medidos pela moda):

- `centrada`: os recuos dos dois lados são iguais (±3 %) e a largura é menor que ~90 % da coluna;
- `escala`: x_size e altura do bbox divididos pelos do corpo;
- `versal`: proporção de maiúsculas;
- `negrito`: densidade de tinta no bbox (pixels escuros por área, normalizada pela do corpo).
  É uma medida na imagem, porque o tesseract LSTM não informa negrito. Separa a tese da linha comum;
- `vocabulário`: `^(PARTE|SECÇÃO|SECÇAO|CAPITULO|ARTIGO|§|PROLOGO|INTRODUCÇÃO|APPENDICE)\b`,
  numerais por extenso e romanos (`PRIMEIRO`, `II`), `^\d+\.`;
- `vão`: espaço acima e abaixo da linha em entrelinhas.

Regras simples, sem aprendizado de máquina, ajustadas no piloto. O nível vem da **hierarquia do
vocabulário** (parte > secção > capítulo > artigo > tese), não do tamanho da letra, porque o
tamanho só confirma.

Validações cruzadas, que aparecem como alertas na proposta:

- **Números em sequência**: teses 5, 6, 7… contínuas pelo volume inteiro; artigos I, II…
  recomeçam por capítulo; capítulos recomeçam por parte. Um salto (`6, 8`) indica tese perdida ou
  dígito mal lido, e a sequência sugere o valor esperado.
- **Cabeçalho corrente**: o título corrente das páginas ímpares (`PROLOGO`, `EXISTENCIA DE DEUS`)
  muda exatamente onde o TSV diz que começa uma divisão. O das pares dá parte/secção
  (`METAPHYSICA — PARTE QUARTA — THEODICEA`).
- **Índice impresso** (re-OCR cuidadoso das páginas do fim do volume): cada entrada do índice
  deve ter uma linha no TSV com a mesma página, com tolerância a erro de OCR por distância de
  edição. A divergência entra num relatório; o índice **não** altera o TSV sozinho.

## Formato do `estrutura.tsv`

Uma linha por título, na ordem do livro. A página final **não** é guardada: ela é derivada da
linha seguinte. Assim, corrigir uma linha nunca deixa outra inconsistente.

```
# pág  âncora                   nível      rótulo              título                                                       id
419    PROLOGO                  prologo    Prologo             -                                                            theodicea-prologo
421    5.                       tese       5                   Divisão da Theodicea.                                        t5
421    CAPITULO PRIMEIRO        capitulo   Capitulo Primeiro   Existencia de Deus                                           existencia-de-deus
421    SUMMARIO                 sumario    -                   Demonstrabilidade da existencia de Deus. — Demonstração …    -
421    ARTIGO I.                artigo     Artigo I            Demonstrabilidade da existencia de Deus.                     existencia-de-deus-a1
421    6.                       tese       6                   A existencia de Deus póde ser demonstrada pela razão humana.  t6
422    7.                       tese       7                   A existencia de Deus deve ser demonstrada.                   t7
```

- `pág` + `âncora`: onde o título está. A âncora é o **início do texto** da linha na página,
  casado de forma tolerante (normalizado, distância de edição). Não se usa número de linha, que
  mudaria a cada re-OCR.
- `rótulo` e `título` são o que será impresso, na grafia do original. A modernização (F7) os
  converte como o resto. Uma coluna opcional `título_moderno` permite fixar à mão um caso
  especial.
- `id`: estável, gera `\label`/âncora HTML e o nome do arquivo do nó. As teses ganham `t6`, base
  dos hiperlinks "cf. n. 6".
- **Corrigir** = editar o campo. **Título fantasma** (texto do corpo tomado por título) = apagar a
  linha, e o texto volta a ser corpo. **Título perdido** = acrescentar uma linha com `pág` e
  `âncora`. **Nível errado** = trocar `nível`.

## Do TSV aos arquivos e à formatação

- **Nós/arquivos**: uma configuração por volume diz em que níveis o texto é cortado em arquivos
  (padrão: `capitulo`, e `prologo` como capítulo). Pastas `NN_slug/` e o recorte das páginas
  (`corta.py`) saem do TSV. O `estrutura.tsv` atual de `docs/05` (`caminho pág_ini pág_fim`) passa
  a ser **derivado** deste, e `corta.py` lê o novo formato.
- **Formatação** (atualizado: a fonte agora é TEI, ver `tei-base-e-obra-nova.md`): cada `nível`
  vira `<div type="…" xml:id n>` + `<head>` no TEI, e `tei2latex`/`tei2html` mapeiam cada tipo para
  **uma macro** do preâmbulo / uma tag HTML, e a aparência fica em
  um só lugar:

  | nível | LaTeX gerado | HTML gerado |
  |---|---|---|
  | `parte` | `\parte{Parte Quarta}{Theodicea}` | `<h1 id=…>` |
  | `capitulo` | `\capitulo{Capitulo Primeiro}{Existencia de Deus}` | `<h2 id=…>` |
  | `sumario` | `\sumario{…}` | `<p class="sumario">` |
  | `artigo` | `\artigo{Artigo I}{Demonstrabilidade …}` | `<h3 id=…>` |
  | `tese` | `\tese{6}{A existencia …}` (já existe) | `<p id="t6"><strong>6. …` |
  | `prologo` | `\capitulo{Prologo}{}` | `<h2>` |

- Na geração (`pagina2tei.py`, F5), as linhas que o TSV declara título são **retiradas do fluxo**
  do corpo e viram `<div>`/`<head>`, com o `<pb>` mantido no lugar. O que o TSV não declara
  continua sendo corpo.
- Sumário/índice do livro (`\tableofcontents`) e índice do site saem das próprias macros, ou seja,
  do TSV.

## Custo

Tudo determinístico e em segundos. A revisão humana do TSV é a única etapa estrutural manual:
algumas centenas de linhas por volume (as teses são a maior parte), lidas em ordem, com os
alertas indicando onde olhar.
