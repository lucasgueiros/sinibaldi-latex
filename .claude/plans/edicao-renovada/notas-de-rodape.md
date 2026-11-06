# Notas de rodapé: separar do corpo e unir as que atravessam páginas

Parte de `plano.md`, fase F2. Medido nas pp. 421–422 do vol. 2 (300 ppi, hOCR do tesseract).

## O que o livro faz (observado, não suposto)

- A área de notas começa abaixo de um **filete curto** à esquerda e é composta em corpo menor.
- **Entrelinha** (distância entre linhas consecutivas) é o discriminador estável:
  corpo **51–53 px**, notas **42–43 px**. O `x_size` do hOCR oscila demais (25–37 nas notas)
  e não serve.
- Entre a última linha do corpo e a 1.ª da nota há um **vão de 115–131 px** (o filete está nele).
- As notas são numeradas `(1)`, `(2)`… **recomeçando em cada página**; a nota nova começa com
  `(n)` recuado (~70 px além da margem).
- Linha recuada **sem** `(n)` dentro da área de notas é **parágrafo novo da mesma nota**
  (p. 422: "Por se sufficientemente conhecida…").
- **Continuação:** se a área de notas começa por uma linha **sem** `(n)`, é o resto de uma nota
  da página anterior. p. 421 abre com "de uma *psychologia*…" (fim de nota da p. 420); a nota (2)
  da p. 421 ocupa **toda** a área de notas da p. 422, onde o corpo tem só 3 linhas. Uma nota pode,
  portanto, atravessar várias páginas, e uma página pode ser quase só nota.
- As margens mudam entre página par e ímpar (x0 ≈ 186 vs. 256): toda medida horizontal é
  **relativa à margem da própria página** (moda dos x0 das linhas).
- Lixo de borda (um `3` isolado em x0 = 1738) cai fora da coluna de texto e é descartado pelo bbox.

## Modelo: dois fluxos independentes

O livro tem **dois textos correndo em paralelo**: o corpo e as notas. Cada um atravessa as páginas
por conta própria. Então o script não "procura o fim da nota". Ele:

1. Separa, em cada página, as linhas em `cabeçalho | corpo | notas`.
2. Concatena **todas as áreas de notas do volume** num único fluxo, na ordem das páginas, com um
   marcador de página `⟦pág 422⟧` em cada virada.
3. Corta esse fluxo em notas pelos inícios `(n)`. Tudo o que vem antes do 1.º `(n)` de uma página
   pertence à última nota aberta, mesmo que essa nota tenha começado três páginas antes.
4. Liga cada nota à sua chamada `(n)` no corpo **da página em que a nota começa**.

## Algoritmo de separação, por página (`tools/estrutura_pagina.py`)

1. **Cabeçalho**: 1.ª linha da coluna, se for curta em altura e contiver o número impresso
   (conferido com o manifesto) ou um título corrente conhecido. Vai para o JSON, não para o texto.
2. **Fronteira corpo/notas**: o 1.º ponto, de cima para baixo, onde:
   - a entrelinha passa de ~52 para ~43 **e permanece** assim até o pé da página; e
   - há um vão maior que ~2 entrelinhas antes; e
   - (confirmação) há um filete: na imagem, uma faixa horizontal fina e escura, de 150–300 px,
     encostada à margem esquerda, dentro do vão. Isso é medido com projeção horizontal da imagem
     (PIL/numpy), sem OCR.

   As duas medidas, entrelinha e filete, são calibradas por volume com a moda das páginas, não fixas.
3. **Por que exigir "até o pé da página"**: o corpo também tem trechos em tipo menor (citações em
   bloco, o *Summario*). Um bloco de entrelinha pequena **no meio** da página, sem filete, é citação
   (`quote`) e não nota.
4. **Notas da página**: dentro da área, uma linha que casa `^\s*\((\d{1,2}|[lI])\)` com recuo de
   início de parágrafo é **início de nota**. O que vem antes do primeiro início é **continuação**.

## Validações automáticas (cada falha vira um alerta no JSON da página)

- **Chamadas × notas**: o conjunto de chamadas `(n)` no corpo da página deve ser exatamente o
  conjunto de notas que **começam** nela, e ambos devem ser `1..k` em sequência. Essa expectativa
  corrige o dígito mal lido: `(l)` → `(1)`, `(4)` onde se esperava `(2)`.
- **Continuação coerente**: se a página N+1 começa com continuação, a última nota da página N não
  deve terminar em pontuação final. Se termina e mesmo assim há continuação, emite alerta e mantém
  a continuação (pode ser um parágrafo novo da nota, como na p. 422). O caso inverso também gera
  alerta: a nota de N termina sem pontuação, e N+1 começa com `(1)` ou não tem notas.
- **Página sem filete com entrelinha de nota no pé**, ou com filete mas sem mudança de entrelinha:
  vai para a fila de revisão.
- Ao fim do volume, a soma de chamadas deve ser igual à soma de notas.

Na prática, só as páginas com alerta precisam de atenção especial. A revisão LLM da fase F6 vê a
imagem de todas as páginas e recebe os alertas da página como dica do que olhar.

## Saída

No JSON de cada página: `corpo` (linhas), `notas_iniciadas` (`n`, texto até o pé da página),
`continuacao` (texto, id da nota a que pertence) e `alertas`. O fluxo unido fica em
`volN/notas.jsonl`, uma nota por linha:

```json
{"id": "421-2", "pag_chamada": 421, "n": 2, "paginas": [421, 422, 423],
 "texto": "Os systemas, que contestam ... ⟦pág 422⟧ revelação ou pela tradição ..."}
```

## No LaTeX

- `\footnote{…}` inteiro **no ponto de chamada**, como no capítulo já transcrito à mão.
- Dentro da nota, cada virada de página do original vira `\pgn{422}`, uma variante discreta de
  `\pg`. Isso mantém a citação exata ("p. 422, n.") sem quebrar a nota. Pode ser ocultado por chave
  no preâmbulo, como já se faz com `\semnotas`.
- O `\pg{n}` do corpo continua marcando só as viradas do corpo. São dois fluxos, cada um com os
  seus marcadores.

## Casos raros, tratados à mão se aparecerem

Nota que remete a outra nota; nota com chamada no título; página de nota sem nenhuma linha de
corpo. Todos são detectáveis pelas validações acima, por isso não ficam escondidos.
