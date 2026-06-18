# Deploy LojaOnline — Hostinger (Linux + FileZilla)

Este guia assume **servidor Linux com SSH** e upload de arquivos via **FileZilla**, como nas suas outras aplicações.

## Visão geral

| Camada | Função |
|--------|--------|
| FileZilla | Enviar código para o servidor |
| MySQL (mesmo servidor) | Banco `loja2001` em `127.0.0.1` |
| Gunicorn | App Flask na porta interna `8001` |
| Nginx | HTTPS e proxy para o Gunicorn |

Impressão Windows (`win32print`) **não funciona no Linux**; o restante do PDV funciona.

---

## 1. FileZilla — enviar o projeto

### Conexão

1. Abra o FileZilla.
2. Use o mesmo **host, usuário e porta SFTP/SSH** das suas outras apps.
3. Painel local: pasta do projeto no PC (`LojaOnline`).
4. Painel remoto: crie ou use uma pasta, por exemplo:
   - `/var/www/lojaonline` (comum em VPS), ou
   - `/home/SEU_USUARIO/apps/lojaonline`

### O que enviar

Envie **tudo**, exceto o que está em [`FILEZILLA_EXCLUIR.txt`](FILEZILLA_EXCLUIR.txt):

- Incluir: `app.py`, `wsgi.py`, `requirements.txt`, `templates/`, `static/`, `blueprints/`, `services/`, `deploy/`, arquivos `.sql`, etc.
- **Não enviar:** `.venv`, `.env`, `__pycache__`, `.git`

### Filtro no FileZilla (opcional)

`Editar` → `Configurações de filtros` → adicionar exclusão: `.venv`, `__pycache__`, `.env`

### Arquivos criados só no servidor

1. Copie [`env.production.example`](env.production.example) para `.env` **no servidor** (FileZilla: renomear após upload ou criar localmente e enviar).
2. Preencha `FLASK_SECRET_KEY`, `MYSQL_*`, caminhos `LOJA_*_DIR`.
3. Permissão recomendada (via SSH): `chmod 600 .env`

---

## 2. MySQL no mesmo servidor

1. No painel Hostinger ou `mysql` CLI, execute o modelo [`mysql_setup.example.sql`](mysql_setup.example.sql) (ajuste senha).
2. Importe estrutura/dados:
   - **Banco novo:** envie `criar_banco_loja2001_completo.sql` e importe no phpMyAdmin ou:
     ```bash
     mysql -u loja_app -p loja2001 < criar_banco_loja2001_completo.sql
     ```
   - **Copiar homologação:** no PC, `mysqldump` do banco local; envie o `.sql` pelo FileZilla; importe no servidor.
3. Porta: em produção use `MYSQL_PORT=3306` no `.env` (local pode ser `3308`).

---

## 3. SSH — Python e dependências

O FileZilla só envia arquivos; **venv e pip** rodam no servidor:

```bash
cd /var/www/lojaonline   # ajuste o caminho
bash deploy/install_server.sh
```

Ou manualmente:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p data/pedidos_salvos data/relatorios
```

Ajuste dono das pastas (ex.: usuário do Gunicorn):

```bash
sudo chown -R www-data:www-data data
```

---

## 4. Schema do banco (uma vez)

Com `.env` configurado:

```bash
cd /var/www/lojaonline
bash deploy/bootstrap_schema.sh
```

---

## 5. Gunicorn + systemd

1. Edite [`lojaonline.service`](lojaonline.service) se a pasta no servidor for diferente de `/var/www/lojaonline`.
2. Instale o serviço:

```bash
sudo cp deploy/lojaonline.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable lojaonline
sudo systemctl start lojaonline
sudo systemctl status lojaonline
```

Logs: `journalctl -u lojaonline -f`

Teste local no servidor: `curl -I http://127.0.0.1:8001/login/form`

---

## 6. Nginx + HTTPS

1. Copie [`nginx-lojaonline.conf`](nginx-lojaonline.conf) para `/etc/nginx/sites-available/lojaonline`.
2. Altere `server_name` para seu subdomínio (ex.: `pdv.seudominio.com.br`).
3. Ative e recarregue:

```bash
sudo ln -s /etc/nginx/sites-available/lojaonline /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

4. Certificado: `sudo certbot --nginx -d pdv.seudominio.com.br`

Se já existir Nginx para PHP/Node, adicione um **novo `server_name`** (subdomínio) em vez de misturar na mesma raiz, salvo se souber configurar `location`.

---

## 6b. Apache — subpath `/LojaOnline/` (pedidofacil.online)

Quando o domínio já tem outro site na raiz, use **apenas** o subpath:

1. No `.env` do servidor: `LOJA_URL_PREFIX=/LojaOnline`
2. Apache (ex.: `000-default-le-ssl.conf`):
   - `ProxyPass /LojaOnline/ http://127.0.0.1:8001/`
   - `ProxyPassReverse /LojaOnline/ http://127.0.0.1:8001/`
   - `Alias /LojaOnline/static ...` e `ProxyPass /LojaOnline/static !`
   - **Remova** `ProxyPass /` na raiz se existir (conflita com o site principal).
3. Modelo: [`apache-lojaonline.conf.example`](apache-lojaonline.conf.example) ou `bash deploy/apache-inject-proxy.sh`
4. Reinicie: `sudo systemctl reload apache2` e `sudo systemctl restart lojaonline`

URL de teste: `https://pedidofacil.online/LojaOnline/login/form`

---

## 7. Checklist pós-deploy

- [ ] `https://seu-dominio/LojaOnline/login/form` abre (ou raiz, se sem prefixo)
- [ ] Login funciona (usuário no MySQL)
- [ ] `/casa` e `/mesa` após autenticação
- [ ] Sem erro 500 (`journalctl -u lojaonline`)
- [ ] Pastas `data/pedidos_salvos` e `data/relatorios` graváveis
- [ ] `FLASK_DEBUG=0` no `.env`
- [ ] Porta `8001` **não** exposta na internet (só Nginx)

---

## 8. Atualizar versão (deploy contínuo)

1. **FileZilla:** envie arquivos alterados (mesmas exclusões).
2. **SSH:**
   ```bash
   cd /var/www/lojaonline
   source .venv/bin/activate
   pip install -r requirements.txt
   sudo systemctl restart lojaonline
   ```

---

## Arquivos desta pasta

| Arquivo | Uso |
|---------|-----|
| `env.production.example` | Modelo do `.env` no servidor |
| `lojaonline.service` | Systemd + Gunicorn |
| `nginx-lojaonline.conf` | Proxy reverso |
| `mysql_setup.example.sql` | Usuário/banco MySQL |
| `install_server.sh` | venv + pip |
| `bootstrap_schema.sh` | Tabelas/colunas iniciais |
| `FILEZILLA_EXCLUIR.txt` | Lista para não enviar |
