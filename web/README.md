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
.venv/bin/python manage.py derivar_nova_edicao    # edição "nova" [--recriar]
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver              # http://127.0.0.1:8000/
```

`importar_tei` lê `volN/volN.corrigido.xml` (`--fonte estruturado` para o outro) em `SINIBALDI_DADOS` ou, se não achar, na raiz do repo; a ordem importar → derivar é obrigatória (a nova edição copia a de 1916).

**Dar acesso a um editor**: crie o usuário (`createsuperuser`, ou pelo admin em `/admin/` com um superusuário)
e ponha-o no grupo `editores` (admin › Usuários › Grupos, ou
`manage.py shell -c "from django.contrib.auth.models import User, Group; User.objects.get(username='ana').groups.add(Group.objects.get(name='editores'))"`).
O grupo (add/change/delete de `Bloco`) é criado pela migração `0002`; as telas de edição exigem login +
`obra.change_bloco`. Superusuários passam sem o grupo.

Variáveis de ambiente: `SINIBALDI_DADOS` (imagens), `SINIBALDI_CACHE` (padrão `web/cache/`: PDFs gerados e
`scans/` com os JPEG reduzidos), `SECRET_KEY`, `DEBUG` (`0` desliga), `ALLOWED_HOSTS`.

Utilitários e testes:

```bash
.venv/bin/python manage.py exportar_tei --edicao 1916 --volume 2 -o /tmp/vol2.xml   # [--forcar]
.venv/bin/python manage.py sincronizar_nova_edicao [--aplicar]                       # ver "Pendências"
.venv/bin/python manage.py test obra
```

Front-end (só para quem altera `frontend/` ou `templates/`; os bundles em `static/` já vêm commitados):

```bash
npm install
npm run build:editor    # TipTap: static/js/editor.bundle.js, revisao.js, nova.js, css do editor
npm run build           # Tailwind (static/css), depois de mexer em templates
```

### Rotas principais

| Rota | Nome (`obra:`) | O que é |
|---|---|---|
| `/`, `/edicao/<slug>/`, `…/<xml_id>/`, `…/busca/` | `inicio`, `edicao`, `no`, `busca` | Parte pública: sumário, leitura por nó, busca; `…/baixar/<formato>/` (`baixar`) |
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
| `/edicao-colaborativa/nova/` | `nova_estrutura` | Estrutura e ordem das partes da nova edição |
| `/edicao-colaborativa/nova/no/<id>/` | `nova_no` | Editor paginado de um nó (`nova_trecho`, `nova_gravar`…) |
| `/edicao-colaborativa/nova/pendencias/` | `nova_pendencias` | Sincronização com a 1916 |
| `/entrar/`, `/admin/` | | Login e administração |

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

## Nova edição (`/edicao-colaborativa/nova/`, `views_nova.py`, `servicos_nova.py`, `partes.py`)

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
