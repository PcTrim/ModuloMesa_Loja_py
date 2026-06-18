-- Adicionar coluna cliente na tabela canceladas se não existir
ALTER TABLE canceladas ADD COLUMN cliente VARCHAR(255) NULL;
