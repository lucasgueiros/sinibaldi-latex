# TEI: a edição "Sinibaldi 1916" e a obra nova

Parte de `plano.md` (F5–F8). Decisão do usuário (2026-11-10): **a edição-base é reconstruída em
TEI XML**, por ser mais estável que LaTeX, por guardar as melhorias feitas, facilitar a extração
de trechos e a relação com a obra nova. A obra nova fica em XML separado, ligada à base.

## Recomendação: a obra nova também em TEI

O usuário deixou isso em aberto ("não precisa ser TEI"). Recomendo TEI porque tudo o que a obra
nova exige já existe nele como mecanismo padrão. Um XML próprio teria de reinventar cada item,
com schema, validação e conversores próprios:

| requisito | mecanismo TEI |
|---|---|
| autor de cada trecho | `@resp` → `<respStmt>`/`<person>`; Sinibaldi é `#sinibaldi` |
| trecho de Sinibaldi sem cópia | `@copyOf="sin:t6"` (o elemento é uma cópia daquele) |
| trecho adaptado de Sinibaldi | `@corresp="sin:t7 sin:t7.p2"` + `@resp` |
| referência à página original | calculada: a base tem `<pb n="421"/>`, então todo id tem página |
| quando / por quê | `@change="#c12"` → `<change when who>motivo</change>` |
| citações novas, referências | `<cit><quote/><bibl/></cit>`, `<listBibl>`, `<ptr target>` |
| notas de rodapé | `<note place="foot">`, as de Sinibaldi por `copyOf`, as novas com `@resp` |
| capítulos acrescentados / substituídos | `<div type="capitulo">` novo, ou com `@corresp` ao que substitui |
| remover sem perder rastro | marco de supressão (ver abaixo) |
| ligar dois arquivos | `<prefixDef ident="sin">` → `sinibaldi1916.xml#…` |

A mesma cadeia de ferramentas (validação, `tei2latex`, `tei2html`) atende as duas obras.

**TEI restrito.** O TEI completo tem cerca de 600 elementos. Uma **personalização ODD** do projeto
restringe a algumas dezenas e acrescenta as regras próprias, como "todo trecho não-Sinibaldi tem
`@resp`". Quem edita não se perde, e os conversores só precisam tratar esse subconjunto.

## 1. A base: `sinibaldi1916/`

Um arquivo por volume, que inclui um arquivo por capítulo via XInclude. Os ids são **estáveis
para sempre** depois que a base é congelada.

```xml
<div type="capitulo" xml:id="cap-existencia-de-deus" n="I">
  <head type="rotulo">Capitulo Primeiro</head><head>Existencia de Deus</head>
  <argument xml:id="cap-existencia-de-deus.sum"><p>Demonstrabilidade da existencia de Deus. — …</p></argument>
  <div type="artigo" xml:id="art-demonstrabilidade" n="I">
    <head type="rotulo">Artigo I.</head><head>Demonstrabilidade da existencia de Deus.</head>
    <div type="tese" xml:id="t6" n="6">
      <p xml:id="t6.p1"><label>6.</label> <hi rend="bold">A existencia de Deus póde ser demonstrada
        pela razão humana.</hi> — <s xml:id="t6.p1.s1">A razão humana póde deduzir da existencia
        dos effeitos a existencia da causa.</s> <s xml:id="t6.p1.s2">Ora todos os seres sensiveis
        são effeitos.</s> … que é <hi rend="sc">Deus</hi><note place="foot" n="2" xml:id="n421-2">
        Os systemas, que contestam a nossa proposição são — o <hi rend="it">tradicionalismo</hi>, …
        <pb n="422" facs="paginas/0422.png"/>revelação ou pela <hi rend="it">tradição</hi>, …
        <quote xml:lang="la">…</quote></note></s></p>
    </div>
  </div>
</div>
```

- **Ids**: divisões (`cap-…`, `art-…`), teses (`t6`), parágrafos (`t6.p1`), **frases** (`t6.p1.s1`)
  e notas (`n421-2`). São gerados por script no congelamento. As frases dão a granularidade fina
  para a obra nova citar meio parágrafo sem copiar.
- `<pb n facs>` em cada virada, no corpo e **dentro das notas**. Daí sai a página de qualquer
  trecho, inclusive de uma nota que atravessa páginas.
- `xml:lang="la"` no latim, `<hi rend>` para itálico e versalete, como no impresso.
- **Grafia**: o texto da base fica em **grafia de 1916** (o nome da edição é literal). A grafia
  AO 1990 é uma **transformação na saída**: `ortografia/mapa.tsv` (tipo → forma atual, revisado),
  aplicado por `tei2latex`/`tei2html`. Só os casos que dependem do contexto (`póde` → pode/pôde,
  `E'` → É) ficam no texto como `<choice><orig>póde</orig><reg>pode</reg></choice>`. Isso evita
  envolver ~um quinto das palavras em `<choice>`, o que tornaria o XML ilegível. O resultado é o
  mesmo, com uma só fonte para as duas grafias.
- **Melhorias na própria base** (erro tipográfico do original, citação errada de S. Tomás):
  `<choice><sic>…</sic><corr resp="#lucas" change="#c3">…</corr></choice>`, notas do editor
  `<note type="editorial" resp="#lucas">`. O texto de Sinibaldi nunca é sobrescrito.

## 2. A obra nova: `obra-nova/`

```xml
<teiHeader> …
  <listPrefixDef><prefixDef ident="sin" matchPattern="(.+)"
    replacementPattern="../sinibaldi1916/vol2.xml#$1"/></listPrefixDef>
  <revisionDesc><listChange>
    <change xml:id="c12" who="#lucas" when="2027-03-01">Atualiza a cosmologia: idade do universo.</change>
    <change xml:id="c13" who="#lucas" when="2027-03-01">Argumento do éter abandonado pela física.</change>
  </listChange></revisionDesc>
</teiHeader>

<div type="capitulo" xml:id="nc-deus" corresp="sin:cap-existencia-de-deus">
  <div copyOf="sin:t6"/>                                   <!-- tese 6 inteira, de Sinibaldi -->

  <p resp="#lucas" change="#c12" corresp="sin:t7.p1 sin:t7.p2">   <!-- adaptado -->
    <seg copyOf="sin:t7.p1.s1"/> Hoje, porém, … <bibl><ptr target="#bib-hawking1988"/>, p. 12</bibl>
  </p>

  <div type="secao" resp="#lucas" change="#c14">            <!-- seção nova -->
    <head>A objeção de …</head>
    <cit><quote>…</quote><bibl><ptr target="#bib-x"/></bibl></cit>
    <p>…<note place="foot" resp="#lucas">nota nova</note></p>
  </div>

  <note copyOf="sin:n421-2"/>                              <!-- nota de Sinibaldi, mantida -->
  <milestone unit="supressao" corresp="sin:t9" resp="#lucas" change="#c13"/>   <!-- removido -->
</div>
<back><listBibl><bibl xml:id="bib-hawking1988">…</bibl></listBibl></back>
```

Regras do projeto, verificadas por `tools/procedencia.py` (e por Schematron na ODD):

- **Autoria**: o que tem `copyOf` é de Sinibaldi, com referência e página calculadas. Todo
  elemento de texto **sem** `copyOf` precisa de `@resp`, herdado do ancestral mais próximo.
  Nenhum trecho fica sem autor.
- **Reordenar** = mudar a ordem dos elementos. As referências vão por id, então nada se perde.
- **Substituir um capítulo**: `<div corresp="sin:cap-x" resp change>` com o conteúdo novo.
  **Remover**: `<milestone unit="supressao">` no lugar, que não aparece no texto mas conta na
  cobertura. **Acrescentar**: `<div resp>` sem `corresp`.
- **Cobertura**: todo id de tese/nota da base aparece na obra nova como cópia, correspondência
  (adaptado/substituído) ou supressão. Id órfão = alerta. Nada de Sinibaldi some em silêncio.
- **Base mudou depois da adaptação**: se um id em `corresp` tem `<change>` na base posterior ao
  `change` do trecho adaptado, ele é sinalizado para revisão.
- **Relatórios**: tabela de correspondência base ↔ obra nova (com páginas de 1916), diff de cada
  trecho adaptado contra a origem, registro de mudanças por autor/data/capítulo.

## Saídas

- `tools/tei2latex.py` → `.tex` com o preâmbulo atual (`\pg`, `\tese`, notas) → PDF via
  `latexmk -lualatex`. Na obra nova, a procedência fica visível e comutável: sigla na margem
  (`S. 421` cópia, `S.* 422` adaptado, `Rev.` novo).
- `tools/tei2html.py` → site: `[421]` abre a imagem do scan, um trecho adaptado mostra o original
  ao lado, notas em popup, grafia 1916 ↔ atual comutável.
- **Extração de trechos**: qualquer id (`t6.p1.s2`) → texto + página + capítulo, por script. Isso
  substitui `trecho.py`/`%%>>>`, e os slides passam a sair daí.
- Ambos em Python + `lxml`, já instalado. Validação RelaxNG também via `lxml`. O schema vem da
  ODD do projeto, compilada uma vez (TEIGarage/Roma) e versionada.

## Edição no dia a dia

Editor XML com validação pelo schema: VS Code + extensão XML (Red Hat), gratuito, com
autocompletar a partir do `.rng`; ou FairCopy/Oxygen. `@resp`/`@change` podem ser preenchidos por
snippet ou por um script `novo-change` que cria o `<change>` com data e autor e devolve o id.
