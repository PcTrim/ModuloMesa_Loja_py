# Guia para quem nunca fez deploy — LojaOnline na Hostinger

Leia na ordem. Você não precisa entender programação; é seguir passos.

---

## Seu caso (banco já no servidor + PC já usa esse banco)

**Você NÃO precisa** criar banco novo nem importar SQL. Os dados já estão no MySQL da Hostinger.

O que muda ao subir o site **para o servidor**:

| No seu PC (hoje) | No servidor (produção) |
|------------------|------------------------|
| Programa roda no Windows | Programa roda no Linux (Gunicorn) |
| `.env` com IP do servidor (ex.: `92.113.33.100`) | `.env` com **`MYSQL_HOST=127.0.0.1`** (banco no mesmo servidor) |
| Porta MySQL pode ser `3308` (como no PC) | Porta em geral **`3306`** no servidor — use a que o painel Hostinger mostrar |
| Usuário, senha e nome do banco | **Copie iguais** do seu `.env` local |

**Passos que bastam para você:** 1 FileZilla → 2 criar `.env` no servidor → 3 SSH (instalar e ligar) → 4 domínio Nginx.  
**Pule** a seção “PASSO 3 — Banco de dados” mais abaixo.

---

## O que você vai fazer (visão geral)

Imagine três “andares”:

1. **Seu computador** — onde está o projeto hoje (homologação).
2. **Servidor Hostinger** — onde o site vai ficar online 24h.
3. **MySQL no servidor** — onde ficam clientes, produtos e pedidos.

Você vai:

- **Copiar os arquivos** do PC para o servidor → **FileZilla** (você já usa).
- **Ligar o programa Python** no servidor → precisa de **SSH** (terminal remoto). É como abrir o “prompt de comando” do servidor. No Windows use **PuTTY** ou o terminal que a Hostinger indicar.
- **Apontar o domínio** para o programa → normalmente **Nginx** (já deve existir se PHP/Node funcionam). Quem configurou as outras apps pode repetir o mesmo tipo de configuração.

---

## O que é cada ferramenta (1 frase)

| Nome | Para que serve |
|------|----------------|
| **FileZilla** | Copiar pastas/arquivos do PC para o servidor |
| **SSH / PuTTY** | Digitar comandos no servidor (instalar Python, iniciar o site) |
| **MySQL** | Banco de dados (tabelas de loja, usuários, pedidos) |
| **`.env`** | Arquivo de senhas e configurações (NÃO vai para o Git; cria no servidor) |
| **Gunicorn** | Programa que mantém o Flask rodando no servidor |
| **Nginx** | Porta da frente: o visitante acessa `https://seusite.com` e o Nginx repassa para o Gunicorn |

---

## ANTES DE COMEÇAR — anote isto

Peça ou localize na Hostinger / nas outras apps:

- [ ] **IP ou host** do servidor (ex.: `123.45.67.89` ou `ssh.seudominio.com`)
- [ ] **Usuário SSH** (ex.: `root` ou `u123456789`)
- [ ] **Senha SSH** ou **arquivo de chave** (.ppk / .pem)
- [ ] **Pasta** onde estão hoje o PHP ou Node (ex.: `/var/www/...`) — a LojaOnline pode ficar **ao lado**, ex.: `/var/www/lojaonline`
- [ ] **Domínio ou subdomínio** para o PDV (ex.: `pdv.minhaloja.com.br`)
- [ ] **MySQL:** nome do banco, usuário, senha, porta (geralmente `3306` no servidor)

Sem SSH você consegue **enviar arquivos**, mas **não consegue “ligar”** o site sozinho.

---

## PASSO 1 — Enviar o projeto com FileZilla

1. Abra o **FileZilla**.
2. Conecte com os **mesmos dados** que usa nas outras aplicações (Host, usuário, senha, porta **22** se for SFTP).
3. **Esquerda (local):** navegue até a pasta do projeto no PC, por exemplo:  
   `Desktop\Projetos_em_andamento\_Mexendo\LojaOnline`
4. **Direita (servidor):** entre na pasta onde quer o site, por exemplo:  
   `/var/www/lojaonline`  
   (crie a pasta `lojaonline` se não existir: botão direito → criar diretório)
5. Selecione **tudo** na esquerda **exceto**:
   - pasta `.venv`
   - pasta `.venv-1`
   - arquivo `.env` (se existir no PC — não envie)
   - pastas `__pycache__`
   - pasta `.git` (se existir)
6. Arraste para a direita e aguarde o upload terminar.

Lista completa: arquivo `deploy/FILEZILLA_EXCLUIR.txt`.

---

## PASSO 2 — Criar o arquivo de configuração no servidor

No servidor (painel direito do FileZilla), na pasta `lojaonline`:

1. Encontre o arquivo `deploy/env.production.example`.
2. **Baixe** para o PC (botão direito → Download).
3. Renomeie para **`.env`** (só ponto env).
4. Abra com Bloco de Notas e preencha:

```
ENVIRONMENT=production
FLASK_SECRET_KEY=cole-aqui-uma-frase-longa-aleatoria-qualquer

MYSQL_HOST=127.0.0.1
MYSQL_USER=seu_usuario_mysql
MYSQL_PASSWORD=sua_senha_mysql
MYSQL_PORT=3306
MYSQL_DATABASE=loja2001

FLASK_DEBUG=0
SESSION_COOKIE_SECURE=1

LOJA_PEDIDOS_SALVOS_DIR=/var/www/lojaonline/data/pedidos_salvos
LOJA_RELATORIOS_DIR=/var/www/lojaonline/data/relatorios
```

5. Ajuste `/var/www/lojaonline` se você usou **outra pasta** no passo 1.
6. Envie o `.env` de volta para a **raiz** de `lojaonline` (mesmo nível que `app.py`).

**FLASK_SECRET_KEY:** pode ser qualquer texto longo (ex.: 50 letras aleatórias). Serve para sessão de login.

---

## PASSO 3 — Banco de dados MySQL

Você precisa de um banco com as tabelas da loja.

**Se já existe banco `loja2001` no servidor com dados:** use usuário/senha no `.env`.

**Se o banco é novo:**

1. No painel Hostinger (ou phpMyAdmin), crie banco `loja2001`.
2. Crie usuário com acesso só a esse banco (anote no `.env`).
3. Importe o arquivo `criar_banco_loja2001_completo.sql` (está na pasta que você enviou pelo FileZilla). No phpMyAdmin: Importar → escolher o arquivo → Executar.

**Se quer copiar tudo da homologação do PC:**

No PC (com MySQL rodando local), alguém com experiência pode gerar um arquivo `.sql` com `mysqldump` e você importa no servidor pelo phpMyAdmin.

### Cadastrar uma nova loja (multi-tenant)

O mesmo banco `loja2001` pode atender **várias lojas**. Cada loja tem um `id_cliente` (1, 2, 3…). Para não precisar de SQL manual:

1. No `.env` do servidor, defina quem da equipe técnica pode administrar:
   ```env
   PLATFORM_ADMIN_USERS=suporte,admin_pctrim
   ```
2. Faça login no sistema com um desses usuários (o login precisa existir na tabela `usuarios`).
3. Acesse **`https://seu-dominio/admin/lojas`** (ou `/LojaOnline/admin/lojas` se usar subpasta).
4. Preencha o formulário **Nova loja** (nome, login e senha do gerente).
5. O sistema cria automaticamente: usuário, `dadosloja`, contador de pedidos, configuração, formas de pagamento e taxas de entrega padrão.
6. Entregue login/senha ao cliente. Ele completa produtos e impressoras em **Configurações**.

**Checklist pós-cadastro (manual):** impressoras, WhatsApp (uazapi), e `BUSINESS_TYPE=retail` no `.env` se a instalação for PDV de varejo (hoje é por servidor, não por loja).

---

## PASSO 4 — SSH: instalar e ligar o site

Aqui você **não usa FileZilla**. Usa **PuTTY** (Windows) ou terminal da Hostinger.

### 4.1 Abrir PuTTY

1. Baixe PuTTY se não tiver: https://www.putty.org/
2. Host Name = IP ou host SSH da Hostinger
3. Port = 22
4. Open → login e senha (ou chave)

### 4.2 Comandos (copie um bloco por vez)

Troque `/var/www/lojaonline` se sua pasta for outra.

```bash
cd /var/www/lojaonline
```

```bash
bash deploy/install_server.sh
```

(Isso cria o ambiente Python e instala bibliotecas. Pode demorar alguns minutos.)

```bash
bash deploy/bootstrap_schema.sh
```

(Cria/ajusta tabelas extras que o app precisa.)

```bash
mkdir -p data/pedidos_salvos data/relatorios
```

```bash
sudo cp deploy/lojaonline.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable lojaonline
sudo systemctl start lojaonline
```

Ver se está rodando:

```bash
sudo systemctl status lojaonline
```

Deve aparecer **active (running)** em verde. Se der erro, anote a mensagem.

Teste interno:

```bash
curl -I http://127.0.0.1:8001/login/form
```

Se aparecer `HTTP/1.1 200` ou `302`, o Flask está vivo.

---

## PASSO 5 — Nginx e domínio (site no navegador)

Esta parte costuma ser **igual às suas apps PHP/Node**.

1. Peça a quem configurou o servidor **ou** siga o painel Hostinger para criar um **subdomínio** (ex.: `pdv.seudominio.com.br`) apontando para o servidor.
2. Copie o arquivo `deploy/nginx-lojaonline.conf` para o Nginx (no servidor, com ajuda de quem administra):

   ```bash
   sudo cp /var/www/lojaonline/deploy/nginx-lojaonline.conf /etc/nginx/sites-available/lojaonline
   ```

3. Edite o domínio dentro do arquivo (`server_name`).
4. Ative e recarregue:

   ```bash
   sudo ln -s /etc/nginx/sites-available/lojaonline /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl reload nginx
   ```

5. HTTPS (cadeado): `sudo certbot --nginx -d pdv.seudominio.com.br`

**Se não souber fazer o passo 5:** envie para o suporte Hostinger ou para quem montou PHP/Node:  
*“Preciso de um virtual host Nginx apontando `pdv.meudominio.com` para `http://127.0.0.1:8001` e servir `/var/www/lojaonline/static/` em `/static/`.”*

---

## PASSO 6 — Testar no navegador

1. Abra `https://pdv.seudominio.com.br/login/form` (troque pelo seu domínio).
2. Faça login com um usuário que existe no MySQL.
3. Entre em `/casa` e `/mesa`.

Se não abrir:

- `sudo journalctl -u lojaonline -n 50` — mostra erros do Python
- Confira `.env` (usuário/senha MySQL)
- Confira se o banco foi importado

---

## Quando atualizar o sistema depois

1. **FileZilla:** envie só os arquivos que mudaram (de novo, sem `.venv` e sem `.env`).
2. **SSH:**

   ```bash
   cd /var/www/lojaonline
   source .venv/bin/activate
   pip install -r requirements.txt
   sudo systemctl restart lojaonline
   ```

---

## O que NÃO funciona no servidor Linux

- Impressão direta em impressora do Windows (como no PDV local). O resto do sistema funciona.

---

## Precisa de ajuda humana?

Monte um texto para Hostinger ou para seu técnico:

> Tenho uma app Flask em `/var/www/lojaonline`, entrada WSGI `wsgi:application`, Gunicorn na porta `127.0.0.1:8001`. Preciso de virtual host Nginx + SSL para `SUBDOMINIO` e permissão de escrita em `/var/www/lojaonline/data/`. MySQL local em `127.0.0.1:3306`, banco `loja2001`.

---

## Resumo em 6 linhas

1. FileZilla → enviar pasta (sem `.venv` e sem `.env`).
2. Criar `.env` no servidor com senhas MySQL.
3. Importar banco SQL no MySQL.
4. SSH → `install_server.sh` → `bootstrap_schema.sh` → `systemctl start lojaonline`.
5. Nginx apontar domínio para porta 8001.
6. Abrir o site no navegador e testar login.

Guia técnico completo (referência): `deploy/README_DEPLOY.md`.
