# pedidofacil.online — erro "Not Found" (Apache)

## O que aconteceu

- O **Gunicorn** responde em `http://127.0.0.1:8001` (teste `curl` deu 200 OK).
- O navegador abre **https://pedidofacil.online** → quem responde é o **Apache**, não o Flask.
- O Apache **nao sabe** encaminhar para a porta 8001 → **404 Not Found**.

## Solucao (escolha UMA)

### Opcao 1 — Subdominio (melhor se o site principal ja usa Apache/PHP)

Ex.: `https://pdv.pedidofacil.online`

1. No DNS do dominio, crie registro **A** ou **CNAME**: `pdv` → IP do servidor.
2. No servidor, use `deploy/apache-lojaonline.conf.example` com `ServerName pdv.pedidofacil.online`.
3. Certificado SSL para `pdv.pedidofacil.online` (certbot).

### Opcao 2 — Dominio inteiro para LojaOnline

So use se **pedidofacil.online** nao tiver outro site importante.

`ServerName pedidofacil.online` no arquivo Apache e proxy para `127.0.0.1:8001`.

---

## Comandos no servidor (SSH)

```bash
sudo a2enmod proxy proxy_http headers ssl rewrite
sudo cp /var/www/html/LojaOnline/deploy/apache-lojaonline.conf.example /etc/apache2/sites-available/lojaonline.conf
sudo nano /etc/apache2/sites-available/lojaonline.conf
```

Ajuste: `ServerName`, caminhos dos certificados SSL.

```bash
sudo a2ensite lojaonline.conf
sudo apache2ctl configtest
sudo systemctl reload apache2
```

Certificado (se ainda nao tiver para o subdominio):

```bash
sudo certbot --apache -d pdv.pedidofacil.online
```

Teste no navegador:

`https://pdv.pedidofacil.online/login/form`

---

## URL correta no navegador

| URL | Resultado esperado |
|-----|-------------------|
| `https://pedidofacil.online/` | 404 ate configurar proxy OU outro site |
| `https://pedidofacil.online/login/form` | 404 ate configurar proxy no Apache |
| `https://pdv.pedidofacil.online/login/form` | Login LojaOnline (apos Apache configurado) |

O app Flask usa rotas como `/login/form`, `/casa`, `/mesa` — nao e pasta fisica no Apache.
