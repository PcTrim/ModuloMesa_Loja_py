# Print Bridge — impressão com o site no Hostinger



O servidor Linux **não** imprime na térmica Windows. Rode este programa no **mesmo PC** onde está a impressora.



## Uso diário



1. Pasta `deploy\print_bridge` no PC da loja

2. Duplo clique em `iniciar-print-bridge.bat`

3. Deixe a janela aberta

4. Site: `https://pedidofacil.online/LojaOnline/` — **Ctrl+F5** após atualizar arquivos



**Impressora:** vem do MySQL (`impressoras`, `comanda_delivery=S` ou `conta_mesa=S`). O `.bat` não configura impressora.



O bridge resolve nomes **sem diferenciar maiúsculas/minúsculas** e aceita UNC (`\\note\usb` → fila `USB` no Windows).



## Copiar para o PC da loja



- `iniciar-print-bridge.bat`

- `app.py`, `printer_core.py`, `printer_match.py`

- `requirements.txt`

- **Não** copie `.venv`



## Testes



1. `http://127.0.0.1:9123/health` → `impressoras_windows` lista filas do Windows

2. Logado: `/LojaOnline/api/impressora-para-origem?origem=casa` → `printer` do cadastro

3. Imprimir em `/casa` → sucesso; resposta pode incluir `printer_windows`



## Deploy Hostinger (FileZilla)



- `static/imprimir-bridge.js` (?v=7)

- `templates/index.html`, `mesa.html`, `painel_menu.html`

- `app.py` (opcional, APIs)



```bash

sudo systemctl restart lojaonline

```



O bridge **não** roda no Hostinger — só no PC da loja.

