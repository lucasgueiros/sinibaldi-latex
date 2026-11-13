# Citações: componente, reconhecimento automático e referências precisas

Objetivo: cada citação que Sinibaldi faz (S. Tomás, Hegel, Büchner…) vira um objeto com dados
estruturados, para que a **nova edição** troque as referências vagas dele — «(Sum. Th., p. I, q. 84,
a. 7)», ou nenhuma — pelas de edições críticas e traduções recentes, e para gerar BibTeX.

## No texto (dialeto de `web/obra/esquema.py`)

```xml
<p>Hegel fala que <quote type="direta" xml:id="v2.cit-ab12cd">algo é assim</quote>, porém,
<quote type="direta" corresp="#v2.cit-ab12cd">e assado</quote> <bibl corresp="#v2.cit-ab12cd">(Phän., p. 3)</bibl>.</p>
```

- `type`: `direta` (entre aspas), `indireta` (paráfrase, sem aspas), `mencao` (termo entre aspas,
  sem fonte: «a palavra « racional »»; não tem ficha nem `xml:id`).
- **O texto guardado não tem aspas.** Quem renderiza desenha `«…»` (internas: `“…”`): CSS no site,
  `tei2latex.py` no PDF, `exportacao.py` no texto, `gera_slides.py` nos slides. Assim o uso de aspas
  é um só, qualquer que seja o que o OCR leu (`«»`, `“”`, `"`).
- Citação **interrompida** pelo autor: um `<quote>` por segmento; o 1º tem `xml:id`, os outros
  `corresp="#id"`. Cada segmento recebe as suas aspas.
- `<bibl corresp>`: a referência que o próprio Sinibaldi deu, ligada à citação.
- Não há citação dentro de citação (as internas são texto `“ ”`), salvo dentro de uma nota chamada
  de dentro da citação.

## Dados (`Citacao` e `Fonte`, em `web/obra/models.py`)

`Citacao` tem por chave o `xml:id` do 1º segmento, **comum às duas edições** (as cópias da nova
herdam os ids). A indexação (`servicos_citacoes.indexar_blocos`, chamada por todo
`servicos.salvar_blocos`) preenche `texto`, `referencia_autor`, `volume`/`pagina` (página do scan
onde o 1º segmento está, contando os `<pb>` no meio do parágrafo; a da 1916 prevalece) e `ativa`.
O editor preenche autor e obra citados, `lugar` (canônico: «I, q. 84, a. 7»), `fonte` + página,
`texto_fonte`, `traducao` + página, `texto_traducao` e nota. `Fonte` é uma entrada BibTeX
(`chave`, papel: edição crítica / tradução / antiga; `abreviatura` = rótulo curto no texto).

Referência precisa (`obra/referencias.py`):

    (Tomás de Aquino, *Summa theologiae*, I, q. 84, a. 7; ed. Leonina, p. 325; trad.: …, p. 12)

## Reconhecimento automático (`web/obra/citacoes.py`)

Pares de aspas no mesmo nível de elemento (parágrafo, nota, sumário, itálico): `«»`, `“”`, `„”`;
reta `"` alterna (abre/fecha) e não conta entre duas letras (`Exc"e Rev"º`); famílias trocadas pelo
OCR (`“…»`) fecham a aberta mais próxima. `(…)` logo depois (admite `.`/traço no meio) com cara de
referência — dígito, romano, `l.`, `q.`, `pag.`… ou título em itálico — vira `<bibl>`. Dois pares
separados por um trecho curto que começa por vírgula/travessão e não fecha a frase são uma citação
interrompida. Até 4 palavras sem referência: `mencao`.

Medido nos `volN.corrigido.xml` (nov/2026):

| | vol. 1 | vol. 2 |
|---|---|---|
| citações diretas | 630 | 451 |
| com a referência de Sinibaldi ligada (`<bibl>`) | 352 | 346 |
| continuações (citação interrompida) | 15 | 0 |
| menções | 88 | 4 |
| aspas sem par (ignoradas) | 1485 | 296 |
| fragmentos inválidos | 0 | 0 |

Em 1916 + nova (banco do site): 607 blocos na 1916, 599 cópias exatas atualizadas na nova,
1.118 fichas, todas com página. As aspas sem par do vol. 1 são quase todas `"` e `“` soltas do OCR.

```bash
cd web
.venv/bin/python manage.py marcar_citacoes                 # relata (1916, depois nova)
.venv/bin/python manage.py marcar_citacoes --aplicar       # grava (Revisao) e indexa; ~7 min; idempotente
.venv/bin/python manage.py marcar_citacoes --reindexar     # só refaz as fichas a partir do texto
```

Na 1916 todo parágrafo/sumário com aspas é examinado; as **cópias exatas** na nova recebem o xml
marcado da origem (mesmos ids, continuam `copia`); na nova só os `adaptado`/`novo` são examinados.

## No editor (web)

Barra de ferramentas (`frontend/editor/citacoes.js`):

- **«Cit»**: a seleção vira citação (direta, indireta, menção, ou *continuação* de uma citação da
  tela); as aspas das pontas da seleção são retiradas. No cursor de uma citação: muda o tipo (de
  todos os segmentos) ou desfaz a marca (devolve `« »` ao texto).
- **(Ref.)**: a seleção vira referência do autor, ligada a uma citação.
- **Ficha**: abre a ficha da citação sob o cursor.
- **Aspas→cit.**: o reconhecimento automático na tela inteira (no servidor, o mesmo de
  `marcar_citacoes`, via `converter` com `detectar`); desfazível.
- Digitar `«…»` ou `“…”`: ao fechar a aspa, o trecho vira citação.

## Telas (`/edicao-colaborativa/citacoes/`, `views_citacoes.py`)

Lista com filtros (estado, volume, com/sem referência de Sinibaldi, com/sem fonte, busca) e
**edição em lote** (autor, obra, fonte, tradução, estado). Ficha: o trecho em contexto nas duas
edições (links para o texto, o editor e o fac-símile), a página na edição de Sinibaldi com a
chamada ABNT e o BibTeX dela, os dados, a pré-visualização da referência precisa, `\autocite` e o
BibTeX das fontes; «Gravar e ir à próxima a conferir». Fontes: lista, formulário, `fontes.bib`.

## Saídas

| Saída | 1916 | nova |
|---|---|---|
| leitura no site | `«»` do CSS; referência de Sinibaldi; a precisa no `title` | `<bibl>` → referência precisa (a original no `title`); sem `<bibl>`, entra depois do último segmento |
| texto puro (`.txt`) | `«»` | idem + referência precisa |
| TEI | `<quote>`/`<bibl>` + `<back><div type="citacoes">`: `listBibl type="fontes"` (com o BibTeX) e `type="citacoes"` (um `<bibl corresp>` por citação: autor, título, `citedRange`, `ptr` para a fonte, `note type="referencia"`) | idem |
| LaTeX/PDF | `tei2latex.py` (padrão `--citacoes original`) | `--citacoes precisa` |

`tools/tei2latex.py --citacoes biblatex --bib fontes.bib` sai com `\autocite[325]{chave}` e grava o
`.bib` a partir do `<back>`. A chave de cache dos PDFs inclui a última alteração de fichas e fontes.

## Pendências

- Conferir as 1.118 fichas detectadas (estado «Detectada»): falsos pares do OCR em parágrafos com
  aspas soltas, e citações que abrem num itálico e fecham fora (contadas como «sem par»).
- Indiretas só existem marcadas à mão (não há aspas para reconhecer).
- Citação que continua em outro parágrafo (citação longa em vários `<p>`): marcar à mão como
  continuação (`corresp`); o detector só junta segmentos do mesmo parágrafo.
