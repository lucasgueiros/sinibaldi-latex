# Deploy na VM e CI/CD (GitHub Actions)

Mesmo esquema do site da Academia Leão XIII (`academialeaoxiii.org.br/deploy/`), na **mesma VM** e no
**mesmo banco** dele: VM Ubuntu 22.04 com nginx + gunicorn + systemd, sem containers, publicação
automática pelo GitHub Actions.

Endereço provisório: **https://sinibaldi.familiagueiros.com.br**
Homologação: **https://hml.sinibaldi.familiagueiros.com.br** (branch `homolog`)

```
PR / push ──► job "Testes" (runner do GitHub, ubuntu-22.04, Python 3.10; SQLite e PostgreSQL 14)
merge na master ──► job "Publicar na VM" (runner self-hosted DESTE repositório, na VM)
                    git archive <sha> web tools tex deploy | sudo -u sinibaldi /srv/sinibaldi/bin/release <sha>
push na homolog ──► job "Publicar na homologação" (mesmo runner, mesma VM)
                    git archive <sha> web tools tex deploy | sudo -u sinibaldi-hml /srv/sinibaldi-hml/bin/release <sha>
```

| Instância | Usuário | Banco (o do site) | Esquema / papel | Serviço e nginx |
|---|---|---|---|---|
| produção | `sinibaldi` | `academialeaoxiii` | `sinibaldi` / `sinibaldi` | `sinibaldi` |
| homologação | `sinibaldi-hml` | `academialeaoxiii_hml` | `sinibaldi` / `sinibaldi_hml` | `sinibaldi-hml` |

## O banco compartilhado

O editor usa o banco do site da Academia (o `DB_NAME` de `/etc/academialeaoxiii/env`), mas num
**esquema próprio** (`DB_SCHEMA=sinibaldi`) e com **papel próprio**, cujo `search_path` é só esse
esquema. Assim as tabelas do Django do editor (`auth_user`, `django_migrations`, `django_session`…) não
se misturam com as homônimas do site, e o papel do editor não lê nem altera as do site (`permission
denied`). O papel do site recebe `SELECT` no esquema do editor, para que o backup diário dele (o
`pg_dump` do banco inteiro) continue funcionando e inclua o editor. O editor tem ainda o seu próprio
backup, só do esquema (`deploy/backup.sh`, 03:45).

Contas: **os usuários são separados** (cada esquema tem o seu `auth_user`). Para compartilhá-los seria
preciso `DB_SCHEMA=` vazio (esquema `public`), o que mistura as tabelas do Django dos dois projetos;
não use sem planejar.

Depois do `sync-hml-from-prod.sh` **do site** (que copia o banco inteiro para a homologação), as
tabelas do editor na homologação ficam com o dono errado: rode `sudo bash deploy/bootstrap-hml.sh`
daqui, que devolve a posse (ou `deploy/sync-hml-from-prod.sh` daqui, que copia só o esquema do editor).

## O que fica na VM

- `/srv/sinibaldi/releases/<sha>/{web,tools,tex,deploy}`: uma pasta por versão (são mantidas as 5 últimas).
  `tools/` e `tex/` vão junto porque o site os chama (TEI → LaTeX → PDF, slides).
- `/srv/sinibaldi/current`: link para a versão no ar
- `/srv/sinibaldi/dados/`: `SINIBALDI_DADOS`, os dados que não vão nas versões (imagens do scan
  `volN/paginas/*.png`, `manifesto.tsv`, os PDFs originais do fac-símile, `volN.corrigido.xml`),
  enviados por `deploy/envia-dados.sh`
- `/srv/sinibaldi/cache/`: `SINIBALDI_CACHE` (PDFs e LaTeX gerados, JPEG reduzidos), regenerável
- `/srv/sinibaldi/{venv,static,backups}`
- `/etc/sinibaldi/env`: segredos (chave do Django, senha do banco), gerados pelo bootstrap; ver `env.example`
- serviço systemd `sinibaldi` (gunicorn via socket unix), atrás do nginx

O gunicorn roda com **um processo e 8 threads** (`gunicorn.conf.py`): os PDFs grandes compilam numa
thread em segundo plano e o andamento fica em memória, o que exige um processo só.

A cada publicação, `release.sh` extrai o código, instala as dependências e roda `collectstatic`,
`check --deploy` e `migrate`. Depois troca o link `current`, reinicia o gunicorn e testa a página
inicial. **Se o teste falhar, volta sozinho para a versão anterior** (migrações já aplicadas não são
desfeitas).

## 1. Preparação (uma única vez, na VM)

Pressupõe o site da Academia já instalado na VM. Antes, aponte o DNS de
`sinibaldi.familiagueiros.com.br` para o IP da VM.

**Runner**: um runner self-hosted é registrado por repositório; o do site não pega os jobs daqui.
Registre um segundo runner na VM para `lucasgueiros/sinibaldi-latex` (*Settings › Actions › Runners ›
New self-hosted runner*), num diretório próprio (ex.: `~/actions-runner-sinibaldi`), e instale-o como
serviço (`sudo ./svc.sh install && sudo ./svc.sh start`). O bootstrap detecta o usuário pela unidade
`actions.runner.*sinibaldi*`; senão, informe `RUNNER_USER=<usuário>`.

```bash
git clone https://github.com/lucasgueiros/sinibaldi-latex.git /tmp/sinibaldi-bootstrap   # ou --filter=blob:none
cd /tmp/sinibaldi-bootstrap && git checkout master
sudo LETSENCRYPT_EMAIL=seu-email@exemplo.com bash deploy/bootstrap-vm.sh
```

O bootstrap é idempotente e:

- instala o TeX (LuaLaTeX, `texlive-fonts-extra` com EB Garamond e Cinzel dos slides) e o `mutool`,
  além do que o site já usa;
- cria o usuário `sinibaldi`, o papel e o esquema no banco do site, as permissões e `/etc/sinibaldi/env`;
- configura o systemd, o nginx (sem tocar no site da Academia) e o HTTPS;
- cria o backup diário do esquema (03:45);
- dá ao usuário do runner permissão sudo **apenas** para `/srv/sinibaldi/bin/release`;
- publica a primeira versão.

Depois, carregue os dados, **da máquina de trabalho** (raiz do checkout principal, que tem as imagens):

```bash
deploy/envia-dados.sh <ssh-host>          # scans, PDFs originais, TEI (~4 GB na 1ª vez; depois, incremental)
deploy/envia-banco.sh <ssh-host>          # banco local web/db.sqlite3 → PostgreSQL (só numa instância vazia)
```

Sem o banco local, o texto pode ser criado no servidor a partir do TEI (`web/README.md`):

```bash
sudo -u sinibaldi /srv/sinibaldi/bin/manage importar_tei
sudo -u sinibaldi /srv/sinibaldi/bin/manage derivar_edicao_atualizada
sudo -u sinibaldi /srv/sinibaldi/bin/manage derivar_nova_edicao
sudo -u sinibaldi /srv/sinibaldi/bin/manage createsuperuser
```

Rode o bootstrap de novo quando mudar algo em `deploy/` que não seja `gunicorn.conf.py` ou `backup.sh`
(por exemplo `release.sh`, o nginx ou o systemd). O workflow avisa quando o `release.sh` instalado
estiver desatualizado.

## 2. Atualização automática

Merge na `master` publica sozinho. Também dá para disparar à mão em *Actions › CI/CD › Run workflow*.

Recomendado no GitHub:

- *Settings › Branches*: proteja a `master` e exija o check "Testes".
- *Settings › Actions › General*: exija aprovação para workflows de PRs de forks. O runner
  self-hosted roda na VM, e nenhum código de terceiros deve chegar a ele.

Mudou imagem do scan, `manifesto.tsv` ou o TEI? Isso não vai pelo CI: rode `deploy/envia-dados.sh`.

## 3. Trocar de domínio

```bash
sudo DOMAIN=novo.dominio EXTRA_DOMAINS="sinibaldi.familiagueiros.com.br" \
     LETSENCRYPT_EMAIL=seu-email@exemplo.com bash deploy/bootstrap-vm.sh
```

Depois atualize `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` em `/etc/sinibaldi/env` (o bootstrap não
sobrescreve esse arquivo) e a `url` do ambiente em `.github/workflows/ci-cd.yml`. Reinicie com
`sudo systemctl restart sinibaldi`.

## Operação

```bash
sudo journalctl -u sinibaldi -f
sudo -u sinibaldi /srv/sinibaldi/bin/manage <comando>          # ex.: aplicar_componentes, gerar_indice
sudo -u sinibaldi /srv/sinibaldi/bin/manage preparar_downloads  # pré-gera os PDFs dos volumes no cache
ls -t /srv/sinibaldi/releases
```

Na homologação, troque `sinibaldi` por `sinibaldi-hml` (usuário e caminhos).

Para voltar a uma versão anterior à mão, aponte o link `current` para outra pasta de `releases/` e
reinicie o serviço.

Restaurar o backup do editor (sem tocar no site):

```bash
sudo systemctl stop sinibaldi
sudo -u sinibaldi bash -c 'set -a; . /etc/sinibaldi/env; PGPASSWORD=$DB_PASSWORD pg_restore -h localhost \
    -U $DB_USER -d $DB_NAME --clean --if-exists -n $DB_SCHEMA /srv/sinibaldi/backups/db-AAAAMMDD-HHMM.dump'
sudo systemctl start sinibaldi
```

## Homologação (branch `homolog`)

Pressupõe a homologação do site instalada (banco `academialeaoxiii_hml`). Aponte o DNS de
`hml.sinibaldi.familiagueiros.com.br` para a VM e, de um clone na branch `homolog`:

```bash
sudo LETSENCRYPT_EMAIL=seu-email@exemplo.com bash deploy/bootstrap-hml.sh
deploy/envia-dados.sh <ssh-host> sinibaldi-hml        # da máquina de trabalho
sudo bash deploy/sync-hml-from-prod.sh                # opcional, na VM: copia texto e dados da produção
```

A homologação envia `X-Robots-Tag: noindex`. Push na `homolog` publica nela.
