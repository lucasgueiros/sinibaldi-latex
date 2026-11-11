# Títulos → `estrutura.tsv` → trechos (o TSV manda)

Parte de `plano.md`, fase F4. **v2 (2026-11-11)**: reescrita depois de `estruturar_tei.py`,
`formatacao.py` e `corrige_ocr.py` existirem. A v1 supunha começar do zero. Hoje a detecção de
títulos já existe, embutida no estruturador, e o que falta é **tirá-la de lá**, medi-la e
torná-la revisável. A segunda metade (§ Trechos) é nova: com a estrutura fixada, qualquer nó ou
faixa da obra vira um trecho (TEI, texto, LaTeX, PDF, scan, slides) com um só comando.

## Estado medido (2026-11-11, `volN.corrigido.xml`)

| | parte | secção | capítulo | artigo | tese |
|---|---|---|---|---|---|
| vol. 1 | 2 | 6 | 23 | 31 | 162 |
| vol. 2 | 7 | 9 | 30 | 73 | 231 |

Os números estão baixos: o vol. 2 tem dezenas de `Artigo I.` sem um capítulo antes. As
falhas, por classe e com exemplo, são o caderno de testes do script novo:

1. **Rótulo engolido como cabeçalho corrente.** Página de abertura de capítulo não tem cabeçalho,
   e a regra "1.ª linha = cabeçalho" come `CAPITULO SEGUNDO` (vol. 2 p. 32: o `ARTIGO I` e a tese 24
   aparecem, o capítulo não). É a causa da maior parte dos capítulos perdidos.
2. **Título em várias linhas** cortado na 1.ª (`Alma humana, sua existencia` / `e substancialidade.`).
3. **Título ausente ou lixo**: `Artigo IV.` sem título, `SECÇÃO PRIMEIRA / AA`, `Artigo V. / y`,
   `ANTHROPOL OGIA`, `Origem da alma Irunaaaana,.`.
4. **Cabeçalho corrente tomado por título**: `CAPITULO TERCEIRO / RACIOCINIO E ARGUMENTAÇÃO — 65`
   (vol. 1 pp. 65, 73), `CAPITULO II / FACULDADES … 477`. Duplicam o capítulo.
5. **Aparato final lido como corpo**: a *Synopse* e o *Indice das materias* (vol. 1 pp. 895–908;
   vol. 2 pp. ~818–827) geram 14 secções/capítulos/partes fantasmas no vol. 1.
6. **Numeral mal lido**: `Artigo 11.`, `Artigo |.`, `Artigo 1I.`, `SECÇÃO 11`, `CAPITULO I]`.
7. **ids sequenciais** (`cap-6`, `art-36`): acrescentar um capítulo perdido renumera todos os
   seguintes. Nenhum trecho pode se apoiar neles.

O que já existe e serve: o `.tsv` por página (caixas de linha e palavra), o `.fmt.tsv` com `rend`
(`bold`/`it`/`sc` por palavra, medido na imagem), `reconhece_titulo()` (vocabulário tolerante a
OCR), a conferência da sequência das teses (`resolve_numero`) e os cabeçalhos correntes já
isolados em `<fw>`. Estes são um sinal muito melhor do que a v1 supunha:

```
36  METAPHYSICA — PARTE TERCEIRA — ANTHROPOLOGIA       (par:   obra — parte — nome)
37  SECÇÃO I — CAPITULO II — ALMA HUMANA  37           (ímpar: secção — capítulo — nome)
```

Mesmo com OCR ruidoso (`CAPITULO l|`, `CAPITULO 1Í`), a **votação em janela** dá parte, secção e
capítulo de cada página.

## Princípio (mantido da v1)

1. `tools/titulos.py` **detecta** e **propõe** `volN/estrutura.proposta.tsv` + alertas.
2. Revisado e versionado, `volN/estrutura.tsv` é a **única fonte da estrutura**. `estruturar_tei.py`
   lê o TSV e não decide mais nada sobre títulos.
3. Corrigir = mudar uma linha do TSV e regenerar. Nunca editar título no `.tex`/XML.
4. Rodar `titulos.py` de novo **não sobrescreve** o revisado. Ele grava a proposta e um diff
   (`--diff`), e só se incorpora o que se quiser.

## Onde entra na cadeia

```
paginas/*.tsv + *.fmt.tsv ──► titulos.py ──► estrutura.proposta.tsv ──(revisão)──► estrutura.tsv
                                                                                   │
paginas/*.tsv + *.fmt.tsv + estrutura.tsv ──► estruturar_tei.py ──► corrige_ocr ──► tei2latex …
                                                                                   │
                                                  trecho.py (seletor → TEI/txt/tex/pdf/scan/slides)
```

Sem `estrutura.tsv`, `estruturar_tei.py` cai no comportamento atual (heurística embutida), e a
cadeia nunca quebra durante a transição. `gera_volume.sh` ganha a etapa `1b. titulos.py` só
para gerar a proposta e os alertas, sem tocar o TSV revisado.

## `tools/titulos.py`: detecção

### Candidatos por linha (relativo à página: margem e corpo pela moda)

Do `.tsv` (linha = `level 4`) e do `.fmt.tsv`:

- `centrada`: recuos esquerdo e direito iguais (±3 % da coluna) e largura < 90 % da coluna;
- `escala`: altura da linha / altura modal do corpo (`CAPITULO PRIMEIRO` ≈ 1,8; corpo = 1);
- `versal`: proporção de maiúsculas entre as letras;
- `rend`: fração das palavras `bold`/`sc` no `.fmt.tsv`. Isso dispensa a densidade de tinta da v1,
  porque `formatacao.py` já mede;
- `vocab`: `reconhece_titulo()` reaproveitado (movido para um módulo comum,
  `tools/estrutura_comum.py`, importado pelos dois scripts), ordinais por extenso, romanos
  tolerantes (`1I`, `|`, `l|`, `11` → I, II…), `SUMMARIO`, `PROLOGO`, `INTRODUCÇÃO`, `APPENDICE`;
- `vão`: espaço acima/abaixo em entrelinhas do corpo;
- `posição`: 1.ª linha da página? Isso **não** desclassifica mais. Ver a regra 1 abaixo.

### Regras (determinísticas, ajustadas no piloto)

1. **1.ª linha**: é cabeçalho corrente só se tiver a forma de cabeçalho (`eh_cabecalho_corrente`:
   número de página numa ponta, travessões, x_size pequeno). Uma linha centrada, de `escala` > 1,3,
   com `vocab` de rótulo, é **título**, mesmo na 1.ª posição. Isso corrige a classe 1.
2. **Bloco de título**: linhas consecutivas centradas, sem recuo francês e sem vão maior que 1,5
   entrelinha, formam um bloco só. Rótulo (`CAPITULO SEGUNDO`) + nome (`ALMA HUMANA`) ou rótulo
   (`ARTIGO I`) + título em 1–3 linhas. Corrige a classe 2.
3. **Sumário**: `SUMMARIO` em versalete até o primeiro parágrafo não-recuado-em-francês. Fica numa
   linha `sumario` própria.
4. **Tese**: `^\d+\.` na margem + `bold` até o 1.º `—`. A numeração sai da sequência já
   conferida (reaproveitar `resolve_numero`). A tese também vai para o TSV, porque é a âncora dos
   hiperlinks e dos trechos.
5. **Nível = vocabulário** (`parte > secção > capítulo > artigo > tese`). A escala só confirma.
   Sem vocabulário, um bloco centrado e versal logo após um rótulo é o nome do rótulo. Isolado, vira
   alerta `titulo-sem-rotulo`, sem gerar linha.
6. **Zonas excluídas**: a config do volume lista as faixas de aparato (`synopse`, `indice`,
   pré-textuais), e nelas o script não propõe divisão. Corrige a classe 5. A faixa é detectada
   pelo cabeçalho corrente (`SYNOPSE DA …`, `INDICE DAS MATERIAS`) e fixada na config.

### Conferências cruzadas (viram alertas, nunca alteram o TSV sozinhas)

- **Cabeçalho corrente por página.** Normalizar cada `<fw>` (par → parte; ímpar → secção, capítulo
  e nome) e votar numa janela de ±3 páginas. Daí saem três alertas:
  - `capitulo-esperado`: o cabeçalho muda de `CAPITULO I` para `CAPITULO II` entre as pp. *p* e
    *p+1*, e o TSV não tem capítulo ali. O alerta aponta o melhor candidato da página, que é a
    classe 1 e a principal fonte de recuperação;
  - `capitulo-fantasma`: o TSV abre um capítulo, e o cabeçalho continua igual dos dois lados
    (classe 4);
  - `nome-diverge`: o nome no TSV difere do nome votado no cabeçalho (distância de edição). A votação
    também **sugere a grafia** do título quando o OCR do título é lixo (classe 3), porque o
    cabeçalho repete o nome dezenas de vezes.
- **Sequência**: artigos I, II… recomeçam por capítulo; capítulos por secção ou parte; teses
  contínuas no volume. Um salto ou repetição gera `numero-fora-de-sequencia` com o valor esperado.
  Isso corrige a classe 6: o rótulo impresso no TSV é o **esperado**, e o lido vai para o alerta.
- **Índice impresso** (vol. 2 pp. ~823–827; vol. 1 pp. ~905–908). Um re-OCR cuidadoso dessas
  páginas (`ocr_paginado.py`, `--psm 4`) é parseado em linhas `Rótulo — Título … página`, e
  cada entrada é casada com uma linha do TSV por (nível, página ±1, distância de edição do título).
  Isso gera `indice-sem-titulo` (provável título perdido) e `titulo-fora-do-indice`.
  Fica num relatório à parte (`estrutura.indice.tsv`), porque o índice também tem erro de OCR.

Cada alerta: `pág  tipo  linha-do-TSV-ou-candidato  mensagem  sugestão`. A revisão anda pelos
alertas, não pelo volume.

## Formato do `estrutura.tsv`

Igual à v1, com duas mudanças: o `id` é **semântico**, e entra a coluna `fonte`.

```
# pág  âncora              nível     rótulo             título                                       id                         fonte
419    PROLOGO             prologo   Prologo            -                                            theodicea                  auto
421    5.                  tese      5                  Divisão da Theodicea.                        t5                         auto
421    CAPITULO PRIMEIRO   capitulo  Capitulo Primeiro  Existencia de Deus                           theodicea.existencia-de-deus  revisado
421    ARTIGO I.           artigo    Artigo I           Demonstrabilidade da existencia de Deus.     theodicea.existencia-de-deus.a1  revisado
421    6.                  tese      6                  A existencia de Deus póde ser demonstrada …  t6                         auto
```

- A página final é **derivada**: um nó vai até a página anterior ao próximo nó de nível igual
  ou superior. A página em que o próximo começa também pertence a ele quando a virada é no meio da
  página. Nos trechos, o corte exato é pela **âncora**, não pela página.
- `âncora` é o início do texto da linha na página, casado com tolerância (normalizado, distância de
  edição). Nunca número de linha, que muda a cada re-OCR.
- `id`: `parte.capitulo-slug[.aN]` a partir do título **revisado**, e `tN` para teses. Depois que
  a linha vira `revisado`, o id não muda mais, mesmo que o título seja corrigido. Isso corrige a
  classe 7. `estruturar_tei.py` copia esse id para `xml:id`.
- `fonte`: `auto` (proposta não conferida) ou `revisado`. `titulos.py --diff` nunca propõe mudar
  uma linha `revisado`, só alerta se a detecção discorda dela.
- Correções: título fantasma = apagar a linha. Título perdido = acrescentar `pág` + `âncora`.
  Nível errado = trocar `nível`.

## `estruturar_tei.py` passa a ler o TSV

- `--estrutura volN/estrutura.tsv`: para cada página, as linhas do TSV dessa página são casadas
  pela âncora com as linhas OCR. As casadas (e o bloco de título que elas iniciam) saem do fluxo
  do corpo e viram `<div type xml:id n>` + `<head type="rotulo">` + `<head>`, com o **texto do
  TSV** e não o do OCR.
- Âncora sem casamento vira o alerta `ancora-perdida` e não gera div. Linha do OCR com cara de título
  que o TSV não declara continua sendo corpo e gera `titulo-nao-declarado`.
- `Estrutura.par()` perde a heurística de títulos (fica a de teses, que alimenta o próprio TSV).
- O `estrutura.tsv` antigo (`caminho pág_ini pág_fim`, `docs/05`) deixa de existir como fonte e
  passa a ser **gerado** por `trecho.py --materializa`.

## Trechos: `tools/trecho.py` (reescrito)

Objetivo: trabalhar com **qualquer parte da obra** sem saber páginas nem caminhos, por um seletor.

### Seletor

| forma | exemplo | resolve para |
|---|---|---|
| id do TSV | `theodicea.existencia-de-deus` | o nó e os filhos |
| prefixo/busca | `existencia-de-deus`, `/alma humana/` | o único nó que casa; se houver vários, lista e para |
| tese | `t6`, `t6..t12` | a tese, ou da tese 6 até o fim da 12 |
| páginas | `421-442`, `p421` | faixa de páginas impressas, cortada na virada exata |
| combinado | `vol2:theodicea.existencia-de-deus.a2` | volume explícito (padrão: o único que casa) |

A resolução usa só o `estrutura.tsv`, que dá id → (volume, pág. inicial, âncora, pág. final
derivada). O conteúdo vem do `volN.corrigido.xml` **pelo `xml:id`**, que é exato, e pela
página só no modo `páginas`.

### Saídas (`--formato`, repetível; padrão `txt`)

- `tei`: o `<div>` recortado, com os `<pb>` e `<note>` dele, e um `teiHeader` mínimo que cita
  volume e páginas. É a entrada de tudo o mais;
- `txt`: texto corrido, notas no fim, `[421]` nas viradas. Serve para ler, para colar num prompt e
  para dar `diff`;
- `tex`: `tei2latex.py` sobre o fragmento (`--grafia original|atual` repassado);
- `pdf`: o `.tex` acima compilado com `tex/_preview.tex` (é o que `compila.sh`/`gera_volume.sh -f -l`
  fazem hoje por página, agora por nó);
- `scan`: as páginas do original (`paginas/<id>.png` via manifesto) num PDF com `mutool convert`,
  para conferir contra a imagem;
- `slides`: `gera_slides_base.py` alimentado pelo `.tex` do trecho. O modo `%%>>> id` do
  `trecho.py` atual fica como `--marcador` enquanto houver `.tex` manuais que o usem.

Destino: `build/trechos/<id>.<ext>` (git-ignored), ou `-o`, ou stdout para `txt`/`tei`.

### Outros modos

- `--lista [seletor]`: árvore com id, rótulo, título e páginas. É o sumário navegável e também a
  forma de conferir o TSV de relance;
- `--onde 'texto'`: busca no `corrigido.xml` e devolve o nó mais interno e a página de cada ocorrência
  (`t87 · vol1 p. 302 · ontologia.essencia-e-existencia`);
- `--materializa [nível]`: gera a árvore de pastas `volN/NN_slug/…` de `docs/05` a partir do TSV,
  no nível de corte configurado (padrão `capitulo`), com o `.tei`/`.txt`/`.tex` de cada nó. Substitui
  `corta.py --tsv`. O `corta.py` continua para faixas de PDF de OCR, se ainda for útil.

## Validação (portão)

Não existe padrão-ouro de estrutura. Ele é construído no próprio piloto:

1. **Piloto: vol. 2, Anthropologia (pp. 5–418)**, que concentra as classes 1–3. O TSV proposto é
   revisado à mão contra o cabeçalho corrente e o índice impresso, e vira o ouro de estrutura
   (`fonte=revisado`).
2. Métrica: precisão e revocação por nível (linha casada = mesmo nível, página ±0, rótulo igual),
   mais o acerto do título (distância de edição normalizada), calculados por `titulos.py --mede
   estrutura.tsv`. Metas antes de rodar o resto: **revocação ≥ 98 % em capítulo/artigo** e **zero
   fantasmas não alertados**. Uma falha que escapa sem alerta é pior que uma falha alertada.
3. Regressão: as pp. 421–442 (padrão-ouro de texto) mantêm o WER de `mede_wer.py`. A mudança na
   estrutura não pode alterar o texto do corpo.
4. Depois disso, o vol. 2 inteiro e então o vol. 1, cada um com a revisão dirigida pelos alertas.

## Andamento (2026-11-11)

Feito: `titulos.py` (etapas 2–3: candidatos, regras, votação do cabeçalho por execuções com
subsequência monótona por parte, teses por parte) e `trecho.py` novo (etapa 7, exceto `--materializa`),
documentados em `docs/07`. **Desvios do plano:** (a) em vez de extrair `estrutura_comum.py`
(etapa 1), `titulos.py` importa de `estruturar_tei.py`, para não arriscar o XML gerado; (b) a
numeração das teses recomeça em cada **parte**, e a de partes não é sequencial (Metaphysica 3, 4;
Ethica 1, 2): a v2 supunha teses contínuas no volume; (c) o recorte de `trecho.py` é por página, não
por âncora. Pendente: etapas 4 (índice), 5 (revisão do piloto), 6 (`estruturar_tei --estrutura`), 8–9.

## Etapas (cada uma um commit)

1. `tools/estrutura_comum.py`: extrair `reconhece_titulo`, `eh_cabecalho_corrente`, normalização e
   romanos tolerantes de `estruturar_tei.py`, sem mudar comportamento (o XML gerado fica byte a
   byte igual).
2. `titulos.py` v0: candidatos + regras 1–6 → `estrutura.proposta.tsv` + `alertas`. Rodar nos dois
   volumes e contar por classe contra a tabela acima.
3. Conferência pelo cabeçalho corrente (votação, `capitulo-esperado`/`fantasma`/`nome-diverge`).
4. Índice impresso: re-OCR das páginas do índice, parser e `estrutura.indice.tsv`.
5. Revisão do piloto (Anthropologia) → `vol2/estrutura.tsv` parcial, `--mede`, ajuste das regras.
6. `estruturar_tei.py --estrutura`: casamento por âncora, ids do TSV, alertas novos. `gera_volume.sh`
   passa o TSV quando ele existe. Conferir o WER das pp. 421–442.
7. `trecho.py` novo: seletor, `--lista`, formatos `tei`/`txt`/`tex`, depois `pdf`/`scan`/`slides`,
   `--onde` e `--materializa`.
8. Docs: `docs/05` (a árvore sai do TSV), `docs/03` (trechos por id; `%%>>>` legado), `CLAUDE.md`
   (lista de `tools/`), e uma nota nova `docs/07-estrutura-e-trechos.md` com as medições.
9. Revisão do resto do vol. 2, depois do vol. 1.

## Custo

Tudo determinístico, em segundos por volume. Só o re-OCR do índice leva alguns minutos. A única
etapa manual é a revisão do TSV: centenas de linhas por volume, a maioria teses que já chegam
certas pela sequência. A revisão segue os alertas e não exige ler o volume.

## Decisões

Assumidas (trocar se discordar):
- teses entram no `estrutura.tsv` (âncora de trecho e de hiperlink), não só as divisões;
- ids semânticos (`theodicea.existencia-de-deus.a1`) fixados na revisão, e `tN` para teses;
- nível de corte em arquivos = `capitulo`;
- trechos gerados em `build/trechos/`, fora do git; o que é versionado é o TSV.

Em aberto:
- **Sumário do capítulo** (`SUMMARIO: — … — …`): o plano o trata como conferência (cada item ≈ um
  artigo). Vale também usá-lo para **sugerir** títulos de artigo perdidos?
