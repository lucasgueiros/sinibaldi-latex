# Revisão final por LLM — comparação de modelos (2026-11-11: concluída, ver `docs/09-revisao-llm.md`)

Branch `worktree-pdfs-revisao-modelos` (worktree `.claude/worktrees/pdfs-revisao-modelos`).

## Pedido
1. Rodar os scripts até os PDFs. 2. Agentes Sonnet e Haiku (depois também Opus) fazem a revisão
final de um capítulo de cada volume. 3. Comparar qual modelo compensa. Também: prompt salvo e um
script para passar um agente num trecho via `claude`.

## Feito
- `tools/gera_volume.sh vol1|vol2 --imagens <checkout principal>/volN/paginas` → `build/vol1.pdf`
  (1757 pp.) e `build/vol2.pdf` (1577 pp.); TEI/correções saíram idênticos aos versionados (só 8
  `.fmt.tsv` com diferenças de 1–2 linhas, restaurados). ~15 min, quase tudo na etapa de formatação.
  No worktree, `.venv` é um symlink para o do checkout principal (não versionado).
- Capítulos escolhidos por terem padrão-ouro: vol. 2 *Existencia de Deus* (pp. 421–442, ouro
  inteiro) e vol. 1 *Divisão do ente* (pp. 331–359, ouro só 331–334). Entrada comum em
  `revisao-modelos/entrada/volN.tex`.
- Linha de base (pipeline, WER total/corpo/notas): vol2 3,12/6,82/2,24%; vol1 (331–334)
  5,98/12,06/4,60%.
- `tools/mede_wer.py --tex X.tex -f P -l Q`: mede um .tex revisado cortado pelos `\pg`
  (o ouro contra si mesmo dá 0,00%). Para trecho parcial corta o ouro também, mas notas que
  continuam fora da faixa inflam o número; para capítulo inteiro é exato.
- `tools/trecho.py`: dois bugs corrigidos no recorte por título — arrastava a matéria preliminar
  (páginas de `<pb n>` negativo nunca entravam na lista de remoção) e perdia o `\pg` da página
  inicial (ficava na `<div>` anterior, apagada por vazia).
- `tools/revisa_trecho.sh` + `tools/prompts/revisao_trecho.md`: `claude -p` num diretório temporário
  fora do repo (sem CLAUDE.md do projeto, memória, MCP; `--bare` se houver `ANTHROPIC_API_KEY`), só
  Read/Edit/Write/Bash(python com PIL). Saída: `revisado.tex`, `relatorio.md`, `resultado.json`,
  `wer.txt`. Teste com Haiku em 2 páginas: OK (22 turnos, 2 min, US$ 0,03).
- `revisao-modelos/roda.sh` (3 modelos × 2 capítulos em paralelo) e `revisao-modelos/compara.py`
  (tabela WER + custo).

## O que deu errado: consumo
1. Primeira tentativa: subagentes Sonnet e Haiku (ferramenta Agent) bateram no limite de 5 h logo no
   início (Sonnet não alterou nada; Haiku, 2 linhas). Descartados.
2. Segunda: `roda.sh` com 6 sessões `claude -p` em paralelo. Todas pararam em 6–7 min com
   "You've hit your 5-hour limit" (zera 21:50). Saídas parciais em `revisao-modelos/<m>/<vol>/`:

| sessão | turnos | US$ | cache lido | cache escrito | saída |
|---|---|---|---|---|---|
| haiku vol1 | 123 | 0,40 | 3,15 M | 162 k | 94 k |
| haiku vol2 | 130 | 0,43 | 2,81 M | 187 k | 95 k |
| sonnet vol1 | 58 | 1,71 | 1,42 M | 218 k | 69 k |
| sonnet vol2 | 53 | 1,62 | 2,01 M | 193 k | 65 k |
| opus vol1 | 54 | 3,35 | 3,37 M | 194 k | 56 k |
| opus vol2 | 174 | 2,79 | 2,51 M | 180 k | 42 k |
| **total** | | **10,29** | **15,3 M** | | |

Causa provável (a verificar): cada turno relê o contexto inteiro, que cresce com (a) o `.tex` do
capítulo lido inteiro (77–120 KB ≈ 30–40 k tokens), (b) cada imagem de página 1755×2481 lida
(e os recortes), que ficam no contexto até o fim, (c) 50–170 turnos (um Edit por correção).
Contexto médio de ~20–60 k tokens × ~100 turnos × 6 sessões ≈ 15 M tokens de cache. Somado às
sessões anteriores do dia (a principal também estava ativa), estourou a janela de 5 h.

## Retomada (2026-11-11, noite): revisão por página — CONCLUÍDA
Branch `worktree-revisao-por-pagina` (o worktree antigo sumiu; o commit dele já estava no master).
- `tools/revisa_paginas.py` + `tools/prompts/revisao_pagina.md`: uma chamada `claude -p` de 1 turno por
  pedaço (cortado nos `\pg`), sem ferramentas, imagens embutidas (stream-json), estrutura congelada,
  validador e 2ª tentativa. `revisao-modelos/roda_por_pagina.sh`, `compara.py <dir>`, `wer_paginas.py`.
- Resultado em `revisao-modelos/por-pagina/` e `docs/09`: vol. 2 WER 3,12% → Haiku 0,89% (US$ 0,14) /
  Sonnet 0,83% (US$ 1,09) / Opus 0,77% (US$ 1,79); vol. 1 (331–334) 5,98% → 1,22 / 1,50 / 1,12%.
  Rodada inteira US$ ~4, sem tocar o limite de 5 h. Recomendação: Opus (Haiku se o custo pesar).
- As saídas parciais da tentativa com agente (`revisao-modelos/{haiku,sonnet,opus}/`) ficam só como
  registro do problema de consumo.

## Próximos passos possíveis
- Rodar Opus no resto dos volumes em lotes (`tools/trecho.py … -F tex` → `revisa_paginas.py`).
- Passo à parte para erros de estrutura (nota fora do lugar, `\pg` deslocado), que a revisão congela.
