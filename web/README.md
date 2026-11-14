# Editor web de *Elementos de Philosophia* (Django MVT)

Aplicação Django (MVT) de edição colaborativa. Backend/fundação: modelos, dialeto de fragmento, conversões TEI, serviços de escrita,
importação/exportação. As telas ficam em `templates/`, `static/` e `frontend/`.

## Como rodar (máquina limpa)

Requisitos: Python 3.12+ (Django 5.2, lxml, Pillow). Node só para quem mexe no front.

```bash
cd web
python3 -m venv --system-site-packages .venv      # lxml vem do sistema; sem ele, o pip o instala
.venv/bin/pip install -r requirements.txt         # Django, lxml, Pillow
export SINIBALDI_DADOS=/caminho/do/checkout       # raiz com volN/paginas/*.png (só leitura); padrão: raiz do repo

.venv/bin/python manage.py migrate                # cria db.sqlite3 e o grupo "editores"
.venv/bin/python manage.py importar_tei           # edição "1916" (~5 s): [--volume 1 2] [--fonte corrigido] [--recriar]
.venv/bin/python manage.py derivar_edicao_atualizada  # edição "atualizada" [--recriar] [--oculta]
.venv/bin/python manage.py derivar_nova_edicao    # edição "nova" (nasce oculta) [--recriar]
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver              # http://127.0.0.1:8000/
```

`importar_tei` lê `volN/volN.corrigido.xml` (`--fonte estruturado` para o outro) em `SINIBALDI_DADOS` ou, se não achar, na raiz do repo; a ordem importar → derivar é obrigatória (a nova edição copia a de 1916).

**Dar acesso a um editor**: crie o usuário (`createsuperuser`, ou pelo admin em `/admin/` com um superusuário)
e ponha-o no grupo `editores` (admin › Usuários › Grupos, ou
`manage.py shell -c "from django.contrib.auth.models import User, Group; User.objects.get(username='ana').groups.add(Group.objects.get(name='editores'))"`).
O grupo (add/change/delete de `Bloco`) é criado pela migração `0002`; as telas de edição exigem login +
`obra.change_bloco`. Superusuários passam sem o grupo.

Variáveis de ambiente: `SINIBALDI_DADOS` (imagens e o PDF original do scan, para o fac-símile), `SINIBALDI_CACHE` (padrão `web/cache/`: PDFs gerados e
`scans/` com os JPEG reduzidos), `SECRET_KEY`, `DEBUG` (`0` desliga), `ALLOWED_HOSTS`.

Utilitários e testes:

```bash
.venv/bin/python manage.py preparar_downloads [--so fac-simile|pdf] [--edicao 1916] [--volume 1]  # PDFs dos volumes no cache
.venv/bin/python manage.py exportar_tei --edicao 1916 --volume 2 -o /tmp/vol2.xml   # [--forcar]
.venv/bin/python manage.py sincronizar_nova_edicao [--aplicar]                       # ver "Pendências"
.venv/bin/python manage.py aplicar_componentes [--aplicar] [--edicao 1916|nova]   # ver "Componentes"
.venv/bin/python manage.py aplicar_asteriscos [--aplicar] [--lista x.tsv]        # ver "Asterisco"
.venv/bin/python manage.py marcar_citacoes [--aplicar]                             # ver "Citações"
.venv/bin/python manage.py corrigir_texto "isto 6" "isto é" --palavra [--aplicar]  # troca de texto (nunca em tags); 1916 + cópias + adaptados; [--regex] [--autor u] [--comentario c]
.venv/bin/python manage.py test obra
```

### Componentes: sumário de capítulo e aparato do fim do volume

O OCR deixou o «Summario» de cada capítulo picotado em parágrafos (`SussAnt0: — dia, sua definição…`)
e transformou as linhas da *Synopse* e do *Indice das materias* do fim de cada volume em marcos e
títulos (capítulos/partes fantasmas no sumário principal). `aplicar_componentes` converte, nas duas
edições (1916 e depois nova; sem `--aplicar` só relata; idempotente):

- **sumário de capítulo** (`obra/sumarios.py`) → `<argument>` com um `<p>` por assunto (o rótulo
  «Summario:» e os travessões vêm do CSS/LaTeX); o título do capítulo que o OCR grudou vira `<head>`;
- **aparato final** (`obra/anexos.py`) → nó de nível `anexo` (`v1.synopse`, `v1.indice`…) com
  `<head>`; os marcos de dentro somem; as divisões citadas viram `<p type="anexo-titulo">` e as
  entradas do índice, `<p type="indice">`. O texto não muda.

Na nova, o aparato espalhado pela reordenação de partes é antes reunido no fim
(`servicos_nova.reunir_anexos`), blocos editados à mão são pulados, e os resultantes voltam a ser
`copia` ligados à 1916; `aplicar_ordem_partes` passou a manter os anexos no fim. Leva ~2 min (cada
gravação reconstrói a árvore).

### Componente asterisco (∗)

O ∗ de divisão de assunto do original (centrado, entre parágrafos ou no meio de uma nota) é o
componente semântico `<anchor type="asterisco"/>` (`obra/asteriscos.py`): inline, vale no corpo e
dentro de `<note>`; no site é o botão **∗** da barra do editor; no LaTeX, `\asterisco`
(`tools/tei2latex.py`). Para aplicar sem regerar nada: `aplicar_asteriscos` (sem `--aplicar` só relata,
idempotente) converte os `<p>*</p>` soltos e, com `--lista`, insere onde o PDF tem ∗ e o texto não. TSV
com cabeçalho `volume<TAB>pagina<TAB>depois_de<TAB>nota` (`pagina` = impressa; `depois_de` = trecho
único que antecede o ∗; `nota` = nº da nota, vazio = corpo). Aplica na 1916, atualiza as cópias da nova
(`atualizar_copias`) e repete a inserção nos blocos `adaptado` quando o trecho ainda existe — senão
avisa para inserir à mão.

### Componente gravura

Ilustração recortada do fac-símile, como bloco próprio (`Bloco.tipo = "gravura"`):
`<figure xml:id="v1.gravura-0034-ab12c"><graphic url="paginas/0034.png#xywh=x,y,l,a" width="60%"/><head>legenda</head><p>detalhes</p></figure>`.
A url é a imagem da página (relativa ao diretório do volume, como o `facs` do `<pb>`) + a caixa em pixels do
PNG original (fragmento de mídia W3C); `width` (opcional, 1–100 %) é a largura no texto; `<head>` (opcional) é a
legenda principal («FIGURA VIII. — Côrte vertical do cerebro humano.») e `<p>` (opcional, depois do `<head>`) os
detalhes impressos abaixo dela em corpo menor («A, hemispherio esquerdo; — B, …»); ambos só com
itálico/negrito/versalete/latim/rótulo. O `xml:id` é obrigatório e seu prefixo `vN.` diz o
volume (`obra/esquema.py`).

- **Marcar** (tela de revisão da 1916): botão **Gravura** na barra do scan → arraste uma caixa em volta da
  ilustração (Esc cancela; zoom e roda continuam valendo) → diálogo com a prévia do recorte, legenda e largura →
  **Inserir no texto**: o bloco entra antes do bloco do cursor (se o cursor está no início dele) ou depois. A
  legenda e os detalhes se editam no próprio editor, a largura no seletor da gravura. Grave como de costume.
- **Legenda a partir do texto seguinte** (o OCR costuma pôr a legenda como parágrafos logo depois da gravura):
  os botões **↥ Legenda** e **↥ Detalhes** da gravura trazem para ela a seleção (se houver texto selecionado depois
  dela) ou, sem seleção, o parágrafo seguinte inteiro — um por clique. O texto sai do lugar (parágrafos esvaziados
  somem; marcas de página e notas ficam), as marcas não aceitas na legenda caem e o hífen de fim de linha é
  desfeito («cere-» + «bello» → «cerebello»). **Enter** na legenda passa o que está depois do cursor para o início
  dos detalhes (para separar «FIGURA VIII. …» de «A, hemispherio …»); Enter nos detalhes abre parágrafo novo;
  Backspace no início dos detalhes volta à legenda e, no início da legenda, seleciona a gravura (o 2º remove).
- **Recorte**: `/gravura/<vol>/<arquivo>/<x,y,l,a>.png` (`obra:gravura`, público, cache longo; PNG em
  `SINIBALDI_CACHE/gravuras/`; caixa além da borda é aparada).
- **Saídas**: leitura pública e editor mostram o recorte; HTML para baixar embute a imagem (data URI); texto
  puro dá `[Gravura: legenda]` + os detalhes; TEI exporta o `<figure>`; LaTeX/PDF usam
  `\gravura[detalhes]{arquivo}{fração}{legenda}` (`tools/tei2latex.py`
  recorta do scan do volume para `SINIBALDI_CACHE/gravuras-tex/`).

Front-end (só para quem altera `frontend/` ou `templates/`; os bundles em `static/` já vêm commitados):

```bash
npm install
npm run build:editor    # TipTap: static/js/editor.bundle.js, revisao.js, nova.js, css do editor
npm run build           # Tailwind (static/css), depois de mexer em templates
```

### Rotas principais

| Rota | Nome (`obra:`) | O que é |
|---|---|---|
| `/`, `/edicao/<slug>/`, `…/<xml_id>/`, `…/busca/` | `inicio`, `edicao`, `no`, `busca` | Parte pública: sumário, leitura por nó, busca; `…/baixar/<formato>/` (`baixar`: xml, txt, html, tex, pdf; o PDF aceita `?notas=sem-notas\|1col\|2col\|corpo`, diagramação de `tex/formatos/`, sem ele A5 padrão; o menu «Baixar» é um painel Formato + Notas) |
| | | Com login + `obra.change_bloco`, a página do trecho mostra **Editar**: na nova edição leva a `nova_no` do nó; na 1916, a `revisar` da página onde o trecho começa |
| `/edicao/<slug>/<xml_id>/citar/` | `citar` | Citação ABNT (sem login) do trecho ou de uma passagem selecionada: chamada, referência, LaTeX; `formato=docx\|tex\|txt` baixa; ver "Citação ABNT" |
| `/edicao/<slug>/<xml_id>/baixar/fac-simile/` | `baixar_fac_simile` | Fac-símile do trecho: as páginas do scan original em PDF |
| `/edicao/<slug>/volume/<n>/baixar/xml/`, `…/pdf/` | `baixar_volume`, `baixar_volume_pdf` | Volume inteiro: TEI; PDF composto em LaTeX (em segundo plano) |
| `/fac-simile/<vol>/baixar/` | `baixar_fac_simile_volume` | Fac-símile do volume inteiro (o scan original, uma página do livro por página) |
| `/edicao/<slug>/<xml_id>/sugerir/` | `sugerir` | Formulário público (sem login) de sugestão de correção; POST grava `Sugestao` |
| `/edicao-colaborativa/sugestoes/` | `sugestoes` | Triagem das sugestões (login); `sugestoes/<pk>/acao/` (`sugestao_acao`, POST) |
| `/fac-simile/<vol>/<seq>/` | `facsimile` | Imagem da página (JPEG 1600 px, link p/ PNG original) |
| `/scan/<vol>/<seq>.png` | `scan` | PNG original da página (cache longo) |
| `/scan/<vol>/<seq>.jpg?l=1000\|1600` | `scan_jpg` | JPEG reduzido em cache (`SINIBALDI_CACHE/scans/`); as telas usam `l=1600` e oferecem link "original" |
| `/edicao/<slug>/<xml_id>/slides/` | `slides` | Slides do trecho (PDF embutido); `slides.pdf`, `slides.tex`, `slides.txt` (`slides_pdf`/`_tex`/`_txt`, `?baixar=1`) |
| `/edicao-colaborativa/slides/` | `slides_lista` | Apresentações salvas (login) |
| `/edicao-colaborativa/slides/<slug>/<xml_id>/` | `slides_editor` | Corrigir a fonte dos slides; POST em `salvar/`, `regenerar/`, `descartar/`, `restaurar/` |
| `/edicao-colaborativa/` | `painel` | Painel da área de revisão (login) |
| `/edicao-colaborativa/1916/vol/<n>/` | `paginas` | Páginas do volume |
| `/edicao-colaborativa/1916/vol/<n>/pag/<seq>/` | `revisar` | Scan + editor (`gravar/`, JSON) |
| `/edicao-colaborativa/converter/` | `converter` | html/xml ↔ blocos (JSON) |
| `/edicao-colaborativa/<slug>/` | `nova_estrutura` | Estrutura de uma edição derivada (`atualizada`, `nova`); na nova, também a ordem das partes |
| `/edicao-colaborativa/<slug>/no/<id>/` | `nova_no` | Editor paginado de um nó (`nova_trecho`, `nova_gravar`…) |
| `/edicao-colaborativa/<slug>/pendencias/` | `nova_pendencias` | Sincronização com a 1916 |
| `/edicao-colaborativa/<slug>/visibilidade/` | `visibilidade` | POST: mostra/esconde a edição na parte pública (`obra.change_edicao`) |
| `/entrar/`, `/admin/` | | Login e administração |

## As três edições

| slug | tipo | O que é |
|---|---|---|
| `1916` | `diplomatica` | **Rediagramação do texto de 1916/17**: o texto do livro, página a página, revisado contra o scan |
| `atualizada` | `atualizada` | **Edição atualizada**: derivada da 1916 na mesma ordem. Compõem-na (`Edicao.COMPONENTES_ATUALIZADA`, só descritivo por enquanto): rediagramação; atualização ortográfica e gramatical; atualização das referências e citações; revisão das gravuras; notas do editor |
| `nova` | `nova` | **Nova edição**: derivada e reorganizada (ordem das partes, mover, suprimir); **oculta** |

`atualizada` e `nova` são *derivadas* (`Edicao.derivada`): blocos com `origem` na 1916, procedência
copia/adaptado/novo, mesmas telas de edição e pendências (rotas com o slug). Só a nova tem
`Edicao.reorganiza` (as operações estruturais dão 404/`ErroOperacao` na atualizada).

**Esconder uma edição**: `Edicao.publica` (migração `0007` deixa a `nova` oculta). Oculta, ela some
do menu, do início e do "sobre", e as rotas públicas dela (leitura, busca, downloads, citar, sugerir,
slides) dão 404, exceto para quem tem `obra.change_bloco`, que a vê com o selo «oculta». Alternar:
painel (*Edições na parte pública*, exige `obra.change_edicao`, ou seja, superusuário) ou admin › Edições.

## Modelo

O documento é uma **sequência plana de `Bloco`** por `Edicao`, ordenada por `ordem` (BigInteger,
passo 1024). A hierarquia (`No`: parte > seccao > capitulo > artigo > tese) é derivada dos blocos
`marco` por `arvore.reconstruir`. Faixa de um nó: `ordem_ini <= ordem < ordem_fim` (fim exclusivo).
`Bloco.xml` é um fragmento do dialeto fechado de `obra/esquema.py`. Os `xml:id` ganham o prefixo
`v{volume}.` na importação (únicos na edição).

`Pagina.seq` é o `n` de `<pb>` (no vol. 1 coincide com a página impressa e é negativo nas
preliminares); `Pagina.arquivo` é o radical da imagem (`0034`, `f001`).

## Área de revisão (`/edicao-colaborativa/`, `views_edicao.py`)

Login + permissão `obra.change_bloco`. Rotas (namespace `obra`): `painel`, `paginas` (`1916/vol/<n>/`),
`revisar` (`1916/vol/<n>/pag/<seq>/`), `gravar` (`…/gravar/`, JSON), `converter` (`converter/`, JSON,
genérico), `historico`, `historico_bloco`. A tela de revisão tem scan à esquerda e o editor à direita
(abas Visual/XML). O texto das abas XML é `tei.blocos_para_texto_xml` / `texto_xml_para_blocos`
(`<?bloco id versao?>` + um bloco por parágrafo). O diff do histórico é `obra/diffs.py`.

O editor é TipTap 2 com esquema próprio (`frontend/editor/esquema.js` espelha o dialeto HTML de
`tei.py`); fonte em `frontend/editor/`, empacotado por `npm run build:editor` em
`static/js/editor.bundle.js` (+ `revisao.js`, `static/css/editor.css`), **commitados**: produção não
usa Node nem CDN. A API (`window.SinibaldiEditor.montar/montarAbas/…`) está no topo de
`frontend/editor/index.js`. Rode também `npm run build` (Tailwind) depois de mexer em templates.
(`npm run build:editor` também gera `static/js/nova.js`, o controlador das telas da nova edição.)

Proteção de estrutura no editor: marco (início de divisão) e `pb` nunca são substituídos por digitação ou
colagem (com o marco selecionado, o texto vai para um parágrafo novo depois dele); Backspace/Delete junto a
um marco primeiro o selecionam, e só com ele selecionado o removem. A seleção inicial é sempre um cursor de
texto no primeiro bloco textual, sem roubar o foco.

## Sugestões de leitores (`views_sugestoes.py`, `forms.py`, `servicos_sugestoes.py`, `static/js/sugestao.js`)

Qualquer leitor pode sugerir uma correção sem login: na página de um trecho, seleciona o texto e clica no botão
flutuante «Sugerir correção» (abre um `<dialog>` já preenchido com o bloco e o trecho), ou usa o link do cabeçalho
(página `sugerir/`, que funciona sem JavaScript). O envio é um POST comum e cria uma `Sugestao` pendente, com a
versão do bloco no momento do envio. O e-mail é opcional, visto só pelos editores e nunca publicado; **nenhum IP é
gravado**.

Anti-spam, sem dependências: CSRF; campo-isca `site` (preenchido: responde sucesso sem gravar); no máximo 10 envios
por hora por IP (`django.core.cache`, chave = SHA-256 do `REMOTE_ADDR`; estouro: formulário com erro e HTTP 429).
Em produção use um cache compartilhado entre processos (o padrão `locmem` conta por processo).
Atrás de um proxy reverso o `REMOTE_ADDR` é o do proxy: o limite passa a valer para todos os leitores juntos, a
menos que o proxy/servidor WSGI repasse o endereço real.

Os editores triam em `/edicao-colaborativa/sugestoes/` (filtros por estado e edição; aba com a contagem de
pendentes; cartão no painel). Ações: **Aplicar ao texto** (`servicos_sugestoes.aplicar`), **Aceitar** (já corrigido
à mão), **Rejeitar**, **Reabrir**, todas com nota opcional. *Aplicar* troca `trecho` por `sugestao` no XML do bloco
(espaços do trecho casam com qualquer espaço/quebra) e grava via `servicos.salvar_blocos` (nova versão, `Revisao`
do editor, `volume`/`pagina` do bloco intactos). Recusa, sem alterar nada, quando o trecho não é encontrado, aparece
mais de uma vez no bloco, atravessa elementos (itálico, nota, marca de página), o bloco sumiu ou houve conflito de
versão; nesses casos corrija à mão no editor e use *Aceitar*. A lista avisa quando o bloco mudou depois do envio.

## Notas de rodapé (`leitura.renderizar`, `static/js/site.js`, `frontend/site.css` › `.nota-pop`)

`renderizar` troca cada `<note>` por `<sup class="nref"><a href="#nota-N">` e devolve a lista que os
templates põem no fim (`notas-fim`). No navegador, clicar no número abre a nota num popup junto à
chamada (acompanha a rolagem; Esc, × ou clique fora fecham, e o foco volta ao número); o link «ir para
as notas» do popup, ou Ctrl/⌘/Shift-clique, mantém o salto para a lista. Vale em toda página que tenha
`sup.nref` e a `<li>` de destino (leitura, fac-símile, painel 1916 do editor da nova); sem JS, o link
continua saltando para o fim. Estilo no Tailwind (`npm run build` depois de mexer em `frontend/site.css`).
`base.html` carrega `site.css`/`site.js` com `{% static_v %}` (`obra/templatetags/estaticos.py`: `?v=<mtime>`),
para o navegador não ficar com a cópia antiga depois de um rebuild.

## Citação ABNT (`citacao.py`, `views_citacao.py`, `static/js/citacao*.js`)

Na leitura, o leitor seleciona uma passagem e clica em «Citar (ABNT)» (botão flutuante à esquerda do «Sugerir
correção»; o link do cabeçalho cita o trecho inteiro, sem JS). O JS manda por POST o trecho, a página impressa
inicial e final (última marca `[data-tei="pb"]` antes de cada ponta da seleção) e o bloco; a tela `citar/` mostra:

- **Citação direta** (NBR 10520, autor-data): até 300 caracteres vai entre aspas, no parágrafo (aspas internas
  viram simples); acima disso é *longa* — recuo de 4 cm, corpo 10, espaço simples, sem aspas, chamada ao fim.
  Chamada `(SINIBALDI, 1917, v. 1, p. 12-13)` e a forma «autor no texto».
- **Referência** (NBR 6023): `SINIBALDI, Thiago. **Elementos de philosophia**: <título do volume>. 5. ed. Roma: [s. n.], 1917.
  v. 1, p. 12. Disponível em: <URL do trecho>. Acesso em: <data>.` Na nova edição entra «Edição digital adaptada» no
  lugar do número da edição. Autor, local, editora e edição por volume são constantes no topo de `citacao.py`.
- **Word**: `.docx` gerado com `zipfile` (sem dependência) — A4, margens 3/2 cm, Times 12; citação longa e referência
  formatadas como pede a ABNT; botão «Copiar para o Word» cola HTML formatado.
- **LaTeX**: fragmento para `abntex2` + `abntex2cite` (`\begin{citacao}`/`\cite[v.~1, p.~12]{chave}`, `\citeonline`) e a
  entrada `@book` para o `.bib`; `.tex` para baixar. Conferido compilando com `abntex2.cls`.

Página fora do conjunto de páginas do volume é descartada (usa a do trecho); trecho acima de 5000 caracteres é recusado
com 400, nunca truncado. Nada é gravado no banco.

## Citações (`citacoes.py`, `servicos_citacoes.py`, `referencias.py`, `views_citacoes.py`, `frontend/editor/citacoes.js`)

Detalhes e medições em `docs/10-citacoes.md`. No dialeto, `<quote type="direta|indireta|mencao" xml:id>`
(continuação de citação interrompida: `corresp="#id"`) e `<bibl corresp>` (a referência que Sinibaldi deu); o
texto não tem aspas — o CSS/LaTeX desenha `«»`. Os dados ficam em `Citacao` (chave = `xml:id`, comum às duas
edições; indexada a cada `salvar_blocos`) e `Fonte` (entrada BibTeX).

- `manage.py marcar_citacoes [--aplicar] [--edicao 1916|nova] [--volume N] [--exemplos N] [--reindexar]`:
  reconhecimento pelas aspas; na nova, as cópias exatas herdam o xml marcado (mesmos ids).
- Editor: botões **«Cit»** (marcar/continuar/mudar tipo/desfazer), **(Ref.)**, **Ficha**, **Aspas→cit.**
  (`converter` com `{"detectar": true, "prefixo": "v2."}`); digitar `«…»` cria a citação.
- `/edicao-colaborativa/citacoes/` (`citacoes`, `citacoes_lote`, `citacao_editar`), `/edicao-colaborativa/fontes/`
  (`fontes`, `fonte_nova`, `fonte_editar`), `fontes.bib` (`fontes_bib`, `?usadas=1`).
- Saídas: na nova, leitura, `.txt`, `.tex`/PDF (`tei2latex.py --citacoes precisa`) trocam a referência de
  Sinibaldi pela precisa; o TEI exportado leva `<back><div type="citacoes">` com fontes e fichas.

## Edições derivadas: nova e atualizada (`/edicao-colaborativa/<slug>/`, `views_nova.py`, `servicos_nova.py`, `partes.py`)

O que segue vale para as duas, exceto o que mexe na estrutura (ordem das partes, mover, suprimir), que é só da nova.
`sincronizar_nova_edicao`, `aplicar_componentes` e `aplicar_asteriscos` tratam todas as derivadas (`--edicao` filtra).

Telas só para a edição `nova` (login + `obra.change_bloco`; nenhuma rota daqui altera blocos da 1916 e a
tela de revisão da 1916 não enxerga os da nova). Todas as operações são POST com CSRF e gravam `Revisao`
com o autor. Rotas (`obra:`): `nova_estrutura`, `nova_aplicar_ordem`, `nova_no` / `nova_trecho` (editor
paginado, 40 blocos por tela, `?p=`), `nova_no_acao` (subir/descer/suprimir/restaurar), `nova_mover`,
`nova_gravar`, `nova_bloco_acao` (restaurar texto de 1916, suprimir/restaurar bloco), `nova_pendencias`,
`nova_pendencias_acao`.

Fluxo de trabalho:

1. **Derivar**: `manage.py derivar_nova_edicao` (todos os blocos nascem `copia`, com `origem` na 1916).
2. **Criar as partes que faltam**: no vol. 1 o OCR não marcou *Lógica* nem *Ontologia*; elas estão juntas num
   trecho antes da Cosmologia. Em *Estrutura* abra o trecho/capítulo, vá à tela onde a parte começa, ponha o
   cursor no primeiro bloco dela, **Iniciar divisão › Parte** (`xml:id` sugerido `n.parte-ontologia`; a
   unicidade é verificada no servidor ao gravar) e insira o título logo depois. O painel *Ordem das partes*
   identifica as partes pelo título (sem acento/caixa) e diz o que falta.
3. **Aplicar a ordem-alvo** (Lógica › Cosmologia › Antropologia › Ontologia › Teodiceia › Moral): botão
   habilitado com as seis partes. Partes não identificadas ("Direito natural") seguem a anterior; vários
   segmentos da mesma parte mantêm a ordem original; blocos fora de qualquer parte ficam no início.
   Também dá para mover nós avulsos (↑ ↓, *mover…*) e suprimir/restaurar (marca `procedencia="suprimido"`;
   nada é apagado, a parte pública oculta).
4. **Adaptar**: o editor de trecho mostra à esquerda o *Texto de 1916* (bloco de origem destacado) e o *Scan*;
   gravar um bloco `copia` alterado o torna `adaptado`; bloco criado ali nasce `novo` (sem origem; herda
   `volume`/`pagina` do bloco imediatamente anterior, que são os do scan). *Restaurar o texto de 1916*
   volta ao xml da origem.
5. **Pendências** (`nova/pendencias/`, `manage.py sincronizar_nova_edicao [--aplicar]`): (a) cópias cujo xml
   difere da origem — atualizáveis em massa; (b) adaptados cuja origem mudou depois da adaptação
   (`Bloco.origem_versao_vista`; sem ele, compara `atualizado_em`) — o editor vê o diff e marca como visto;
   (c) blocos da 1916 (exceto cabeçalhos) sem correspondente na nova.

## Downloads em PDF (`exportacao.py`, `fac_simile.py`)

O menu **Baixar** de cada trecho (na página do trecho e em partes/secções/capítulos do sumário) oferece TEI, texto,
HTML, LaTeX, **PDF (LaTeX)** e **Fac-símile (PDF do scan)**; o topo do sumário oferece os mesmos formatos para o
**volume inteiro**, e a página de fac-símile linka o volume inteiro.

- **PDF (LaTeX)**: `tools/tei2latex.py --puro` sobre o TEI do banco (na própria requisição) e `latexmk -lualatex`
  em segundo plano (`exportacao.em_segundo_plano`: uma thread por arquivo e processo, que não toca o banco). A
  requisição espera até `ESPERA_PADRAO` (20 s); se não terminou, responde 202 com a página «Preparando…», que se
  recarrega a cada 15 s e baixa o arquivo quando fica pronto. Sem limite de tamanho: o tempo máximo de compilação
  é `tempo_limite_pdf` (120 s + 0,2 s por bloco; ~25 s medidos para 584 blocos). Cache em `SINIBALDI_CACHE`,
  chave = conteúdo dos blocos.
- **Fac-símile**: recortado do PDF original 2-up (`SINIBALDI_DADOS/volN/volN.pdf` ou `SINIBALDI_DADOS/volN.pdf`)
  sem recomprimir as imagens: `mutool poster -x 2` + `mutool merge` na ordem do `volN/paginas/manifesto.tsv`, uma
  vez por volume (`SINIBALDI_CACHE/fac-simile/vN-<assinatura>.pdf`, ~75 MB o vol. 1, ~200 MB o vol. 2; segundos),
  e daí um `mutool merge` com as páginas do trecho (as de início dos blocos + os `<pb>` dentro deles). Nas folhas
  com `/Rotate 90` (vol. 2) o poster entrega a metade direita primeiro; `fac_simile.preparar_volume` reordena.
  Sem o PDF original ou sem `mutool`, a opção some.
- `manage.py preparar_downloads` gera os volumes de antemão (o PDF LaTeX do vol. 1 leva alguns minutos).

## Slides (`slides.py`, `views_slides.py`)

O gerador é `tools/gera_slides.py` (TEI do nó → *fonte* `.slides.txt` → beamer → PDF). Qualquer nó de até
400 blocos tem slides: a página pública (`…/slides/`) só embute o PDF; quem compila é `slides.pdf`
(`latexmk`, cache em `SINIBALDI_CACHE`, chave = hash da fonte + do gerador + de `tex/slides/academia-slides.sty`,
semáforo compartilhado com o PDF do texto). Sem registro, os slides são os automáticos e nada vai ao banco.
Quem tem `obra.change_bloco` corrige a fonte em `…/edicao-colaborativa/slides/<slug>/<xml_id>/`: *Salvar e
recompilar* (valida com `validar`; `versao` dá controle otimista, conflito = 409 sem perder o texto), *Gerar de
novo a partir do texto*, *Descartar correções* e *Histórico*/restaurar (`ApresentacaoRevisao`, que sobrevive
a descartar). `Apresentacao` e o histórico se ligam por `(edicao, xml_id)`, não a `No` (cache recriado por
`arvore.reconstruir`). Se o texto do livro mudou desde a geração, o editor avisa e mostra o diff, sem
sobrescrever. Linha de comando: `manage.py gerar_slides --edicao 1916 --no v2.art-6 [-o x.pdf] [--fonte]`.
O CSS próprio está em `static/css/slides.css` (sem recompilar o Tailwind).
