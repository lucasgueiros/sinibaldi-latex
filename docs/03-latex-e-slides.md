# Arquitetura LaTeX (livro → PDF) e slides

Slides em LaTeX (beamer), sem LLM: `tools/gera_slides.py` (TEI → fonte `.slides.txt` → `.tex` →
PDF) com o tema da Academia em `tex/slides/`; o site gera, mostra e corrige (`web/README.md`, seção
"Slides"). O caminho antigo (`.slides.md` + LLM → `.pptx`) continua no fim deste arquivo.

## Marca de página impressa

Definida em `tex/preambulo.tex`:

```latex
\newcommand{\pg}[1]{\,{\footnotesize\textbf{[#1]}}\,}
```

`\pg{286}` imprime `[286]` no fluxo do texto, na posição exata onde a página virava no original.

`\asterisco` imprime o `∗` centrado em linha própria (divisão de assunto do original); vale no corpo, no meio do
parágrafo e dentro de `\footnote{…}`. No TEI: `<milestone unit="asterisco"/>` (inline ou entre blocos) ou um
`<p>*</p>`; `tools/tei2latex.py` converte ambos.

`\gravura{arquivo.png}{0.60}{legenda}` põe uma gravura recortada do fac-símile no ponto exato do original
(sem float, centrada, fração da largura do texto, legenda opcional em corpo menor). No TEI:
`<figure xml:id><graphic url="paginas/0034.png#xywh=x,y,l,a" width="60%"/><head>legenda</head></figure>` — a
caixa (fragmento de mídia W3C) é em pixels do PNG original da página. `tools/tei2latex.py` recorta a caixa com
Pillow (`--base`: pasta contra a qual resolver a url, padrão a do XML; `--dir-gravuras`: onde gravar os
recortes, padrão `build/gravuras`, caminho que o `.tex` cita). Sem a imagem, sai uma caixa «gravura
indisponível» com `% REVER`. As gravuras são marcadas pela web (tela de revisão da 1916, botão **Gravura**).
Os números vêm de `tools/extract_paginado.py` (ver `docs/02-numeracao-de-paginas.md`) — nunca do OCR
do cabeçalho. Sendo uma macro única, a aparência (margem, sobrescrito, cinza) muda depois sem tocar
no texto.

## Macros de estrutura do autor

`tex/preambulo.tex` também define (promovidas de um artigo transcrito à mão):

- `\tese{n}{título}` — enunciado de tese numerada correndo com o texto (segue travessão);
- `\teseB{n}{título}` — idem, em linha própria (quando vêm subdivisões `a)`, `b)`…);
- `\sub{a}{rubrica}` / `\subp{a}` — subdivisão com / sem rubrica em itálico.

Notas: por omissão saem no pé; com `\def\notascorridas{}` (via `-usepretex`) passam a correr no
corpo, num bloco recuado que interrompe a leitura; com `\def\semnotas{}` são suprimidas por
inteiro (chamada e conteúdo).

## Pré-visualizar um nó isolado

Atalho da raiz: `./compila.sh <capitulo> [--sem-notas | --notas-corpo]` → `build/<stem>[-…].pdf`
(ver `README.md`). Por baixo, `tex/_preview.tex` compila **um** fragmento com o mesmo preâmbulo do
livro:

```bash
latexmk -lualatex -usepretex='\def\fragmento{vol2/02_secao_x/01_cap_y/01_cap_y.tex}' tex/_preview.tex
```

### Compilar o fragmento avulso

Cada fragmento começa com um guarda que, se o arquivo for o documento principal (botão do editor,
`lualatex <stem>.tex` de dentro da pasta do nó), carrega `tex/avulso.tex` (classe + preâmbulo) e
fecha o documento no `\csname fimavulso\endcsname` final; dentro do livro/`_preview` não faz nada:

```latex
% !TEX program = lualatex
\ifdefined\pg\else\IfFileExists{tex/avulso.tex}{\input{tex/avulso}}{\input{../../tex/avulso}}\fi
...
\csname fimavulso\endcsname
```

Use **lualatex**. Com pdflatex o avulso também compila (preâmbulo alternativo inputenc/babel), mas só
para conferência. Livro inteiro: `latexmk -lualatex livro.tex`, com um `\input` por fragmento.

## Compilação

`lualatex` (Unicode + `fontspec`/`polyglossia`), via `latexmk`:

```bash
latexmk -lualatex livro.tex
```

Prova de conceito compilando hoje: `livro.tex` com `tex/exemplo-ontologia.tex`, exibindo `[37]` e `[38]`.

## Trechos nomeados

Trechos que serão usados depois (para os slides em PPTX, ou para citação) podem ser delimitados por
guardas em comentário no próprio `.tex`:

```latex
%%>>> ente-immutavel
\pg{37}\textbf{87. O ente immutavel...} --- ...
%%<<< ente-immutavel
```

`python3 tools/trecho.py tex/exemplo-ontologia.tex ente-immutavel` imprime o bloco. As guardas são
comentários LaTeX e não afetam a compilação. É só um atalho para recortar uma passagem do texto
revisado sem copiar e colar do meio do arquivo — o que se faz com o recorte depois é problema de
quem monta os slides.

## Fluxo de trabalho da transcrição

1. `python3 tools/corta.py <caminho-do-nó> <pág_ini> <pág_fim> --offset N` para recortar a faixa
   (gera `<stem>.pdf` + `<stem>.txt`; ver `docs/05`).
2. Revisar o `.txt` contra a imagem (`pdftotext` não substitui olhar a página).
3. Escrever `<caminho-do-nó>/<stem>.tex` como fragmento `\input`-ável, inserindo `\pg{n}` em cada
   quebra de página do original.

O seccionamento natural segue os parágrafos numerados do autor (`87.`, `88.`, …), não a paginação.

## Slides (beamer, sem LLM)

```bash
python3 tools/gera_slides.py base vol2/vol2.corrigido.xml --id v2.art-6 -o x.slides.txt   # fonte editável
python3 tools/gera_slides.py pdf  x.slides.txt -o x.pdf      # ou direto do TEI (mesmas opções de base)
python3 tools/gera_slides.py valida x.slides.txt             # mensagens "linha N: …"
python3 tools/gera_slides.py resumo vol1/vol1.corrigido.xml  # tipos de slide (calibração)
python3 -m unittest tools/test_gera_slides.py                # SLIDES_VOLUMES=1: texto integral dos 2 volumes
```

- **Fonte `.slides.txt`** (o que o editor humano corrige; nunca LaTeX): `=== tipo`, `# título`,
  `@ referência`, corpo com `! enunciado`, `- tópico` (`  - ` aninha), `> citação`, `Rótulo:: texto`,
  `+continua`; inline `*it*`, `**neg**`, `^sc^`. O cabeçalho de comentários `%` de cada fonte gerada
  repete a sintaxe. Todo texto é escapado ao virar `.tex` (fonte = entrada não confiável).
- **Tipos / telas** (tema `tex/slides/academia-slides.sty`, ver `tex/slides/README.md`): `capa`,
  `secao`, `tese`, `definicao`, `divisao`, `argumento`, `objecao`, `resposta`, `corolario`, `escolio`,
  `observacao`, `citacao`, `texto` — etiqueta e barra próprias por tipo; Cinzel + EB Garamond, cores do site.
- **Classificação** por regras do estilo do autor: `p type=` explícito manda; senão título em negrito
  da tese, "divide-se…", "X é…/chama-se…", silogismo `Ora … Logo …` → Maior/Menor/Conclusão (os
  conectivos viram rótulo), "Corollario", "Objecção", subdivisões `a)`/`1.º`/`I.` → um slide cada.
  Todo o texto do corpo (sem notas) aparece, literal e na ordem — exceto lixo de OCR isolado (`|`).
- **Paginação** estimada em linhas, medidas no tema (parágrafo 8 linhas de ~68 car.; `rotulados`
  9–10 linhas de ~64; enunciado ≤ 5 linhas de ~56); `--max-car` (padrão 544) é a escala. Se o tema
  mudar de métricas, recalibre (`allowframebreaks` só segura transbordo residual: meta = 0 páginas "continuação").
- Medido: vol. 1 → 4051 slides, vol. 2 → 2331; `texto` = 49% / 29% dos de conteúdo (vol. 1 pior: TEI
  ainda fragmentado). `v2.art-6`: 12 slides, ~8 s; `v2.cap-1` (345 blocos): 266 slides, ~45 s.

### Caminho antigo (PPTX via LLM)

```bash
python3 tools/gera_slides_base.py <caminho-do-nó>/<stem>.tex     # -> <stem>.slides.base.md
#   um slide por trecho %%>>> id, com o texto do livro em citação
# LLM: mantém o texto citado EXATO, acrescenta título/tópicos/explicação, salva <stem>.slides.md
.venv/bin/python tools/md2pptx.py <caminho-do-nó>/<stem>.slides.md   # -> <stem>.pptx
```

A fonte a versionar e reeditar é o `.slides.md`; `.slides.base.md` e `.pptx` são reproduzíveis.

## TEI → LaTeX (dois passos)

`tools/estruturar_tei.py <volN>/paginas -o <volN>/<volN>.estruturado.xml [-f P -l P]` lê o
`manifesto.tsv` e o `.tsv` do tesseract de cada página (geometria) e produz o TEI estruturado:
`div` parte/seccao/capitulo/artigo/tese, `head`, `argument`, `label`, `hi rend="bold"`, `fw`,
`pb` e notas `<note>` **no ponto da chamada** (com `<pb/>` interno quando atravessam páginas).
Separação corpo × notas por geometria, não por texto: tamanho da letra (largura por caractere, k-means por volume) + marcador `(n)` + continuação após o filete. Notas chegam a 18 páginas (vol. 2, nota 580-1); ~70% das palavras do vol. 2 estão em notas, como no trecho transcrito à mão (421–442: 8847 palavras em notas contra 8921 geradas).
Tudo que a heurística não fecha vai para `<saida>.alertas.tsv` (revisão F6).

`tools/tei2latex.py <xml> [-f P -l P] [-o x.tex] [--puro] [--grafia original|atual]` converte o TEI
(estruturado, ou o bruto de `paginas2tei.py`) no dialeto de `tex/preambulo.tex`:
`\pg`, `\pgn`, `\tese`, `\footnote`, `\chapter*`/`\section*`, `latim`. Sem `--puro`, o `.tex`
compila avulso (`tex/avulso.tex`). Limitações conhecidas do estruturador: página com corpo
retomado depois de nota (alerta `vao-nas-notas`), tese cujo número o OCR leu mal (alerta
`tese-fora-de-sequencia`; a tese vira `<p>`), latim ainda não marcado com `xml:lang`. Itálico,
versalete e negrito vêm de `tools/formatacao.py` (`<id>.fmt.tsv` → `<hi rend>`; ver `docs/06`).

### Calibração por volume (resultado)

| | vol. 1 (1927) | vol. 2 (1916) |
|---|---|---|
| entrelinha corpo / nota | 51 / 39 px | 53 / 43 px |
| largura por caractere: limiar corpo × corpo menor | 18,3 (≈19,5 × ≈16,3) | 19,7 (≈21,5 × ≈17,5) |
| teses reconhecidas (numeração contínua) | 162 de ~243 | 231 de ~250 |
| notas / palavras em notas | 812 / 68% | 753 / 81% (padrão-ouro: 80%) |
| alertas | 823 | 224 |

(Até 2026-11-11 eram 688 / 727 notas: o corte corpo × notas exigia a conjunção de todos os
critérios e o tamanho da letra, mal medido, vetava notas inteiras. Hoje é por escore — abaixo.)

O limiar de tamanho é calculado sozinho (k-means no volume), então um terceiro volume não pede
ajuste manual. O tamanho de cada linha é medido só em linhas que terminam na margem direita (moda
dos x1): o OCR cola ruído da borda no fim de algumas linhas.

**Corte corpo × notas por escore** (`inicio_notas`/`escore_corte`): cada linha `k` que começa com
`(n)`, ou sem recuo havendo nota aberta, é um candidato; votos somados, nenhum veta: vão antes
(filete; linhas de 1–4 caracteres logo antes são o próprio filete lido pelo OCR), entrelinha da
cauda (nota ≈ 43 contra corpo ≈ 53), tamanho da letra na cauda e nas 2 primeiras linhas medidas
depois do corte, linhas de corpo no meio da cauda. Aceita com escore ≥ 3. Entre `(n)` quase
empatados fica o mais cedo; continuação só abre a área de notas e só ganha se superar o melhor
`(n)`. **Reparo por chamada**: se o corpo tem chamada e nenhum corte passou, aceita o melhor `(n)`
com escore ≥ 0,5 (alerta `corte-por-chamada`). **Nota aberta** também quando a página anterior
deixou chamada sem nota: a continuação vira a nota daquela chamada (alerta `nota-recuperada`).
Antes, uma continuação sem nota aberta era descartada; hoje vira nota `?` (alerta
`continuacao-sem-nota`). Decisões apertadas: alerta `corte-incerto`. Também: ruído de margem
(linha toda fora da coluna) e ornamento (linha curta de confiança < 60 acima do 1.º texto) são
descartados; o `<fw>` de página que continua parágrafo vai para dentro do `<p>`, junto do `<pb>`;
dehifenização de fim de linha consulta o léxico (`chamam-se` mantém o hífen se for ênclise,
`redu- Zir-se` → `reduzir-se`).

Medição: `tools/mede_wer.py` (padrão-ouro pp. 421–442, corpo e notas em separado). Nota no
lugar errado aparece como inserção no corpo e omissão nas notas.

## Correção automática do OCR (antes da F6)

`tools/corrige_ocr.py vol2/vol2.estruturado.xml -o vol2/vol2.corrigido.xml` → TEI corrigido +
`vol2/correcoes.tsv` (`pagina, xml:id, antes, depois, regra`): cada troca é auditável e reversível
por regra (`--sem lexico,a-grave`). Fora de `<fw>`, `<label>`, `xml:lang="la"|"fr"` e de trechos
com cara de latim/francês. Em ordem: regras de sequências impossíveis na grafia antiga (`ao`,
`cao`, `oe`, `a-grave`, `digito`, `deus`, `h-italico`) → léxico do corpus (frequência nos
`paginas/*.txt` dos dois volumes, **sem** o padrão-ouro) com tabela de confusões genérica, menos
trocas primeiro → `marca` (palavra de confiança < 60 sem correção: dica para a F6). O léxico nunca
troca forma aceita por dicionário (hunspell pt_PT/fr, pré-computado em `tools/dados/validas.tsv`
por `.venv/bin/python tools/lexico.py gera`, que precisa de `spylls`), nem forma recorrente
(≥ 10×) que difere só no acento (`fórma`, `áquella`, `tém`: decide a F6) ou em 2 letras.

Regras adicionadas depois (todas passaram pelo portão; cada uma, retirada, piora o WER): `deus`
só respeita o dicionário **pt** (`drus` é francês e bloqueava 655 `Drus`); `w` (w→u fora do
latim e dos nomes de `corrige_w`, só se a forma nova é válida ou tem ≥ 30 ocorrências);
`i-inicial` (`éntelligencia`, `zncredulos`: i itálico lido como ó/é/z/t); `acento-i` (tira o í/ú
que a grafia do livro não tem — `possível`, `espírito` — se a forma sem acento é ≥ 3× mais
frequente; í em hiato fica); `cedilha` (c→ç, mesmo sobre palavra válida como `forca`, se `força`
é ≥ 10× mais frequente); `enclitico` (`Provamolo` → `Provamol-o`); `of` (`Of.` → `Cf.`);
`romano` (`IIT`→`III`, `1I`→`II`); `junta` (palavra partida `in ferior`, só se a soma existe no
corpus e uma parte é fragmento; `n o` → `não`). No léxico, palavra curta e frequente (`eausa`, 59×)
cede a candidato ≥ 20× mais frequente, e forma longa aceita candidato de 10 ocorrências.
**3,97% → 3,45%** (corpo 5,04%; notas 3,10%).

Depois da união dos branches (2026-11-11, medições em `docs/07`): `crase` — o OCR nunca tira o
acento de `á` verdadeiro, só inventa: `á` → `a` onde a crase é impossível (depois de preposição;
antes de pronome, artigo indefinido, masculino em `-o`, infinitivo/masculino em `-r`); e, se o
documento tem `a` isolado com acento acima de 20% (vol. 1: 26,6%; vol. 2: 11,8%, a taxa normal),
`á` só fica depois de regente (`relação á`, `egual á`, `refere-se á`) ou antes de locução
(`á excepção`), aprendidos por `lexico.regentes_crase()`/`locucoes_crase()` do texto do vol. 2
fora do ouro (vol. 1: 47 dos 64 `á` do ouro eram `a`). `e-agudo` — o apóstrofo de `E'` (= É, vol.
2) lido como lixo colado (`E?`, `E!`, `E"`, `E^`, `E '`) → `E'`; e `E` + predicativo no início de
frase (`E certo`, `E impossivel`) → a grafia do volume (`E'` ou `É`, decidida pela contagem no
próprio documento). Fica para a F6: `a`/`á` depois de `e`/`é`/`que` no vol. 2, `e`/`o` isolados,
`3`/`8`, nomes próprios (`Kent`), letras faltantes (`r dicionalismo`), `Zntrinseca` (maiúscula
ambígua).

Portão: `python3 tools/mede_wer.py --corrige [--sem REGRA]` — nenhuma regra entra se piora o WER.
Resultado nas pp. 421–442 (1.ª versão): **5,93% → 3,97%** (corpo 8,7% → 5,8%; notas 5,3% → 3,6%), 205 palavras
corrigidas, 1 regressão (`opéram`). Cada regra, retirada sozinha, piora o WER. Vol. 2: 8 247
trocas; vol. 1: 15 769 (OCR `por` rápido; amostra de 40 trocas do léxico, ~37
certas; no ouro do vol. 1, `docs/07`: WER 19,8% → 17,1%). Chamadas de nota: o OCR do vol. 1 lê `(1)` como `(*)`/`(?)`; o estruturador pareia
chamadas e notas por ordem quando a contagem fecha. Teses: número lido é confiado se estiver à
frente da última (janela de 30); se voltar atrás ou estourar a janela, é corrigido apenas quando
difere do esperado em um dígito (905→205); tudo vai para os alertas `tese-fora-de-sequencia` e
`numero-corrigido`. Sem o OCR dos dígitos de volta, o que falta é revisão (F6), não calibração.
