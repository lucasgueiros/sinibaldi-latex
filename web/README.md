# Editor web de *Elementos de Philosophia* (Django MVT)

Backend/fundação: modelos, dialeto de fragmento, conversões TEI, serviços de escrita,
importação/exportação. As telas ficam em `templates/`, `static/` e `frontend/`.

## Como rodar

```bash
cd web
python3 -m venv --system-site-packages .venv      # lxml vem do sistema
.venv/bin/pip install -r requirements.txt
export SINIBALDI_DADOS=/caminho/do/checkout      # opcional: raiz com volN/paginas/*.png (padrão: raiz do repo)

.venv/bin/python manage.py migrate
.venv/bin/python manage.py importar_tei            # edição "1916" (~5 s): [--volume 1 2] [--fonte corrigido] [--recriar]
.venv/bin/python manage.py derivar_nova_edicao     # edição "nova" [--recriar]
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver

.venv/bin/python manage.py exportar_tei --edicao 1916 --volume 2 -o /tmp/vol2.xml   # [--forcar]
.venv/bin/python manage.py test obra
```

Variáveis de ambiente: `SINIBALDI_DADOS`, `SECRET_KEY`, `DEBUG` (`0` desliga), `ALLOWED_HOSTS`.
O grupo `editores` (add/change/delete de `Bloco`) é criado pela migração `0002`.

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
