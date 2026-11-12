# Revisão final por LLM (`tools/revisa_paginas.py`)

Última etapa do texto: um modelo compara o `.tex` do pipeline com a imagem de cada página e devolve o
trecho corrigido. Medido nos dois padrões-ouro (`docs/07`) com Haiku, Sonnet e Opus em 2026-11-11.

```bash
python3 tools/revisa_paginas.py ENTRADA.tex --vol vol2 --modelo haiku --saida DIR [--paralelo 3]
python3 tools/revisa_paginas.py ENTRADA.tex --vol vol2 --saida DIR --seco          # só mostra os pedaços
python3 tools/revisa_paginas.py ENTRADA.tex --vol vol2 --modelo haiku --saida DIR --so 430 --refaz
revisao-modelos/roda_por_pagina.sh [modelos]        # a comparação abaixo
python3 revisao-modelos/compara.py revisao-modelos/por-pagina
python3 revisao-modelos/wer_paginas.py revisao-modelos/por-pagina/haiku/vol2       # erros por página
```

`ENTRADA.tex` sai de `tools/trecho.py SELETOR -F tex`. Saída em `DIR`: `revisado.tex`, `wer.txt`,
`relatorio.md` (o que o modelo diz ter corrigido e as dúvidas), `resultado.json` (custo, tokens,
recusas) e `paginas/NNNN.{entrada,revisado,rejeitado}.tex` + `.json`. Rodar de novo retoma de onde parou.

## Como funciona (e por que assim)

A primeira tentativa (`tools/revisa_trecho.sh`, agente `claude -p` com Read/Edit num capítulo inteiro)
esgotou o limite de 5 h com US$ 10 e nenhum capítulo terminado: cada um dos 50–170 turnos (um Edit por
correção) relia o prompt de sistema do Claude Code, o `.tex` inteiro e todas as imagens já lidas,
~3 M tokens de cache por capítulo. Agora:

- **um turno por pedaço, sem ferramentas.** O `.tex` é cortado nos `\pg{N}`. Cada pedaço vai numa só
  mensagem (`--input-format stream-json`, `--tools ""`, `--system-prompt` próprio =
  `tools/prompts/revisao_pagina.md`) com as imagens embutidas, e o modelo devolve o pedaço inteiro em
  `<tex>…</tex>`. Contexto de 8–34 k tokens; cache de prompt desligado (`DISABLE_PROMPT_CACHING=1`),
  porque cada mensagem é única e gravar o cache custa mais que a entrada normal.
- **imagens:** as páginas do intervalo, mais as citadas por `\pgn` (nota que continua). Páginas de pura
  continuação de nota (corpo vazio entre dois `\pg`) juntam-se ao pedaço anterior. Cada página vai em
  duas metades cinza de ≤ 1568 px, o máximo que a API usa sem reduzir, e assim o rodapé fica legível.
- **estrutura congelada.** O prompt proíbe mover texto entre corpo e nota, abrir, fechar ou partir
  notas e mover `\pg`/`\pgn`. Na primeira rodada, sem essa regra, Haiku "consertou" notas longas de
  várias páginas: fechou notas cedo, partiu-as em duas e passou ~1900 palavras de nota para o corpo
  (WER do corpo 116%). A estrutura do pipeline está quase sempre certa; o ganho do modelo está na
  leitura das palavras.
- **validador** (`valida()`): recusa a resposta se mudarem os `\pg`, os `\pgn`, o número de
  `\footnote` ou o saldo de chaves; se corpo e notas mudarem em sentidos opostos (texto passou de um
  para o outro); ou se as notas mudarem mais de max(2%, 200 car.) ou o corpo mais de
  max(12%, 180 car. por página com corpo), o que indica texto duplicado, tipicamente copiado de uma
  nota que começa numa página extra. Recusada, há uma 2ª chamada que diz o motivo. Se ela também
  falhar, fica o texto do pipeline e o pedaço vai para `falhas` em `resultado.json`. `--revalida`
  reaplica o validador às respostas recusadas já gravadas, sem nova chamada.
- **a 1ª linha da página.** O pipeline perde com frequência a primeira linha do corpo de uma página
  (5 casos no capítulo do vol. 2, 1 em 331–334). O prompt manda conferir as palavras depois de cada
  `\pg{N}` com a 1ª linha da imagem e repô-la. Uma versão anterior dizia que "o começo da página é do
  trecho anterior" e o modelo pulava essas linhas.

## Resultado (2026-11-11)

WER contra o ouro (`tools/mede_wer.py`). vol. 2 = capítulo *Existencia de Deus* inteiro (pp. 421–442,
15 pedaços); vol. 1 = pp. 331–334 de *Divisão do ente* (o que o ouro cobre). Haiku revisou o
capítulo inteiro do vol. 1 (26 pedaços, US$ 0,23); Sonnet e Opus, só os 4 pedaços medidos.

| | vol. 2 total | corpo | notas | substituições nas notas | US$ capítulo | vol. 1 total | notas | substituições nas notas |
|---|---|---|---|---|---|---|---|---|
| pipeline | 3,12% | 6,82% | 2,24% | 154 | — | 5,98% | 4,60% | 72 |
| **Haiku** | 0,89% | 3,08% | 0,34% | 12 | **0,14** | 1,22% | 0,40% | 4 |
| Sonnet | 0,83% | 3,13% | 0,25% | 6 | 1,09 | 1,50% | 0,75% | 10 |
| Opus | **0,77%** | 2,99% | **0,23%** | **4** | 1,79 | **1,12%** | **0,34%** | **3** |

- O que sobra no **corpo** é praticamente igual nos três: artefatos da medição (números dos `\pgn`,
  das teses e as entradas `\addcontentsline` contadas como palavras) e erros de estrutura do pipeline,
  que o modelo é proibido de mexer. Não é erro de leitura.
- **Haiku** custa ~1/8 do Sonnet e ~1/13 do Opus e fica a 0,1 ponto deles no total. Nas notas
  (latim, letra pequena) ainda deixa 3× os erros do Opus. Também é o que mais desrespeita a
  estrutura: a única recusa legítima da rodada final foi dele (p. 430, que copiou uma nota da página
  seguinte; acertou na 2ª chamada). As outras recusas (333 nos três modelos, 340 no Haiku) eram linhas
  repostas, recusadas por um critério anterior e aceitas com `--revalida`.
- **Sonnet** não vale o preço: custa 8× o Haiku e no vol. 1 ficou pior que ele.
- **Opus** é o melhor em todas as medidas, a US$ 0,08–0,13 por página.
- Em tokens (o que pesa no limite de 5 h), por página: Haiku ~14 k de entrada + ~10 k de saída (pensa
  muito), Opus ~10 k + ~2 k. A rodada final inteira (3 modelos, 79 pedaços) custou US$ ~4 e não chegou
  perto do limite.

**Recomendação:** Opus para a revisão final do livro (≈ 1750 páginas impressas × US$ ~0,10 ≈ US$ 175
em preço de API; por assinatura, rodar em lotes de alguns capítulos por janela de 5 h). Se o custo pesar, Haiku
como primeira passada e Opus só nos pedaços de nota longa/latim. Em qualquer caso, conferir
`resultado.json → falhas` e o `relatorio.md`, que lista as dúvidas do modelo.

## Pendências

- O que sobra são erros de **estrutura** (nota fora do lugar, `\pg` deslocado, p. ex. o `\pg{427}`
  colado ao 428 no vol. 2), que pedem um passo à parte e sem esta regra de congelamento.
- `mede_wer.py --tex` conta os números de `\pgn`/teses como palavras inseridas. Isso infla o WER do
  corpo igualmente para todos (~35 "inserções" no vol. 2).
- Os números são de um capítulo + 4 páginas: diferenças de 0,1 ponto entre modelos estão dentro do ruído.
