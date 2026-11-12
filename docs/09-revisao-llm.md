# Revisão final por LLM (`tools/revisa_paginas.py`)

Última etapa do texto: um modelo (Haiku) compara o **TEI** do pipeline com a imagem de cada página e
devolve o fragmento corrigido, inclusive a **fronteira entre corpo e nota de rodapé**. Medido nos dois
padrões-ouro (`docs/07`) em 2026-11-12.

```bash
python3 tools/trecho.py vol2:existencia-de-deus -F tei -o ENTRADA.xml
python3 tools/revisa_paginas.py ENTRADA.xml --vol vol2 --saida DIR [--paralelo 3]     # Haiku (padrão)
python3 tools/revisa_paginas.py ENTRADA.xml --vol vol2 --saida DIR --seco             # só mostra os pedaços
python3 tools/revisa_paginas.py ENTRADA.xml --vol vol2 --saida DIR --so 430 --refaz   # refaz um pedaço
python3 tools/revisa_paginas.py ENTRADA.xml --vol vol2 --saida DIR --revalida         # validador novo, sem chamadas
revisao-modelos/roda_por_pagina.sh [modelos]        # medição nos dois ouros → revisao-modelos/por-pagina-xml/
python3 revisao-modelos/compara.py revisao-modelos/por-pagina-xml
```

Saída em `DIR`: `revisado.xml` (o documento de entrada com os pedaços revisados), `entrada.tex` e
`revisado.tex` (`tei2latex.py --puro`, para ler e compilar), `wer.txt` (`mede_wer.py --xml` antes e depois),
`relatorio.md` (o que o modelo diz ter corrigido, as dúvidas e **toda mudança de fronteira**),
`resultado.json` (custo, tokens, recusas, `fronteira` por pedaço) e
`paginas/NNNN.{entrada,revisado,rejeitado}.xml` + `.json`. Rodar de novo retoma de onde parou.

## Como funciona

- **Pedaços.** O XML é cortado nos `<pb n>` do *corpo*. Os `<pb>` de dentro de `<note>` marcam onde a nota
  continua e não cortam. Páginas para onde uma nota do pedaço continua ficam no mesmo pedaço, até
  `--max-car` (9000 caracteres de texto), porque o conserto de uma fronteira mexe nas duas páginas.
  Páginas de pura continuação de nota juntam-se à anterior. O fragmento pode começar e terminar no meio de
  elementos (`</p></div><div …>`), e o prompt manda manter essas tags soltas.
- **Uma chamada por pedaço, sem ferramentas** (`claude -p --tools "" --system-prompt
  tools/prompts/revisao_pagina.md`, imagens embutidas via `--input-format stream-json`, cache de prompt
  desligado). Cada página vai em duas metades cinza de ≤ 1568 px. Resposta em `<xml>…</xml>` + `<notas>`.
- **Pistas.** Na mensagem vão os alertas do estruturador para as páginas do pedaço
  (`volN.estruturado.alertas.tsv`: `nota-sem-chamada`, `corte-incerto`, `continuacao-duvidosa`,
  `chamadas-x-notas`, `vao-nas-notas`, `nota-recuperada`, `numero-diverge`). Se a entrada é um trecho, o
  script lê `volN.corrigido.xml` e avisa onde o trecho começa e termina no meio de uma página, com as
  palavras que ficam de fora (`--volume`).
- **Fronteira corpo/nota.** O modelo pode: tirar da nota o texto de corpo que ela engoliu; levar ao
  `<note>` o começo ou fim de nota solto no corpo; criar a `<note>` que ficou inteira no corpo; mover a nota
  "anexada ao fim do último parágrafo" para o ponto da chamada; religar a continuação de nota à nota certa;
  separar notas coladas. O prompt dá a regra visual (nota = letra pequena no pé da página, depois do corpo,
  aberta por "(n)" ou continuação no alto da área de notas). Também diz que notas longas, de vários
  parágrafos, continuam notas.
- **Validador** (`valida()`). A resposta é recusada quando:
  - o XML fica mal formado, checado no documento inteiro, com o pedaço no lugar;
  - os `<pb>` do corpo mudam, ou um `<pb>` de nota fica fora das páginas do pedaço;
  - aparece um elemento que o TEI não usa, um `rend` desconhecido ou um `xml:id` repetido;
  - há texto duplicado (mais de 30 sequências de 10 palavras a mais que na entrada, ≈ 40 palavras), ou
    texto copiado do pedaço seguinte ou de fora do trecho (mais de 12);
  - o texto total muda mais de max(4%, 200) + 180 caracteres por página;
  - passa texto demais entre corpo e nota: corpo→nota acima de `--troca-max` (2500), nota→corpo acima
    de `--nota-corpo-max` (800).

  Quando o XML vem mal formado, `repara()` repõe as tags soltas das pontas e os `</div>` que o modelo
  levou junto ao apagar lixo antes de um título (vol. 2 p. 438). O reparo só fica se a resposta então
  passar. Recusada, há uma 2ª chamada que diz o motivo. Se ela também falhar, fica o texto do pipeline e o
  pedaço vai para `falhas`.

## A "1ª linha perdida" era do recorte, não do OCR

A rodada sobre o `.tex` (abaixo) via o pipeline perder a 1ª linha do corpo de muitas páginas e mandava o
modelo repô-la. A causa era `tools/trecho.py`. Ele removia `<fw>` (cabeçalho corrente) e `<pb>` com lxml,
que apaga junto o `tail` do elemento, e a 1ª linha da página é justamente o tail do `<fw>`. Corrigido com
`tira()`. Só isso leva o WER do corpo de base no ouro do vol. 2 de 5,00% para 2,80% (deleções 50 → 3); no
vol. 1 (331–334), de 9,05% para 6,78%. Tudo o que saiu de `trecho.py -F tei|tex` antes de 2026-11-12
tinha essa perda.

## Resultado (2026-11-12, Haiku sobre TEI)

WER contra o ouro, medido no XML (`mede_wer.py --xml`). vol. 2 = capítulo *Existencia de Deus*
(pp. 421–442, 11 pedaços); vol. 1 = capítulo *Divisão do ente* inteiro (18 pedaços), medido nas pp. 331–334
que o ouro cobre.

| | vol. 2 total | corpo | notas | vol. 1 total | corpo | notas | US$ (2 capítulos) |
|---|---|---|---|---|---|---|---|
| entrada (recorte corrigido) | 2,18% | 2,80% | 2,06% | 4,86% | 6,78% | 4,42% | — |
| **Haiku, TEI** | **0,41%** | **1,26%** | **0,20%** | **0,75%** | 1,26% | 0,40% | **0,45** |
| *rodada antiga sobre .tex:* Haiku | 0,89% | 3,08% | 0,34% | 1,22% | — | 0,40% | 0,37 |
| *rodada antiga sobre .tex:* Opus | 0,77% | 2,99% | 0,23% | 1,12% | — | 0,34% | — |

(As linhas antigas partiam do recorte com a 1ª linha perdida e eram medidas no `.tex`. A comparação não é
exata, mas a ordem de grandeza vale.)

- **Fronteira, casos reais consertados.** No vol. 1 p. 349, a nota (1) estava solta no corpo e foi para
  a chamada; a nota (2) estava presa à chamada errada e foi para "differença (²)". Conferido na imagem.
  No vol. 1 pp. 334–335, notas levadas ao ponto da chamada, duas notas coladas separadas, nota (3) criada com
  a continuação na 336. No ouro do vol. 1, o corpo caiu de 6,78% para 1,26%.
- **O erro típico do Haiku**, visto na 1ª rodada (antes das travas): esvaziar no corpo os parágrafos
  finais de uma nota longa (vol. 2 p. 441: 1567 caracteres de nota viraram corpo depois do § 21). Ele
  também transcrevia o que fica na página antes do começo do trecho (o § 5 e a nota 1 na p. 421). Daí o
  limite nota→corpo de 800, o aviso de limites do trecho e o reforço no prompt. Na 2ª rodada, nenhum dos
  dois se repetiu.
- **Recusas** na rodada final: 1 em 29 pedaços (vol. 1 p. 357, fora do ouro: a resposta repetia texto e
  terminava fora do lugar; ficou o texto do pipeline). Três outras respostas foram aproveitadas com
  `--revalida`. Na 425, a duplicação de 13 palavras era real no livro, o OCR tinha perdido uma ocorrência,
  e o limite antigo era baixo demais. A 438 foi consertada por `repara()`.
- **Custo:** US$ ~0,01–0,04 por pedaço; tokens por pedaço ~10–60 k de entrada e ~10–70 k de saída (Haiku
  pensa muito). ≈ 1750 páginas do livro ≈ US$ 15–20 em preço de API.

## Pendências

- Conferir no `relatorio.md` e em `resultado.json → fronteira` cada mudança de fronteira até haver
  medição de fronteira num ouro com mais casos: o ouro do vol. 2 quase não tem erros desse tipo.
- `resultado.json → falhas`: esses pedaços ficam sem revisão. Rodar `--so N --refaz`, ou passar um modelo
  maior só neles.
- O limite de duplicação (≈ 40 palavras) deixa passar duplicações curtas. O `wer.txt` e o relatório são a
  conferência.
- `tei2latex` às vezes posiciona um `\pg` de outro jeito quando a nota muda de lugar (vol. 1: 30 → 29
  `\pg`, com os mesmos `<pb>` no XML).
- A rodada antiga (agente com Read/Edit, `tools/revisa_trecho.sh`, e por página sobre `.tex`,
  `revisao-modelos/por-pagina/`) fica como histórico. No `.tex` a estrutura tinha de ficar congelada, porque
  ali Haiku "consertava" notas longas passando ~1900 palavras de nota para o corpo. No TEI, com as travas
  acima, a fronteira pode ser corrigida.
