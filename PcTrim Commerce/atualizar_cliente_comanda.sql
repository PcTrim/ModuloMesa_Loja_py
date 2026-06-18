-- Atualizar registros antigos da tabela comanda
-- Copia o valor de 'nome' para 'cliente' onde cliente está vazio

UPDATE comanda 
SET cliente = nome 
WHERE cliente IS NULL OR cliente = '';
