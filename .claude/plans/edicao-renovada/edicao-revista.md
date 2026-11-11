# Edição-base e edição revista: procedência por bloco

Parte de `plano.md` (F8). Motivação: o objetivo não é só corrigir OCR. Depois virão **mudanças
drásticas**: atualizar dados científicos, mudar a ordem da exposição, rever posições filosóficas,
acrescentar problemas teológicos posteriores. Quem, quando e por quê precisam ficar **no texto**.

## Duas obras, não uma com marcações

| | Edição-base | Edição revista |
|---|---|---|
| O que é | Sinibaldi 1916, fiel, grafia AO 1990 | obra nova dos revisores, derivada da base |
| Origem | pipeline OCR → revisão → **congelada** | escrita por humanos |
| Intervenções | grafia, erro tipográfico (pontuais) | reordenar, reescrever, suprimir, acrescentar |
| Cita-se como | Sinibaldi, p. `[421]` | a revista, com remissão à base |

Por que não marcar a revista dentro da base, com TEI `<add>`/`<del>`/`<subst>` ou macros
equivalentes: essas marcas servem para intervenções pontuais sobre um texto fixo. Com reordenação
e reescrita de seções inteiras, o arquivo vira uma sequência de `<del>`/`<add>` de páginas,
ilegível, e mover um trecho é mal representado.

## Ids estáveis na base

Cada unidade da base recebe um id, derivado da estrutura do próprio autor (`estrutura.tsv`):

- `t6`: tese/parágrafo numerado 6; `t6.2`: 2.º parágrafo dela;
- `n421-2`: nota 2 da p. 421;
- `cap-existencia-de-deus`, `art-…`: divisões.

Na base, `\bloco{t6.2}{…}` (ou o id implícito gerado por `\tese`) marca a unidade. Depois de
congelada, os ids **nunca mudam**. A base continua tendo `\pg{n}`, que dá a página de cada bloco.

## A revista é escrita por referência à base

```latex
\trecho{t6}                          % integral: transcluído da base, não copiado
\trecho{t6.1-t6.3}                   % faixa

\begin{adaptado}[de={t7,t7.2}, resp=lucas, data=2027-03-01,
                 motivo={Atualiza o dado sobre a idade do universo.}]
  … texto reescrito …
\end{adaptado}

\begin{novo}[resp=lucas, data=2027-04-12,
             motivo={Objeção posterior ao autor; discussão contemporânea.}]
  … seção nova …
\end{novo}

\suprimido[de=t9, resp=lucas, data=2027-03-01]{Argumento baseado no éter, abandonado pela física.}

\ned[resp=lucas, data=2027-05-02]{Nota do editor, distinta das notas do autor.}
```

- **Reordenar** = mudar a ordem das referências. Nada é copiado nem marcado.
- **Integral é transclusão**: uma correção na base chega sozinha à revista. Se a base mudar depois
  de um `adaptado` ter sido escrito, o script avisa que aquele bloco precisa ser revisto.
- **Quem / quando / por quê** ficam no cabeçalho do bloco, dentro do texto. **O que** mudou não é
  marcado: é calculado (diff do bloco contra a base congelada).
- Granularidade: o bloco, isto é, o parágrafo ou a tese. Uma mudança pequena dentro de um bloco
  integral transforma o bloco em `adaptado`.

## `tools/procedencia.py` (conferência e relatórios)

- **Cobertura**: todo id da base aparece na revista como `trecho`, `adaptado` ou `suprimido`. Id
  órfão = alerta. Nada de Sinibaldi some em silêncio.
- **Tabela de correspondência** base ↔ revista ("n. 6 → §12"), como apêndice do livro e página do
  site.
- **Relatório de diferenças** de cada `adaptado` contra os blocos de origem.
- **Registro de mudanças** (quem, quando, motivo), ordenável por autor/data/capítulo; pode ser
  exportado como `<revisionDesc>` TEI.
- Conferir que `resp`, `data` e `motivo` existem em todo `adaptado`/`novo`/`suprimido`.

## Apresentação (PDF e site)

- Procedência visível e comutável: sigla na margem (`S. 421` integral, `S.* 422` adaptado,
  `Rev.` novo), ou fundo/fio distinto para texto novo. Uma chave gera a versão "limpa", só com o
  texto.
- No site, um bloco adaptado abre o original da base ao lado, e `[421]` abre a imagem do scan.

## Formato

LaTeX semântico nas duas obras (uma só cadeia de ferramentas; texto novo escrito com conforto;
PDF bonito). HTML gerado pelo conversor próprio. TEI só como **exportação** opcional da base
(`<pb>`, `<note>`, `xml:lang="la"`, `<choice><orig><reg>`), mecânica a partir das macros.

## Em que ponto entra no plano

F1–F7 produzem e congelam a base (com os ids). Esta estrutura é a F8. A primeira entrega
acadêmica é a base completa; a revista começa por um capítulo-piloto (Theodicea cap. I) para
validar as macros, o `procedencia.py` e a apresentação.
