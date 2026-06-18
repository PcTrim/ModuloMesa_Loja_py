-- Script para adicionar colunas de latitude e longitude na tabela clientes
-- Execute este script no seu MySQL antes de usar o cálculo automático de distância

USE novaloja;

-- Adiciona coluna para latitude do cliente (MySQL 5.x)
SET @col_lat_exists := (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'clientes'
      AND COLUMN_NAME = 'lat_cliente'
);
SET @ddl_lat := IF(@col_lat_exists = 0,
    'ALTER TABLE clientes ADD COLUMN lat_cliente DECIMAL(9,6) NULL',
    'SELECT 1'
);
PREPARE stmt_lat FROM @ddl_lat;
EXECUTE stmt_lat;
DEALLOCATE PREPARE stmt_lat;

-- Adiciona coluna para longitude do cliente (MySQL 5.x)
SET @col_lon_exists := (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'clientes'
      AND COLUMN_NAME = 'lon_cliente'
);
SET @ddl_lon := IF(@col_lon_exists = 0,
    'ALTER TABLE clientes ADD COLUMN lon_cliente DECIMAL(9,6) NULL',
    'SELECT 1'
);
PREPARE stmt_lon FROM @ddl_lon;
EXECUTE stmt_lon;
DEALLOCATE PREPARE stmt_lon;

-- Verifica se as colunas foram criadas
DESCRIBE clientes;
