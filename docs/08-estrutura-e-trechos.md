# 07 — Estrutura (títulos) e trechos

Desenho e medições em `.claude/plans/edicao-renovada/titulos-e-estrutura.md`. Aqui, o uso.

## `tools/titulos.py`: detectar títulos

```bash
python3 tools/titulos.py vol2                  # -> vol2/estrutura.proposta.tsv + vol2/estrutura.alertas.tsv
python3 tools/titulos.py vol2 -f 400 -l 450    # só uma faixa
python3 tools/titulos.py vol2 --mede --diff    # contra vol2/estrutura.tsv revisado (7 colunas)
```

Segundos por volume; lê `volN/paginas/<id>.tsv` e `<id>.fmt.tsv`. Cada linha da proposta:
`pág  âncora  nível  rótulo  título  id  fonte` (`parte`, `seccao`, `capitulo`, `artigo`, `tese`).

Como decide: rótulo (`PARTE`/`SECÇÃO`/`CAPITULO`/`ARTIGO` + ordinal, tolerante a OCR) em linha
**centrada**; o título é o bloco centrado seguinte; tese = `N. enunciado — texto`. Notas:

- uma linha de rótulo com travessão e texto (`CAPITULO IV — ATTRIBUTOS …`) é **cabeçalho corrente**,
  nunca título;
- a **numeração das teses recomeça em cada parte** (Anthropologia 1…, Theodicea 4…): as teses são
  resolvidas por parte, pela maior subsequência crescente, e um dígito mal lido é corrigido;
- os numerais de artigo/capítulo são conferidos em sequência (a de **parte** não: Metaphysica e
  Ethica numeram as suas);
- aparato final (*Synopse*, *Indice das materias*) fica fora.

Alertas (`estrutura.alertas.tsv`) são o roteiro da revisão: `capitulo-esperado` (o cabeçalho
corrente muda e o TSV não tem capítulo), `capitulo-fantasma`, `nome-diverge`, `sem-titulo`,
`numero-corrigido`, `artigo-pulado`, `tese-pulada`, `tese-descartada`, `id-repetido`.

Estado medido (2026-11-11, proposta sem revisão): vol. 2 = 4 partes, 6 secções, 24 capítulos, 73
artigos, 490 teses, 89 alertas; vol. 1 = 12 capítulos, 1 secção, 41 artigos, 183 teses, ~130
alertas. O vol. 1 está bem pior: faltam partes e secções (logo a contagem de capítulos/artigos por
pai fica errada) e o OCR do cabeçalho é pior.

**Revisão.** Copie a proposta para `volN/estrutura.tsv` (o formato antigo, `caminho pág_ini
pág_fim`, de `corta.py`, será substituído), corrija à mão seguindo os alertas e troque `auto` por
`revisado`. `titulos.py` nunca sobrescreve esse arquivo.

## `tools/trecho.py`: trabalhar com um trecho

```bash
python3 tools/trecho.py --lista vol2 [--teses]            # árvore (~ = ainda não revisado)
python3 tools/trecho.py vol2:existencia-de-deus           # texto no stdout (notas e [pág.] incluídas)
python3 tools/trecho.py vol2:theodicea/t5..t8 -F tex -F pdf
python3 tools/trecho.py vol2:421-442 -F tei -o x.xml
python3 tools/trecho.py vol2:421-442 -F scan              # PDF das imagens do scan (precisa dos PNG)
python3 tools/trecho.py vol2:t6 -F slides                 # .slides.base.md (matéria-prima p/ o LLM)
python3 tools/trecho.py --onde 'ente necessario' vol1     # em que nó, tese e página está
```

Seletor: id do nó (ou sufixo/prefixo), `/trecho do título/`, `ESCOPO/tN..tM`, `PP-QQ`. Se mais de um
nó casar, lista e para. Saídas em `build/trechos/` (git-ignored) quando há mais de um formato.

**Recorte por título.** Um nó começa no bloco do próprio título (casado pela `âncora` do TSV; se o
TEI não tem aquela linha, pelo texto do título) e termina **antes do título seguinte**, mesmo no
meio de uma página: um capítulo não traz as teses que o precedem, e `t6..t8` vai do início da 6 ao
início da 9. Só a faixa `PP-QQ` e o formato `scan` (imagens) cortam por página. A granularidade é o
bloco (parágrafo/`<head>`). Se o título seguinte não é localizado, avisa e corta no fim da página.
Título que o TEI atual perdeu (rótulo `CAPITULO …` de abertura) só começa a existir lá depois de
`estruturar_tei.py --estrutura`. O legado `%%>>>` continua em `trecho.py --marcador FONTE.tex ID`.

## Pendente (do plano)

- `estruturar_tei.py --estrutura`: ler o TSV revisado (ids estáveis, âncora) em vez da heurística
  própria. Até lá, os ids do TSV (`parte.capitulo.aN`) e os `xml:id` do TEI (`cap-6`) são
  independentes: `trecho.py` casa o título pela âncora/texto, não pelo `xml:id`.
- Índice impresso como conferência (`estrutura.indice.tsv`), `--materializa`, medição no ouro
  revisado (piloto: Anthropologia).
