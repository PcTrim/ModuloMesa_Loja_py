-- Adiciona a coluna 'formapagamento' na tabela deliverypendente
ALTER TABLE deliverypendente ADD COLUMN formapagamento VARCHAR(100) NULL AFTER id_cliente;