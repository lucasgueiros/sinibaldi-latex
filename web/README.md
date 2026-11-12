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
