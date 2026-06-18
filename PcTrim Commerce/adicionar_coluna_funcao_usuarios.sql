-- Opcional: executar manualmente no banco loja2001 para habilitar RBAC visual por função.
-- Valores esperados: 'gerente' | 'atendente'

ALTER TABLE usuarios
  ADD COLUMN funcao VARCHAR(20) NOT NULL DEFAULT 'gerente'
  AFTER ativo;

UPDATE usuarios SET funcao = 'gerente' WHERE usuario = 'admin';
