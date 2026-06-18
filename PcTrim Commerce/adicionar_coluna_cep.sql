-- Script para adicionar coluna CEP na tabela clientes
-- Execute este script no seu MySQL

USE novaloja;

SET @col_cep_exists := (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'clientes'
      AND COLUMN_NAME = 'cep'
);
SET @ddl := IF(@col_cep_exists = 0,
    'ALTER TABLE clientes ADD COLUMN cep VARCHAR(9) NULL',
    'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Verifica estrutura
DESCRIBE clientes;
