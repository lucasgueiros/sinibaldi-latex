# Plano — edição renovada do Sinibaldi (grafia atualizada, editável)

**Objetivo.** Reconstruir a edição **"Sinibaldi 1916"** dos *Elementos de Philosophia* em
**TEI XML** (não um scan), com a **paginação original** (`<pb n="421"/>` → `[421]`), a estrutura do
autor (partes, capítulos, artigos, teses numeradas, notas) e saída em **grafia atualizada**
(AO 1990). Sobre ela se constrói uma **obra nova**, separada e ligada a ela trecho a trecho, com o
autor de cada trecho registrado. PDF (via LaTeX) e site (HTML) são gerados das duas.

**Princípio de custo.** Todo o trabalho mecânico (OCR, limpeza, estrutura, geração do LaTeX,
grande parte da modernização) é feito por script; a LLM entra no fim, **por página e com a
imagem**, só para corrigir o que o script não resolve — e a modernização ortográfica é feita
**por vocábulo**, não por página (ver F7), o que a torna quase grátis.

## Estado de partida (verificado em 2026-11-06)

- **Vol. 2** (ed. 1916, Antropologia/Theodicea/Moral): scan em
  `~/Downloads/SINIBALDI Thiago 1916 … Vol. 2 ….pdf` (413 folhas 2-up, imagem JPEG nativa de
  200 ppi, sem camada de texto; os dois arquivos em `Downloads` são idênticos, mesmo md5).
  Não há `vol2/vol2.pdf` nem `_div`/`_ocr` no repositório.
- **Vol. 1** (ed. 1897): **o PDF não está nesta máquina.** Precisa ser localizado/copiado.
- Já existe: `tex/preambulo.tex` (`\pg`, `\tese`, `\teseB`, `\sub`, `\subp`, notas comutáveis),
  `compila.sh`, `tools/corta.py`, `tools/corrige_w.py`, `tools/ocr_paginado.py`.
- **Padrão-ouro:** `vol2/02_parte_theodicea/01_cap_existencia-de-deus.tex` (pp. 421–442) foi
  transcrito à mão a partir da imagem. Serve para **medir** o erro do OCR e o ganho da revisão
  LLM antes de rodar o volume inteiro.
- Ferramentas: tesseract 5.3.4, `pdfimages`/`pdftoppm`, `mutool`, `lualatex`. `tessdata/lat`
  aponta hoje para a variante **fast** do sistema (3,1 MB), não a *best* medida em `docs/04`.
  `.venv` não tem `ocrmypdf` (e o plano não precisa dele).
- **Custo medido do OCR:** folha 215 do vol. 2 (2 páginas), `por_best+lat`, 1 thread:
  **23 s** → ~12 s/página. Volume de 826 pp. com 7 processos ≈ **25 min**. Confiança média 93,3;
  21 de 1160 palavras abaixo de 60.

## Arquitetura: a página é a unidade

```
vol2/
  paginas/                       # uma página do livro = um conjunto de arquivos
    manifesto.tsv                # impressa  folha  metade  (pdf_idx)  — única fonte da numeração
    0421.png                     # imagem da página (git-ignored, regenerável)
    0421.hocr                    # saída bruta do tesseract com coordenadas (git-ignored)
    0421.json                    # página estruturada: cabeçalho / corpo / notas / conf. por palavra
    0421.txt                     # texto limpo da página (VERSIONADO: pequeno, dá para dar diff)
  estrutura.tsv                  # um título por linha ← proposto por titulos.py (F4), revisado; fonte da estrutura
sinibaldi1916/                   # EDIÇÃO-BASE em TEI (grafia de 1916), congelada após revisão
  vol2.xml                       # volume: teiHeader + XInclude dos capítulos
  vol2/02_theodicea/01_existencia-de-deus.xml
ortografia/mapa.tsv              # 1916 → AO 1990, aplicado na SAÍDA (não altera a base)
obra-nova/                       # OBRA NOVA em TEI, ligada à base por ids (F8)
schema/sinibaldi.odd  .rng       # TEI restrito do projeto
```

Por que por página: (a) a numeração original é trivial — o nome do arquivo **é** a página
impressa, vinda do manifesto e não do OCR do cabeçalho (`docs/02`); (b) cada etapa é idempotente
e retomável página a página; (c) a revisão LLM é naturalmente "uma imagem + um texto"; (d) o
`git diff` de uma página mostra exatamente o que cada etapa mudou.

## Fases

### F0 — Preparação (minutos)
1. Copiar o scan do vol. 2 para `vol2/vol2.pdf`; localizar o `vol1.pdf` e copiar para a raiz.
2. Baixar `lat.traineddata` da `tessdata_best` para `tessdata/` (o atual é *fast*) e repetir a
   medição de `docs/04` numa página de latim denso: fica o que ganhar **no texto**, não na
   confiança.

### F1 — `tools/extrai_paginas.py`: imagem + OCR por página (≈25 min/volume, background)
- Extrai a **imagem nativa** de cada folha com `pdfimages` (sem reamostrar; o scan é 200 ppi),
  aplica `/Rotate`, corta ao meio (vol. 1 vertical; vol. 2 idem após rotação), e reamostra para
  300 ppi só na memória para o tesseract.
- Escreve `manifesto.tsv` (impressa ↔ folha/metade; vol. 2: impressa = 2·folha / 2·folha+1;
  vol. 1: pdf_div − 15) e confere contra os números OCR do cabeçalho como **checagem**, não fonte.
- Roda `tesseract -l por_best+lat --psm 1 hocr tsv` por página, `--jobs N`, pulando páginas já
  feitas. Substitui `mutool poster` + `ocrmypdf` (o PDF pesquisável deixa de ser necessário; se
  quiser um para consulta, `ocrmypdf` pode rodar à parte, sem bloquear nada).

### F2 — `tools/estrutura_pagina.py`: limpeza estrutural por página (segundos)
A partir das coordenadas do hOCR (é aqui que ele paga a complexidade que `docs/02` adiou):
- **cabeçalho corrente**: 1.ª linha no topo → removido do corpo, guardado no JSON (o texto dele,
  `SECÇÃO II — CAPITULO III`, alimenta F4);
- **notas de rodapé**: separadas do corpo pela entrelinha (corpo ~52 px, nota ~43 px), pelo vão
  e pelo filete; unidas entre páginas como **um fluxo próprio**, em que uma área de notas que
  começa sem `(n)` continua a última nota aberta. Detalhes, medições e validações em
  **[`notas-de-rodape.md`](notas-de-rodape.md)**;
- hifenização de fim de linha desfeita (`mo-\nvimentos` → `movimentos`), inclusive na virada de
  página (guardando o ponto exato da quebra para o `\pg`);
- parágrafos (recuo da 1.ª linha), teses `NN.` (sequência numérica conferida: o número esperado
  corrige dígito mal lido), `a)`, `b)`;
- `corrige_w` + tabela de erros recorrentes do próprio livro (`Dzvs`/`Drus` → `\textsc{Deus}`,
  `distineto` → `distincto`…), a crescer com o que F6 corrigir;
- confiança por palavra fica no JSON: palavras < 60 são marcadas para a LLM olhar.

### F3 — Vocabulário do corpus (segundos, alimenta F2 e F7)
Lista de todas as formas (`tipo → frequência, páginas`) do volume. Forma rara e de baixa
confiança perto de uma forma frequente (distância de edição 1–2) = provável erro de OCR, corrigível
por regra. É um corretor ortográfico **com o léxico de 1916 do próprio livro**, sem dicionário
moderno que "corrija" `philosophia`.

### F4 — `tools/titulos.py`: títulos → `estrutura.tsv` (o TSV manda)
O script detecta os títulos (centrado, escala, versal, negrito medido na imagem, vocabulário
`CAPITULO`/`ARTIGO`/`N.`) e **propõe** o `estrutura.tsv`, com uma linha por título (pág, âncora,
nível, rótulo, título, id). Depois de revisado, o TSV é a **única fonte da estrutura**: os arquivos
dos nós, as macros de título no LaTeX/HTML e o sumário saem dele. Corrigir uma divisão = mudar uma
linha e regenerar. O índice impresso, o cabeçalho corrente e a sequência das teses servem de
conferência cruzada, não de fonte. Detalhes em
**[`titulos-e-estrutura.md`](titulos-e-estrutura.md)**.

### F5 — `tools/pagina2tei.py`: TEI mecânico por capítulo
Para cada divisão do `estrutura.tsv`, concatena as páginas e gera o TEI bruto do capítulo: `<div>`
e `<head>` vindos do TSV; `<pb n facs>` no ponto exato de cada virada, no corpo e dentro das notas;
`<note place="foot">` inteiro na chamada; `<label>` das teses; `xml:lang="la"` no latim (o hOCR
indica a língua de cada parágrafo, e é o que protege o latim da modernização). Os ids são
provisórios nesta fase e só ficam definitivos no congelamento (F7). O XML é validado pelo schema
do projeto já na geração.

### F6 — Revisão LLM fiel (a etapa cara; por página, com a imagem)
Entrada por página: a **imagem** + o trecho do TEI bruto dessa página (entre dois `<pb>`) + palavras de baixa
confiança. Pedido: corrigir para ficar **idêntico ao impresso, grafia de 1916**, marcando
itálico e versalete (`<hi rend="it">`, `<hi rend="sc">`) — que o OCR não detecta e só a imagem mostra (o livro usa muito
itálico, por isso a imagem é necessária em todas as páginas). Saída: o trecho corrigido.

Salvaguardas automáticas, antes de aceitar: XML válido no schema; `<pb>` intactos e em ordem; variação de nº de palavras
< ~3% (detecta omissão/alucinação); latim não "traduzido"; marcação não inventada. Página que falha
volta para fila de revisão humana.

**Ordem de grandeza** (conferir preço vigente antes de rodar): ~5 k tokens/página (imagem ≈1,5–2 k
+ texto de entrada ≈1,5 k + saída ≈1,5 k) → ≈4 M tokens por volume. Usar a Batch API (metade do
preço, sem pressa) e cache do prompt de instruções.

**Portão de qualidade antes do volume inteiro:** rodar F1–F6 nas pp. 421–442 e comparar com o
`.tex` feito à mão (taxa de erro por caractere, só o texto): OCR cru vs. após F2/F3 vs. após F6.
Só escalar se F6 chegar perto do ouro; senão ajustar prompt/modelo e repetir no mesmo trecho.

Resultado: o TEI revisado do capítulo, em grafia de 1916.

### F7 — Grafia AO 1990 (na saída) e congelamento da base
Norma: **Acordo Ortográfico de 1990**, o mais recente, que vigora no Brasil desde 2016, na variante
brasileira, com referência no **VOLP da ABL**.

A base guarda a **grafia de 1916**, e a atual é uma **transformação na saída**. A maior parte da
modernização é função da palavra, não do contexto (`philosophia → filosofia`, `acto → ato`), então:
1. `tools/moderniza.py` gera candidatos por regra (`ph→f`, `th→t`, `y→i`, consoantes dobradas e
   mudas, acentuação) para o vocabulário da base, fora do latim e dos nomes próprios, e confere
   cada um contra as formas do VOLP.
2. A LLM revisa **a lista de tipos uma vez**, e não as páginas → `ortografia/mapa.tsv`, versionado
   e revisável por humano.
3. Os casos que dependem do contexto (`póde` → pode/pôde, `E'` → É, `para`/`pára`) são resolvidos
   no texto, um por ocorrência: `<choice><orig>póde</orig><reg>pode</reg></choice>`, com a LLM
   vendo a frase.
4. `tei2latex`/`tei2html` aplicam o mapa ao gerar a saída. A base continua fiel e as duas grafias
   saem da mesma fonte.

**Congelamento**: `tools/congela.py` atribui os ids definitivos (`cap-…`, `art-…`, `t6`, `t6.p1`,
`t6.p1.s1`, `n421-2`). A partir daí, os ids nunca mudam, e melhorias na base só entram como
`<sic>/<corr>`, `<reg>` ou nota do editor, com `@resp` e `@change`.

### F8 — Obra nova (contínua), em TEI ligado à base
As mudanças drásticas (dados científicos, ordem da exposição, posições filosóficas, problemas
teológicos posteriores, capítulos, citações, referências, notas) vão para uma obra separada, também
em TEI, ligada à base pelos ids: `copyOf` para trecho de Sinibaldi sem cópia (com a página
calculada pelo `<pb>`), `corresp` + `resp` para adaptado ou substituído, `@resp` obrigatório em todo
o resto, `<change>` com data, autor e motivo, e marco de supressão para o que sai. A cobertura, a
tabela de correspondência e o registro de mudanças saem de `tools/procedencia.py`. Detalhes em
**[`tei-base-e-obra-nova.md`](tei-base-e-obra-nova.md)**.

## Formato: TEI como fonte, LaTeX e HTML como saída

- **Fonte**: TEI XML restrito por uma ODD do projeto, nas duas obras (decisão do usuário para a
  base; recomendação para a obra nova, em `tei-base-e-obra-nova.md`).
- **PDF**: `tools/tei2latex.py` → `.tex` com o preâmbulo atual (`\pg`, `\tese`, notas,
  `compila.sh`) → `latexmk -lualatex`. O LaTeX passa a ser **gerado**, não editado.
- **Site**: `tools/tei2html.py`. `[421]` abre a imagem do scan, "cf. n. 6" vira link, as notas
  aparecem em popup, as grafias 1916 e atual podem ser comutadas, e na obra nova um trecho
  adaptado mostra o original ao lado.
- **Extração de trechos**: qualquer id → texto + página + capítulo. Substitui `trecho.py`/`%%>>>`,
  e os slides passam a sair daí.
- **Edição via sistema**: git + editor XML com validação pelo schema (VS Code + extensão XML,
  gratuito; ou FairCopy/Oxygen). Site publicado a cada commit. Um editor web próprio pode vir
  depois, sobre os mesmos arquivos.
- **Transcrição existente**: o capítulo I da Theodicea, hoje em `.tex` feito à mão, é convertido
  uma vez para TEI. Ele continua sendo o padrão-ouro do portão de qualidade da F6.

## Sequência de execução

1. F0 + F1 + F2 no vol. 2 inteiro (o scan está aqui; ~30 min de máquina).
2. ODD/schema do projeto e conversão do cap. I da Theodicea (`.tex` à mão) para TEI: fixa o
   formato e dá o padrão-ouro.
3. Piloto completo F3→F7 na Theodicea cap. I (pp. 421–442) com o portão de qualidade de F6;
   `tei2latex` compilando o capítulo pelo `compila.sh`.
4. F4 no vol. 2 → `estrutura.tsv` completo, revisado.
5. F5–F6 no vol. 2 inteiro (batch), depois F7.
6. Vol. 1 assim que o PDF estiver disponível (mesmo pipeline, `offset` 15, corte vertical).
7. Piloto da obra nova (um capítulo) para validar `copyOf`/`corresp`/`resp`, `procedencia.py` e
   a apresentação da procedência.
8. Atualizar `docs/` (nova nota `06-tei.md`; `docs/03`, `05` e `CLAUDE.md`, que hoje diz "não
   modernizar a grafia": continua valendo para a base, e a grafia atual sai na conversão).

## Decisões

Fechadas:
1. **Grafia**: AO 1990 (o mais recente), variante brasileira, referência VOLP/ABL.
2. **Estrutura**: `estrutura.tsv` é a fonte; corrigir uma divisão = mudar uma linha.
3. **Base "Sinibaldi 1916" em TEI XML** (decisão do usuário); LaTeX e HTML são saídas geradas.
4. **Obra nova separada, em XML**, ligada à base, com autor de cada trecho e referências às páginas
   originais.

Recomendadas (confirmar):
5. **Obra nova também em TEI**, restrito pela mesma ODD.
6. **Base em grafia de 1916**, com AO 1990 aplicado na saída; `<choice>` só nos casos ambíguos.
7. **Ids até o nível da frase** (`t6.p1.s1`), definitivos no congelamento.

Assumidas (trocar se discordar):
8. **Latim** intocado; tradução, se houver, em nota do editor.
9. **Modelo para F6** escolhido pelo portão de qualidade no piloto, não de antemão.

Em aberto:
10. **Vol. 1**: onde está o `vol1.pdf`?
