# Plano — edição renovada do Sinibaldi (grafia atualizada, editável)

**Objetivo.** Uma edição nova dos *Elementos de Philosophia* (não um scan): texto em LaTeX,
**grafia atualizada**, editável para melhorias acadêmicas, com a **paginação original** marcada
(`\pg{n}` → `[n]`) e a estrutura do autor (partes, capítulos, artigos, teses numeradas, notas).

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
  estrutura.tsv                  # árvore de nós ← reconstruída do índice (F4)
  02_parte_theodicea/01_cap_….orig.tex   # transcrição FIEL (grafia de 1916), revisada
  02_parte_theodicea/01_cap_….tex        # edição RENOVADA (grafia atual) ← texto-mestre editável
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
- **notas de rodapé**: linhas com altura de letra menor, abaixo do corpo → separadas, numeradas
  `(1)`, `(2)`, e ligadas à chamada `(n)` do corpo;
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

### F4 — Reconstruir o índice e as divisões (`tools/indice.py`)
1. Re-OCR das páginas do índice (fim do volume) com mais cuidado (`--psm 4/6`, 400 ppi); parsear
   linhas `Capitulo II. — Título .......... 245` → árvore com página inicial.
2. **Validar em três fontes independentes**: o índice; a mudança do cabeçalho corrente página a
   página (F2); os títulos detectados no corpo (`CAPITULO`, `ARTIGO`, `SECÇÃO` centralizados,
   em versal). As páginas devem ser monotônicas e as três fontes devem concordar; divergência vira
   lista para revisão humana.
3. Gerar `estrutura.tsv` (formato atual de `docs/05`), revisado à mão — é pequeno (dezenas de
   linhas) e é a única etapa onde a decisão humana é estrutural.

### F5 — `tools/pagina2tex.py`: LaTeX mecânico por nó
Para cada nó do `estrutura.tsv`, concatena as páginas e gera `<stem>.ocr.tex` (bruto, git-ignored):
`\pg{n}` no ponto exato de cada virada (no meio da frase, se for o caso), `\footnote{}` na chamada,
`\tese`/`\teseB`/`\sub`, `\chapter*`/`\section*` dos títulos, latim em
`\foreignlanguage{latin}{…}` (o hOCR indica a língua de cada parágrafo/palavra; é o que depois
protege o latim da modernização). Mesmo guarda de fragmento avulso dos `.tex` atuais.

### F6 — Revisão LLM fiel (a etapa cara; por página, com a imagem)
Entrada por página: a **imagem** + o trecho de `<stem>.ocr.tex` dessa página + palavras de baixa
confiança. Pedido: corrigir para ficar **idêntico ao impresso, grafia de 1916**, marcando
itálico (`\emph`) e versalete — que o OCR não detecta e só a imagem mostra (o livro usa muito
itálico, por isso a imagem é necessária em todas as páginas). Saída: o trecho corrigido.

Salvaguardas automáticas, antes de aceitar: `\pg` intactos e em ordem; variação de nº de palavras
< ~3% (detecta omissão/alucinação); latim não "traduzido"; o fragmento compila. Página que falha
volta para fila de revisão humana.

**Ordem de grandeza** (conferir preço vigente antes de rodar): ~5 k tokens/página (imagem ≈1,5–2 k
+ texto de entrada ≈1,5 k + saída ≈1,5 k) → ≈4 M tokens por volume. Usar a Batch API (metade do
preço, sem pressa) e cache do prompt de instruções.

**Portão de qualidade antes do volume inteiro:** rodar F1–F6 nas pp. 421–442 e comparar com o
`.tex` feito à mão (taxa de erro por caractere, sem LaTeX): OCR cru vs. após F2/F3 vs. após F6.
Só escalar se F6 chegar perto do ouro; senão ajustar prompt/modelo e repetir no mesmo trecho.

Resultado: `<stem>.orig.tex` — a **transcrição diplomática**, versionada e congelada.

### F7 — Atualização ortográfica (por vocábulo, não por página)
A maior parte da modernização é **função da palavra**, não do contexto: `philosophia → filosofia`,
`immutavel → imutável`, `sciencia → ciência`, `acto → ato`, `elle → ele`, `d'este → deste`.
Então:
1. Do vocabulário de `*.orig.tex` (fora do latim e de nomes próprios), gerar candidatos por regra
   (`ph→f`, `th→t`, `y→i`, consoantes dobradas e mudas, acentuação do AO 1990) — `tools/moderniza.py`.
2. A LLM revisa **a lista de tipos uma vez** (dezenas de milhares de formas, não 1700 páginas) →
   `ortografia/mapa.tsv`, versionado e revisável por humano.
3. Aplicação determinística do mapa → `<stem>.tex`. Os casos que **dependem do contexto**
   (`póde` → `pode`/`pôde`, `E'` → `É`, `para`/`pára`, `a`/`á`/`à`, `está`/`esta`) ficam marcados
   no mapa como ambíguos e só esses trechos vão à LLM, com a frase em volta.
4. Latim, títulos de obras citadas e nomes próprios não são tocados (`\foreignlanguage{latin}`,
   lista de nomes como em `corrige_w`). Citações de autores em português antigo: decisão abaixo.

Resultado: `<stem>.tex` em grafia atual, **com os mesmos `\pg{n}`**, compilando em `livro.tex`.

### F8 — Edição acadêmica (contínua)
- O texto-mestre editável passa a ser `<stem>.tex` (moderno). `<stem>.orig.tex` fica congelado
  como referência fiel ao impresso (para citação, conferência e para refazer F7 se o mapa mudar).
- Separar autor de editor no LaTeX: notas do editor com macro própria (`\ned{…}`, numeração ou
  marca distinta das notas do autor), intervenções no texto marcáveis (`\add{}`, `\del{}` simples,
  ou `reledmac` se se quiser aparato crítico de verdade). Assim as melhorias acadêmicas nunca se
  confundem com o texto de Sinibaldi e a versão "sem intervenções" continua compilável.
- `livro.tex` com chave para compilar a edição renovada ou a diplomática.

## Sequência de execução

1. F0 + F1 + F2 no vol. 2 inteiro (o scan está aqui; ~30 min de máquina).
2. Piloto completo F3→F7 na Theodicea cap. I (pp. 421–442) com o portão de qualidade de F6.
3. F4 no vol. 2 → `estrutura.tsv` completo, revisado.
4. F5–F6 no vol. 2 inteiro (batch), depois F7.
5. Vol. 1 assim que o PDF estiver disponível (mesmo pipeline, `offset` 15, corte vertical).
6. Atualizar `docs/` (nova nota `06-edicao-renovada.md`; `docs/02`, `04`, `05` e `CLAUDE.md`, que
   hoje diz "não modernizar a grafia" — passa a valer só para `*.orig.tex`).

## Decisões (assumi o padrão entre parênteses; trocar se discordar)

1. **Norma da grafia atual** (AO 1990, variante brasileira: `ato`, `fato`, `ação`).
2. **Latim** (intocado na edição renovada; tradução, se houver, em nota do editor).
3. **Duas camadas** `orig`/moderna (sim — a diplomática é o que permite conferir e refazer a
   modernização; editar só a moderna).
4. **Modelo para F6** (decidir pelo portão de qualidade no piloto, não de antemão).
5. **Vol. 1**: onde está o `vol1.pdf`?
