# Elementos pré-textuais (capa, rosto, aprovações, prefácio…)

Componente `pretextual` do site + revisão de formatação por LLM (Sonnet; Haiku opcional). Feito em 2026-11-14.

## O que existe nos scans

| Vol. | Páginas (id do arquivo → impressa) | Conteúdo |
|---|---|---|
| 1 | `f001` → -14 | capa/guarda sem texto impresso (só sujeira e furos) |
| 1 | `f002` → -13 | folha de rosto (carimbo da biblioteca e anotação a mão: não são do livro) |
| 1 | `f003` → -12 | Imprimatur (Subiaco, 1927) |
| 1 | `f004` → -11 | dedicatória «Sacratissimo Cordi Jesu» (`f005` → -10 em branco) |
| 1 | `f006`–`f011` → -9…-4 | prefácio «Aos benevolos leitores» (da IV edição), todo em itálico, com nota de rodapé de 3 páginas |
| 1 | `f012`–`f013` → -3, -2 | carta de Leão XIII (latim em cima, português embaixo) |
| 1 | `f014`–`f015` → -1, 0 | carta de Bento XV (idem) |
| 2 | `0002` | capa com etiqueta/código de barras da biblioteca: sem texto do livro |
| 2 | `0003`, `0004` | folha de rosto; Approbatio (Assisi, 1916) |
| 2 | `0005` (topo) | anterrosto «METAPHYSICA» (título das três partes); o resto da p. 5 é corpo |

**Capa e contracapa**: os dois scans não trazem capa nem contracapa impressas (o vol. 2 acaba no índice, p. 826). O tipo
`capa`/`contracapa` existe em `esquema.PRETEXTUAIS` — o modelo pode abri-lo (`<abre tipo="capa"/>`) se uma página futura
tiver texto de capa — mas nenhum nó é criado enquanto não há o que imprimir.

## Componente

- **Nó** de nível `pretextual` (`esquema.NIVEIS`): marco `<milestone unit="pretextual" xml:id="vN.pre-<tipo>[-k]"/>`
  + `<head>` com o título + blocos. Fica sem pai e sem filhos; a 1ª parte o fecha. Tipos de peça: `esquema.PRETEXTUAIS`
  (capa, contracapa, rosto, imprimatur, aprovacao, dedicatoria, prefacio, carta, outro).
- **Parágrafos tipados** (`<p type>`, `esquema.TIPOS_PARAGRAFO`): `titulo-obra` (ELEMENTOS / PHILOSOPHIA), `centro`
  (linha centrada: autor, volume, edição, imprenta), `enderecamento` («AO VENERAVEL IRMÃO / MANUEL BISPO DE COIMBRA»),
  `saudacao`, `data-local`, `fecho` (assinatura, à direita). Sem `type`: texto corrido da carta/prefácio.
- **Saídas**: leitura pública/editor/HTML baixado (CSS em `frontend/site.css`, `exportacao.py`), LaTeX
  (`\preTituloObra`, `\preCentro`, `\preEnderecamento`, `\preSaudacao`, `\preDataLocal`, `\preFecho` em `tex/preambulo.tex` e
  `tex/formatos/comum.tex`; o prefixo `pre` evita o `\enderecamento` do pacote de português). No LaTeX a folha de rosto,
  a dedicatória, a capa e a contracapa **não imprimem** o título do nó («FOLHA DE ROSTO» é só o nome no sumário), e as marcas
  `\pg{}` do vol. 1 saem em romano como no livro (`rotulo_pagina`: impressa = seq + 16; as cartas de Bento XV são XV–XVI).
- **Banco**: o bloco **não** guarda `<pb>` no começo (a página vem de `Bloco.pagina`; o exportador reinsere o `<pb>`).
  `<pb>` só no meio de parágrafo que atravessa a página e dentro de nota.

## Revisão por LLM (`tools/revisa_pretextuais.py`)

```bash
export SINIBALDI_DADOS=/caminho/do/checkout          # onde estão volN/paginas/*.png
python3 tools/revisa_pretextuais.py --vol vol1       # Sonnet (padrão); --modelo haiku para comparar
python3 tools/revisa_pretextuais.py --vol vol1 --so f009,f010 --refaz     # refaz páginas
python3 tools/revisa_pretextuais.py --vol vol1 --montar                   # só remonta o JSON
```

Uma chamada `claude -p` (sem ferramentas) por página, em ordem: duas metades da imagem + texto bruto do OCR + a peça
aberta + os blocos em aberto da página anterior (`tools/prompts/pretextuais.md`). O modelo devolve `<abre tipo titulo/>`
(onde começa cada peça), `<p type>` tipados, `continua="RÓTULO"` (parágrafo que atravessa a página; em carta bilíngue cada
língua continua o seu bloco) e `<nota-continua>` (nota de rodapé que vem da página anterior). Cada bloco passa por
`esquema.validar_fragmento`; recusado, há 2ª chamada com o motivo. O script desfaz `hi` repetido dentro de `hi`
(prefácio todo em itálico: `\emph` dentro de `\emph` viraria romano), junta palavra hifenizada no fim de página e
remonta as peças.

Saída versionada: `volN/pretextuais/paginas/<id>.json` (retoma de onde parou), `volN/pretextuais.json` (peças com
`blocos` e `pag_blocos`), e `volN/pretextuais.extra.json` — peças **curadas à mão** que o script junta ao fim (vol. 2: o
anterrosto `METAPHYSICA`, que o modelo não vê por estar na p. 5, de corpo).

Custo: ≈ US$ 0,91 (vol. 1, 15 páginas) + US$ 0,09 (vol. 2, 3 páginas) com Sonnet, ~4 min. Os modelos acertaram o
que o OCR errou («19106» → 1916, «Nohis» → Nobis, «MDCCCXOCII» → MDCCCXCIII), ignoraram carimbos e anotações, e
registraram as dúvidas em `notas` de cada `paginas/<id>.json`.

## Aplicar no site

```bash
cd web
.venv/bin/python manage.py migrate                         # 0010: novo valor de No.nivel
.venv/bin/python manage.py aplicar_pretextuais             # relata
.venv/bin/python manage.py aplicar_pretextuais --aplicar   # 1916 + atualizada + nova; idempotente
```

Substitui, em cada volume, os blocos do começo até o 1º marco que não é pretextual (e só até `ate` do JSON). Na 1916 e
nas derivadas; blocos editados à mão (`adaptado`/`novo`) numa derivada fazem o comando pular aquele volume; os blocos
novos das derivadas ficam `copia` ligados aos da 1916. Reconstrói a árvore (`pagina_ini/fim` dos nós vêm de `Bloco.pagina`).

## Limites conhecidos

- Ordinais sobrescritos («S.to», «Exc.mo») saem sem marcação: o dialeto só tem `it`/`bold`/`sc`.
- Folha de rosto do vol. 1: o impresso traz «1297» riscado e corrigido a mão para «1927»; o modelo pôs 1927.
- Cartas bilíngues ficam na ordem da página (latim, português, latim da p. seguinte…): as marcas de página alternam
  `[XIII] … [XIV] … [XIII] … [XIV]`, fiel ao livro.
- O rótulo de página do site (`Pagina.impressa`) ainda mostra -9, -8… no pré-textual do vol. 1; só o LaTeX usa romano.
- Na nova edição, os nós `pretextual` ficam no início (as reordenações de partes já mantinham o que está fora de parte antes).
