# Correção automática antes da revisão LLM (F2/F3 → F6)

Avaliação de 2026-11-11. Parte de `plano.md`. Objetivo: entregar à F6 um TEI em que (a) as notas
já estão no lugar certo e (b) os erros mecânicos do OCR já sumiram. Assim a LLM corrige o resto
olhando a imagem e não tem que reestruturar a página. Diffs menores também deixam menos espaço para
ela modernizar a grafia ou inventar texto.

Protótipo e medição: `prototipo-correcao/` (`python3 .claude/plans/edicao-renovada/prototipo-correcao/mede_wer.py [--fix]`,
da raiz).

## 1. Notas no corpo: o caso da 1.ª nota do vol. 2 (pp. 5–6)

**Sintoma** (`vol2/vol2.estruturado.xml`): a nota (1) da p. 5, "Animal racional é a definição…",
ficou inteira no corpo como `t2.p2`…`t2.p6`. Na p. 6, a continuação dela ("definição — animal
racional — parece indicar…") também ficou no corpo. Só a nota (1) da p. 6 foi reconhecida.

**Causa medida** (geometria do `.tsv`):

O `inicio_notas()` combina vários critérios, mas todos ligados por **E** a dois que derivam só
da largura por caractere: `pequeno[i]` e a fração de linhas pequenas até o pé.

- **nota nova** = `(n)` E `pequeno[i]` E fração ≥ 0,8;
- **continuação** (só com `aberta`) = vão ≥ 1,3× a entrelinha do corpo E sem recuo E sem `(n)` E
  `pequeno[i]` E fração ≥ 0,85;
- a entrelinha de nota (~43 px) é calibrada, mas não entra por linha: só a do corpo é usada, no vão.

Medido na linha `(1)` da p. 5 (i = 12):

| critério | valor | resultado |
|---|---|---|
| `(n)` no início | sim | ✔ |
| vão antes | 159 px (corpo 53) | ✔ (não é exigido para nota nova) |
| entrelinha depois | 41–44 px até o pé | não usada |
| `pequeno[i]` | False (larguras/caractere 21,1 / 21,7 / **28,9** / 22,2; limiar 19,7; a maioria das linhas sem medida) | ✘ veta |
| fração pequena até o pé | 0,26 (mesma medida) | ✘ veta |

Resultado: corte em 39/39, sem notas. **Cascata:** na p. 6 a continuação (i = 13: vão 141,
`pequeno` = True, fração 1,00) satisfaz todos os critérios, e com `aberta=True` o código atual
corta certo em 13. Ela só se perde porque a p. 5 não deixou nota aberta.

### Correção proposta: escolher o ponto de corte por escore, não por veto

Os critérios atuais ficam. O que muda é a forma de combiná-los: trocar a conjunção, em que um
sinal frágil veta todos os outros, por uma soma ponderada, e acrescentar a entrelinha de nota,
que já é calibrada. Uma página tem no máximo uma fronteira corpo→notas. Avaliar **cada** corte
`k ∈ [1..n]`, mais "sem notas", e ficar com o de maior escore somado:

- `+` vão antes de `k` ≥ ~2× a entrelinha do corpo (o filete está ali);
- `+` mediana das entrelinhas em `k..n` próxima de 43 e distante de 53;
- `+` linha `k` com `(n)` recuado; ou, havendo nota aberta, linha `k` não recuada;
- `+/−` tamanho da letra **quando medido** (mediana da cauda), com peso menor. É um voto, não um veto;
- `+` filete na imagem (projeção horizontal da faixa do vão). É o único sinal que não depende do OCR.
  As PNGs são regeneráveis, mas só a faixa do vão precisa ser reamostrada;
- `−` cauda com linhas de corpo grande no meio (é escólio em corpo menor, não nota: "Pergunta-se /
  Resposta" fica no corpo).

**Restrição chamadas × notas como reparo, não só como alerta.** Se o corpo tem chamada `(n)` e o
corte vencedor é "sem notas", tomar o melhor corte que comece em `(n)`. A p. 5 passa só por isso.

**Nota aberta**: hoje é `nota_aberta and pag_anterior_com_notas`. Acrescentar: a página anterior
tem chamada sem nota correspondente (o caso da p. 5). Isso desfaz a cascata da p. 6 mesmo quando o
corte da página anterior falha.

**Teste de regressão:** pp. 5–6 (este caso) + pp. 421–442 (o padrão-ouro tem as notas no lugar),
e o número de alertas em `vol2.estruturado.alertas.tsv` (hoje 239). A meta é que só sobrem alertas
onde é preciso olhar a imagem.

Outros defeitos estruturais vistos nas mesmas páginas, para a mesma passada:
- **ruído de margem** dentro da coluna de leitura: `o —` em x0 = 1752 na p. 6 quebrou o parágrafo
  ("pois a Phy-" | "o — siologia"). Descartar linha curta com x0 além de ~80% da coluna;
- lixo de ornamento na p. 5 (`tel ole Sub`, `DA V. es`, `Ier V/A»`): descartar linhas de
  confiança média baixa acima do 1.º título;
- `<fw>` emitido no meio do parágrafo que atravessa a página (p. 6). Deve ir junto do `<pb>`.

## 2. Erros de palavra: medição no padrão-ouro (pp. 421–442)

WER do TEI estruturado contra o `.tex` feito à mão: **7,5%** (10 854 palavras: 494 trocas,
311 inserções, 14 omissões). Os erros são muito sistemáticos:

| classe | exemplos (ouro → OCR) | n |
|---|---|---|
| til/agudo/grave | `não→nào` (50), `á→à` (26), `são→sáo`, `noção→nocáo`, `suppõe→suppóe` | ~110 |
| DEUS em versalete | `Deus→Drus/Dzvs/Dxvs/Dzus/Dmus/Dgus` | ~60 |
| `c`↔`e`↔`o` | `causa→eausa`, `com→eom`, `intelligencia→intelligeneia` | ~40 |
| `h` itálico → `A` | `physica→pAysica`, `atheismo→atAeismo` | ~10 |
| `i` inicial em itálico | `immanentismo→ómmanentismo`, `intelligencia→tntelligencia` | ~10 |
| `é→6`, `á→4`, `c→0`, `l→1` | | ~10 |
| inserções estruturais | números de nota/página soltos, cabeçalho no fluxo, lixo de 1–3 caracteres | 29 trechos |

### Lição 1: o léxico do próprio OCR está contaminado

O F3 do plano supõe que "forma rara perto de forma frequente = erro". Isso falha nos erros
**sistemáticos**: nos dois volumes, `nào` ocorre 3 361 vezes (contra 10 232 `não`) e `à` ocorre
6 868 vezes, contra 1 356 `á`, embora o padrão-ouro não tenha nenhum `à`. Na 1.ª versão do
protótipo (limiar absoluto de frequência) o WER caiu só para 7,1%.

**Correção:** combinar três mecanismos, em ordem:

1. **Regras determinísticas de sequências impossíveis** na grafia de 1916: `-ào/-áo→-ão`,
   `-cáo→-ção`, `-óe(s|m)→-õe…`, `à→á`, `às→ás`, `À→A`, `6→é` isolado entre palavras,
   `D??s→Deus` (versalete; a marcação `sc` fica para a F6). São baratas, auditáveis e pegam o grosso.
2. **Léxico de frequência do corpus** (≈930 mil palavras, vol. 1 + vol. 2, **excluindo** a faixa
   de teste) + tabela de confusões genérica (`c/e/o`, acentos, `u/n`, `i/t/í`, `s/z`, `A→h`).
   Trocar quando o candidato é ≥ 10× mais frequente que a forma lida. Palavras curtas e frequentes
   ficam protegidas; as longas não, porque nelas pares mínimos legítimos são raros (é isso que pega
   `intelligeneia`, 9 casos).
3. **Não corrigir e marcar**: palavra de confiança < 60 no `.tsv`, sem candidato. Vai para a F6
   como dica.

**Resultado do protótipo: 7,5% → 5,5%** (257 erros corrigidos, 42 introduzidos).

### Lição 2: as regressões são palavras válidas raras

`medo→modo` (9), `era→ora`, `entra→outra`, `Mestra→Mostra`, `ideal→dia`, francês (`L'idée→L'ideo`).
Faltam duas coisas:
- **dicionário de palavras válidas** independente do OCR. O sistema só tem hunspell en/fr, que já
  protegeria o francês. Proposta: hunspell `pt_PT` (LibreOffice). Ele não reconhece `philosophia`,
  mas essas formas são frequentes no corpus e já ficam protegidas; o que ele protege são os
  `medo/era/entra`. Regra: **nunca trocar uma forma que está no dicionário** (pt, fr, lat);
- não aplicar a correção dentro de `xml:lang="la"`/`fr` (latim e francês têm léxico próprio; o `w→u`
  do `corrige_w.py` continua valendo).

### O que fica deliberadamente para a LLM (F6)

São casos contextuais em que regra local erra: `a` vs `á` (o `à→á` acerta 26 e erra 11), `E` vs
`E'` (15), `e/o` isolados, dígitos (`3↔8`), versalete e itálico (só a imagem mostra). Em vez de
adivinhar, o corretor registra cada troca.

## 3. Forma de implementar

- `tools/corrige_ocr.py`: roda **sobre os nós de texto do TEI estruturado**, depois de
  `estruturar_tei.py`, e grava `volN/correcoes.tsv` (`página, xml:id, antes, depois, regra`). A
  correção fica separada da estruturação, então cada troca é auditável e reversível por regra. A F6
  recebe a lista da página e as palavras de baixa confiança.
- Dehifenização com léxico: hoje `chamam-\nse` vira `chamamse` e `redu- Zir-se` não se junta.
  Juntar só se o resultado está no léxico. Se a 2.ª parte é clítico (`se`, `o`, `a`, `lhe`,
  `nos`…), manter o hífen.
- Portão: `mede_wer.py` nas pp. 421–442 a cada regra nova; **nenhuma regra entra se piora o WER**.
  As confusões da tabela não são aprendidas do padrão-ouro: ele é só teste. Para não ajustar demais
  a um capítulo, convém transcrever à mão um 2.º trecho curto (5 páginas do vol. 1, de outro
  compositor/ano) como 2.º teste.

## 4. Alternativas descartadas por ora

- **Re-OCR em conjunto** (outra binarização/escala, votação estilo ROVER): ≈25 min/volume por
  variante e ganho incerto. Os erros dominantes são de diacrítico e itálico, que se repetem entre
  variantes. Só vale reavaliar se a WER depois das regras ainda for alta em latim.
- **LLM sem imagem para limpar o texto**: ela "corrige" a grafia de 1916 e não resolve `a/á` sem
  ver a página. A F6 com imagem já está no plano.

## Ordem sugerida

1. Corte por escore + reparo por chamadas + "nota aberta" (§1); regressão pp. 5–6, 421–442 e
   contagem de alertas.
2. Ruído de margem/ornamento e `<fw>` no lugar.
3. `tools/corrige_ocr.py` (regras → léxico → marcação) com `correcoes.tsv`; portão de WER.
4. Hunspell `pt_PT` + proteção por idioma; dehifenização com léxico.
5. Só então: piloto da F6 nas pp. 421–442 sobre o texto corrigido (comparar com a F6 sobre o
   texto cru: o ganho da correção automática é medido também em custo/erros da LLM).
