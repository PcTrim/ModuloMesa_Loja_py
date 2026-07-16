# Checklist Manual Final

## Pedido

- [ ] Criar pedido novo em balcão
- [ ] Criar pedido novo em delivery
- [ ] Reabrir pedido em `AGUARDE`
- [ ] Editar item
- [ ] Remover item
- [ ] Validar totais no modal e no dashboard

## Cancelamento

- [ ] Cancelar comanda válida
- [ ] Tentar cancelar comanda já cancelada
- [ ] Tentar cancelar pedido já recebido
- [ ] Confirmar mensagem clara para operador

## Recebimento

- [ ] Receber pedido com uma forma de pagamento
- [ ] Receber pedido com múltiplas formas
- [ ] Validar troco
- [ ] Validar que pedido sai de `ABERTO/ROTA` para `RECEBIDO`

## Estoque

- [ ] Validar baixa automática em produto com controle de estoque
- [ ] Validar que baixa não duplica ao repetir ação
- [ ] Conferir histórico de movimentos

## Impressão

- [ ] Imprimir pedido real via Print Bridge
- [ ] Conferir layout térmico W=40
- [ ] Simular bridge offline
- [ ] Validar erro explícito sem falso sucesso

## Fechamento

- [ ] Gerar preview
- [ ] Conferir resumo financeiro
- [ ] Executar fechamento
- [ ] Conferir arquivamento em histórico
- [ ] Validar relatório gerado

## Segurança operacional

- [ ] Testar rota protegida sem login
- [ ] Testar operador sem permissão em rota crítica
- [ ] Validar expiração de sessão em operação aberta
