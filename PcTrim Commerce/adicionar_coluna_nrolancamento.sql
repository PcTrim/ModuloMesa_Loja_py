-- Adicionar coluna nrolancamento na tabela mesa
-- Esta coluna agrupa itens de múltipla escolha (ex: partes de uma pizza)

ALTER TABLE mesa 
ADD COLUMN nrolancamento INT NULL;

-- Criar índice para melhorar performance de buscas
CREATE INDEX idx_mesa_nrolancamento ON mesa(nrolancamento);

-- Atualizar registros existentes com nrolancamento único (cada item = 1 lançamento)
UPDATE mesa SET nrolancamento = id WHERE nrolancamento IS NULL;
