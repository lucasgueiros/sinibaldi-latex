# Padrões-ouro

Texto transcrito à mão da imagem da página, usado **só como teste**: nada é aprendido dele
(`tools/lexico.py: TESTE` tira essas páginas do léxico). É contra ele que `tools/mede_wer.py`
(texto) e `tools/mede_formatacao.py` (itálico/versalete/negrito) medem qualquer mudança.

| volume | arquivo | págs. impressas | palavras (corpo / notas) |
|---|---|---|---|
| 2 (ed. 1916) | `vol2/02_parte_theodicea/01_cap_existencia-de-deus.tex` | 421–442 | 10 849 (2 140 / 8 709) |
| 1 (ed. 1927) | `vol1/ouro/062-065_logica_raciocinio.tex` | 62–65 | 1 680 (796 / 884) |
| 1 | `vol1/ouro/331-334_ontologia_ente-necessario.tex` | 331–334 | 2 139 (398 / 1 741) |
| 1 | `vol1/ouro/577-580_cosmologia_existencia-do-mundo.tex` | 577–580 | 1 672 (662 / 1 010) |

```bash
python3 tools/mede_wer.py                       # vol. 2
python3 tools/mede_wer.py --vol vol1 --lista 40 # vol. 1: cada bloco + "soma"
python3 tools/mede_wer.py --vol vol1 --corrige  # com tools/corrige_ocr.py antes
python3 tools/mede_formatacao.py --vol vol1 --erros 30
```

## Vol. 1: por que estes três blocos

Um bloco de 4 páginas em cada parte do volume, em vez de um trecho contínuo, porque o scan e a
composição variam ao longo do livro. Cada bloco cobre algo que o ouro do vol. 2 não tem:

- **62–65 (Lógica)**: fim de capítulo + abertura de capítulo (título, *Summario*, Artigo),
  `\textsc{Regra}`, syllogismos em linhas soltas e um exemplo em **duas colunas** (rubrica à
  esquerda, syllogismo à direita: o OCR intercala as colunas linha a linha), uma nota que o
  estruturador mete no meio de uma palavra hifenizada (`desconve-…niencia`).
- **331–334 (Ontologia)**: notas longas — a nota (1) da p. 331 ocupa o pé de três páginas e é
  o grosso do bloco; a p. 331 abre com o fim de uma nota da p. 330 (fica fora, pertence à
  chamada da p. 330); `\textbf{Deus}` nas notas; teses com enunciado em negrito e `a)`/`b)`.
- **577–580 (Cosmologia)**: portada de parte (*Metaphysica / Parte Segunda / Cosmologia /
  Prologo*), *Secção Primeira*, latim nas notas (Plínio; Rom. I, 19-20) e nomes próprios com
  `w` (*Newton*: a armadilha de `docs/04`).

## Convenções da transcrição (as mesmas do ouro do vol. 2)

- Ortographia e **erros do original** preservados e anotados no cabeçalho de cada arquivo
  (`seu elementos`, `pelo tres juizos`, `cum um só olhar`, `Este infinito`, `sería`,
  `causas supremus`, `Liepig`, `pelo sentidos`).
- Crase nesta edição é `á` (agudo); conferido com zoom — no corpo pequeno das notas o glifo
  parece grave, mas é o mesmo da `á` do corpo.
- `\pg{n}` só no corpo, na posição da quebra (palavra hifenizada fica inteira antes do `\pg`).
- Nota inteira no `\footnote` do ponto de chamada, **inclusive o que transborda** para a página
  seguinte (é o que o TEI faz: `<pb/>` dentro do `<note>`). Por isso o léxico exclui também a
  página seguinte a cada bloco (66, 335, 581).
- Cabeçalho corrente, número de página e assinatura (`Vol. I  38`) ficam de fora.
- Títulos de secção/capítulo em `\section*`/`\chapter*`/`\part*` (rótulo de formatação: romano,
  como no vol. 2), enunciado de tese em `\tese`/`\teseB` (negrito), rubricas `a)` em `\sub`
  (itálico) ou `\subp`.
- Não usar `tabular` nem argumentos opcionais que o `tex_limpo` não conheça: ele descarta
  `\begin{…}`/`\end{…}` e `\\[…]`, o resto do argumento viraria palavra.

Método: rascunho a partir de `vol1/paginas/NNNN.txt`, leitura da página inteira na imagem
(`vol1/paginas/NNNN.png`, 1754×2481) e zoom 2× nas palavras duvidosas recortando pela caixa
do `.tsv`. Depois `mede_wer.py --lista` lista cada divergência; todas foram reconferidas e as
restantes são erros do OCR/estruturador, não da transcrição.

## Medições (2026-11-11, TEI `vol1/vol1.estruturado.xml` versionado)

WER (palavras), sem → com `corrige_ocr`:

| bloco | total | corpo | notas |
|---|---|---|---|
| 62–65 | 16,5% → 13,5% | 14,2% → 11,6% | 14,1% → 10,5% |
| 331–334 | 8,7% → 5,9% | 8,5% → 7,0% | 8,7% → 5,6% |
| 577–580 | 37,4% → 35,1% | 45,5% → 42,2% | 32,0% → 30,3% |
| **soma vol. 1** | **19,8% → 17,1%** | 24,1% → 21,5% | 16,5% → 13,7% |
| vol. 2 (421–442) | 5,9% → 3,9% | 8,6% → 5,7% | 5,3% → 3,5% |

- A correção automática ajuda no vol. 1 (−2,7 pontos), confirmando a amostra de `docs/03`.
- O vol. 1 erra ~3× mais que o vol. 2 em leitura pura (bloco 331–334, sem erro de estrutura:
  8,7% contra 5,9%): `l`/`t`, `n`/`u`, `c`/`e`, `ã`→`à`, `o`→`0`.
- **Erro de estrutura domina 577–580**: a nota (1) da p. 580 (≈ 210 palavras) não foi
  reconhecida e ficou no corpo — inserção no corpo + omissão nas notas. Em 62–65, a nota da
  p. 62 foi parar dentro de `desconve-…niencia`.
- O título *Metaphysica* da portada e os números de tese sem `<label>` (`34`, `56`, `57`) também
  aparecem como divergência.

Formatação (`mede_formatacao.py --vol vol1`, 3 804 palavras rotuladas, acerto 92,8%): itálico
P 83% / R 80% (vol. 2: 98% / 97%); negrito **R 1,4%** — os enunciados de tese em negrito do
vol. 1 quase não são detectados; versalete só 2 ocorrências no ouro (`Regra`), sem medida útil.

## Medições depois da união dos branches (2026-11-11)

Branches `deus-versalete-fr`, `ouro-vol1` e `plano-titulos-trechos` unidos; cadeia inteira
(`tools/gera_volume.sh vol1|vol2`) refeita. WER sem → com `corrige_ocr`:

| | antes (tabela acima) | só a união | + melhorias abaixo |
|---|---|---|---|
| vol. 1, soma | 19,8% → 17,1% | 19,8% → 16,75% | **12,3% → 8,4%** |
| 62–65 | 16,5% → 13,5% | → 13,1% | 16,4% → 12,3% |
| 331–334 | 8,7% → 5,9% | → 5,6% | 8,6% → 4,9% |
| 577–580 | 37,4% → 35,1% | → 34,7% | 12,9% → **9,1%** |
| vol. 2 (421–442) | 5,9% → 3,9% | 5,9% → 3,41% | 5,9% → **3,26%** |

Melhorias (cada uma medida isoladamente no portão):

- `estruturar_tei`: o filete lido como traço (`- (1)`, `— (2)`, `-(1)`) impedia o início da
  nota: 7 notas do vol. 1 ficavam no corpo, entre elas a da p. 580 (vol. 1: 16,1% → 8,5%).
- `estruturar_tei`: palavra hifenizada na virada de página fica inteira antes do `<pb>` (corpo e
  notas; antes `desconve<pb/>niencia` imprimia `desconve [63] niencia`, e nas notas o hífen nem
  saía: `neces-<pb/>sario`); nota sem chamada não cai no meio da palavra.
- `corrige_ocr`: regras `crase` (vol. 1: −0,67 ponto) e `e-agudo` (vol. 2: os 15 `E'` do ouro;
  −0,15 ponto). Ver `docs/03`.
- Ouro do vol. 2: 3 hífens de fim de linha esquecidos na transcrição (`pre-`/`missas`,
  `imper-`/`feito`, `essen-`/`cial`) juntados; o total passou de 10 849 para 10 846 palavras.

Ficou de fora por não valer a pena: negrito do vol. 1. A espessura não o separa nesse scan
(`swr` mediana do negrito 1,14 contra p90 do romano 1,12; no vol. 2, 1,38 contra 1,09), então
mexer no limiar só troca revocação por falsos positivos. Erros que ainda restam no vol. 1 são
de leitura (`l`/`t`: `lambem`, `Lerceira`; `á` depois de `e`/`é`/`que`), coisa da F6.

## Mudanças nas ferramentas junto com este ouro

- `mede_wer.py`: `--vol vol1` lê os blocos de `vol1/ouro/<de>-<ate>_<nome>.tex`; o corte em
  "Summario" virou propriedade só do ouro do vol. 2; `tex_limpo` descarta o cabeçalho de
  compilação avulsa, `\csname fimavulso\endcsname`, `\begin/\end{…}` e `\\[…]` (antes viravam
  as palavras `tex avulso`, `center`, `3em`; o vol. 2 foi de 5,93% para 5,89% só por isso).
- `mede_formatacao.py`: `--vol`, mesma limpeza.
- `lexico.py`: `TESTE` aceita vários intervalos por volume.
