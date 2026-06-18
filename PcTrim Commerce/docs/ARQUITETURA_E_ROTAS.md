# Inventario tecnico LojaOnline

## Funcoes principais
- Autenticacao e sessao multi-tenant em `auth_routes.py`.
- Catalogo de produtos/classificacoes em `app.py` e `blueprints/catalog.py`.
- Fluxo de mesa/comanda em `app.py` e `blueprints/mesa_shop.py`.
- Delivery pendente/cancelamentos em `app.py` e `helpers_app.py`.
- Configuracoes de loja/taxa/entregadores em `app.py` e `services/dados_loja.py`.
- Impressao e PDF em `app.py` e `helpers_app.py`.

## Duplicidades criticas
- Endpoints de catalogo em `app.py` e `blueprints/catalog.py`.
- Endpoints de mesa em `app.py` e `blueprints/mesa_shop.py`.
- Variacao legada completa em `app-Cliente30.py`.

## Prioridade de risco (alto para baixo)
1. SQL dinamico e integridade transacional em operacoes de mesa/pedido.
2. Configuracao de seguranca e segredos por ambiente.
3. Migracao de senha legada para hash bcrypt.
4. Consolidacao arquitetural do monolito para services/repositories.
