# Suíte de Testes em Camadas

## Objetivo

Validar estabilidade, integridade dos dados, previsibilidade operacional e ausência de falhas silenciosas antes da liberação para produção.

## Princípios obrigatórios

- Idempotência: cancelar, receber, imprimir e fechar período não podem duplicar efeitos.
- Atomicidade: operações críticas devem concluir por inteiro ou falhar com rollback.
- Sem falha silenciosa: erro deve ser explícito para API, tela e operador.
- Backend como fonte da verdade: frontend e impressão devem refletir os mesmos dados.
- Observabilidade mínima: registrar ação, usuário, endpoint e resultado.

## Quando usar o quê

| Comando | Quando |
|---------|--------|
| `python -m tests.run_gate` | **Sempre** antes de deploy / CI local — gate obrigatório |
| `discover -s tests` | Diagnóstico manual (MySQL, legado, skips) — nível 2, não bloqueia deploy |
| `E2E=1 python -m tests.test_contador_pedido_e2e` | Contador de pedido em homologação (opcional) |

## Gate de produção (obrigatório)

Comando:

```bash
python -m tests.run_gate
# ou
powershell -ExecutionPolicy Bypass -File deploy\run_test_gate.ps1
```

Inclui **somente**:

| Pasta | Conteúdo |
|-------|----------|
| `tests/unit/` | Regras isoladas (fechamento, etc.) |
| `tests/api/` | Contratos de APIs críticas (mock) |
| `tests/integration/` | Fluxos críticos com mocks (impressão) |

**Não inclui:**

- arquivos em `tests/*.py` da raiz (MySQL/estoque/retail/admin)
- e2e (`test_contador_pedido_e2e`)
- qualquer teste que precise de MySQL real, `.env` de produção ou rede

Requisitos do gate:

- executa as 3 camadas **sempre** (continue-all); se uma falha, as outras ainda rodam
- exit code `0` = verde; qualquer failure/error → `!= 0`
- sem MySQL, sem `TEST_DB_*` obrigatório, sem rede
- `deploy/deploy_vps8.py` roda o gate no início (`SKIP_TEST_GATE=1` só se pular conscientemente)
- `VERBOSE=1` mostra unittest detalhado por teste

### Exemplo de saída

```
==> Gate de produção (isolado, continue-all)
[UNIT] 5 testes -> OK (0.01s)
[API] 9 testes -> OK (0.07s)
[INTEGRATION] 2 testes -> OK (0.04s)

TOTAL: 16 testes -> OK (0.12s)
```

Em falha (ainda roda as outras camadas):

```
[UNIT] 5 testes -> OK (0.01s)
[API] 9 testes -> FAIL (0.08s)  failures=1 errors=0
[INTEGRATION] 2 testes -> OK (0.04s)

TOTAL: 16 testes -> FAIL (0.13s)
  falhas:
    [API] test_exemplo (... )
```

## Discover nível 2 (manual / opcional)

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Esperado: **todos passam ou estão skipados** — nenhuma falha ativa.  
**Não** bloqueia deploy. Use para inspecionar legado/MySQL; skips usam a mensagem fixa `Dependência de ambiente externo (MySQL/E2E)`.

### Ambiente MySQL (nível 2)

`tests/test_env.py`:

- Preferir: `TEST_DB_HOST`, `TEST_DB_PORT`, `TEST_DB_NAME`, `TEST_DB_USER`, `TEST_DB_PASS`
- Fallback: `MYSQL_*` / `.env`
- Helpers: `aplicar_env_teste()`, `conectar_teste()`
- `REQUIRE_TEST_DB=1` exige `TEST_DB_*` explícito (sem produção silenciosa)

Testes MySQL da raiz usam `conectar_teste()` e fazem skip com:

`Dependência de ambiente externo (MySQL/E2E)`

E2E contador:

```bash
set E2E=1
python -m tests.test_contador_pedido_e2e
```

(ou `E2E_LIVE=1` com servidor em `:2001`)

## Ajustado vs desativado

### Ajustado

| Item | Mudança |
|------|---------|
| `tests/run_gate.py` | Gate isolado unit/api/integration + resumo + exit code |
| `deploy/run_test_gate.ps1` | Wrapper PowerShell do gate |
| `deploy/deploy_vps8.py` | Gate antes do upload |
| `tests/test_env.py` | `TEST_DB_*` + `conectar_teste()` |
| `test_estoque`, `test_retail_*`, `test_restaurant_estoque_pdv` | `conectar_teste` + SkipTest se DB down |
| `test_contador_pedido_e2e` | `E2E=1` / `E2E_LIVE=1`; `conectar_teste` |
| `_db_integrity_check.py` | Usa `conectar_teste` |
| `test_login_otp_whatsapp` | Mock `conectar_admin` + `locate_login_user` |
| `test_clientes_internos` | Fixture mock com porta 3308 |

### Desativado (skip)

| Item | Motivo (mensagem) |
|------|-------------------|
| `PlatformAdminRouteTests` | Dependência de ambiente externo (MySQL/E2E) |
| `test_casa_item_nova_venda_bloqueada` | Dependência de ambiente externo (MySQL/E2E) |
| Classes MySQL raiz sem DB acessível | Dependência de ambiente externo (MySQL/E2E) |
| E2E contador sem `E2E=1` | Script standalone; não entra no gate nem no discover como TestCase |

## Checklist final de liberação

1. `python -m tests.run_gate` verde
2. impressão validada em estação real (checklist manual)
3. checklist manual de produção concluído

Opcional: discover nível 2 verde (pass/skip).

## Fora de escopo

- SQLite em memória
- Reescrever a suíte legada
- Cobertura total
- Incluir MySQL/e2e no gate
