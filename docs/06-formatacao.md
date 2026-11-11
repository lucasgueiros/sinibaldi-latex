# Formatação tipográfica medida na imagem (itálico, versalete, negrito)

O tesseract LSTM não informa estilo, mas o `<id>.tsv` de cada página traz a caixa de cada
palavra e o `<id>.png` (de `tools/extrai_paginas.py`) tem os pixels. `tools/formatacao.py` mede o
estilo palavra a palavra e grava `<id>.fmt.tsv` ao lado do `.tsv`; `tools/estruturar_tei.py`
lê esse arquivo e emite `<hi rend="it|sc|bold">`, que `tools/tei2latex.py` já convertia em
`\emph` / `\textsc` / `\textbf`.

```bash
python3 tools/formatacao.py vol2/paginas [--imagens DIR] [-f P -l P]   # -> vol2/paginas/<id>.fmt.tsv
python3 tools/mede_formatacao.py                                       # P/R contra o padrão-ouro
python3 tools/formatacao.py vol2/paginas --treina-versalete            # refaz tools/dados/versalete.json
tools/gera_volume.sh vol2 [--imagens DIR] [-f P -l P]                  # cadeia inteira até build/volN.pdf
```

As medições ficam em cache (`<id>.medidas.pkl`, git-ignorado): mudar só os parâmetros de decisão
(`P` no topo de `formatacao.py`) e rodar de novo leva ~30 s por volume; medir as imagens do zero,
~10 min por volume com 4–5 processos. O `.fmt.tsv` é versionado (block, par, line, word, texto,
ang, swr, vsc, rend): dá para auditar e corrigir à mão uma palavra.

## O que se mede

| traço | como | romano | estilo |
|---|---|---|---|
| `ang` | ângulo de cisalhamento (−12°…30°) que maximiza a soma dos quadrados do histograma de colunas da tinta, menos a mediana da página | ≈ 0° (p95 = 1°) | itálico 12–16° (p5 = 6,7°) |
| `swr` | comprimento médio das corridas horizontais de tinta, sobre a mediana das romanas da página, separado por tamanho de letra (corpo × notas) | ≈ 1,0 (p99,8 = 1,26) | itálico ≈ 0,80; negrito ≈ 1,38 |
| `vsc` | família *Deus/Dei/Deum*: recorte após a inicial, na altura da inicial, 30×14, distância ao gabarito versalete menos ao minúsculo | < 0 | > 0 |

Itálico de letras redondas (`causa`, `mesma`, `menos`) inclina pouco (2–5°), mas o traço é fino:
por isso a evidência é uma logística em `ang`, `swr` e `ang·swr` (99,85% de acerto nas palavras
de ≥ 4 letras do ouro). Palavras curtas não decidem sozinhas: um Viterbi de 2 estados na ordem
de leitura da página pesa a evidência pelo nº de letras e cobra para trocar de estado; acento
agudo em palavra de 1–2 letras (`é`, `à`, `só`) é inclinado e tem peso zero.

Versalete: o livro a usa quase só em **DEUS** (129 das 132 do ouro), e no mesmo parágrafo há
"Deus" em minúscula — o léxico não decide, a forma decide. Tamanho e largura relativos não
separam (miolo 0,64 × 0,65 da inicial); o que separa é o desenho (`E` de haste reta × `e`
redondo): gabarito médio de cada classe, aprendido no ouro (`tools/dados/versalete.json`),
reajustado em cada volume por 2-médias (outra impressão no vol. 1). Validação deixando uma
página de fora: 97% de acerto. Fora da família, versalete = palavra que o OCR leu com ≥ 2
maiúsculas após a inicial e cujo miolo é ≤ 0,82 da inicial, em linha minúscula (título em caixa
alta não conta).

Negrito: `swr ≥ 1,32` com ≥ 4 letras; palavra de 2–3 letras só com `swr ≥ 1,42` **e** vizinha de
negrito longo (senão `no`, `se`, `em` e fragmentos de hifenização viram negrito). O negrito que
importa — enunciado de tese, títulos — já vem da estrutura; o detector pega o negrito avulso.

## Resultado (vol. 2, pp. 421–442, 8 807 palavras que casam com o ouro)

| | ouro | P | R | F1 |
|---|---|---|---|---|
| itálico | 844 | 98,3% | 96,7% | 97,5% |
| versalete | 61 | 100% | 95,1% | 97,5% |
| negrito | 40 | 75% | 37,5% | 50% |

Validação cruzada do itálico (parâmetros escolhidos nas páginas ímpares e medidos nas pares, e
vice-versa): F1 97,9% e 95,4%. Antes da logística (limiares fixos em `ang`), F1 90,1%. O
negrito "perdido" é quase todo enunciado de tese e título (marcados pela estrutura, onde as marcas
são descartadas de propósito); o ouro rotula títulos de secção como romano.

Volume inteiro: vol. 2, 47 393 palavras em itálico, 2 294 em versalete, 2 274 em negrito.

## Como a marca atravessa o estruturador

A estrutura (corpo × notas, parágrafos, teses, títulos) é decidida no texto **limpo**
(`Linha.texto`), como antes. O texto com marcas (`Linha.marc`: caracteres de uso privado
U+E010–E012 abre, U+E020–E022 fecha, só em volta do núcleo da palavra — pontuação e chamada
`(n)` ficam fora) é o que entra nos parágrafos; `hifen()` decide sobre o texto limpo e devolve o
marcado. Um passe final (`aplica_marcas`) funde corridas vizinhas do mesmo estilo, estende a
palavra inteira um estilo que começa ou termina no meio dela (`ultraphe-` itálico + `nomenico`
lido como romano) e troca as marcas por `<hi>`; uma corrida aberta atravessa `<pb/>` e `<note>`
do mesmo elemento. Em `<fw>`, `<label>`, `<head>` e no enunciado da tese as marcas só somem.

Portões de regressão: sem `.fmt.tsv`, a saída é byte a byte a do estruturador anterior; com a
formatação, o texto é o mesmo (WER do ouro igual, 0 tokens diferentes). `corrige_ocr.py` corre
dentro dos `<hi>` (`<hi rend="sc">Dzvs</hi>` → `<hi rend="sc">Deus</hi>`).

## Limites

- Letra isolada em itálico (`b)`, `a)` das subdivisões) quase nunca tem tinta suficiente: herda dos
  vizinhos, e em geral os vizinhos são romanos.
- Versalete fora de *Deus* e de leituras em maiúsculas não é detectada (é rara no livro).
- Espacejado e corpo menor não são marcados aqui (o corpo menor já separa notas no estruturador).
- O ouro é um só trecho do vol. 2; o vol. 1 (outra edição) não tem ouro — conferir por amostra.
