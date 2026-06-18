-- Compatível com MySQL 5.x
SET @col_cliente_exists := (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'comanda'
      AND COLUMN_NAME = 'cliente'
);
SET @ddl := IF(@col_cliente_exists = 0,
    'ALTER TABLE comanda ADD COLUMN cliente VARCHAR(255) DEFAULT NULL',
    'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_nropedido_exists := (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'comanda'
      AND INDEX_NAME = 'idx_nropedido'
);
SET @ddl2 := IF(@idx_nropedido_exists = 0,
    'ALTER TABLE comanda ADD INDEX idx_nropedido (nropedido)',
    'SELECT 1'
);
PREPARE stmt2 FROM @ddl2;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;

SET @idx_telefone_exists := (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'comanda'
      AND INDEX_NAME = 'idx_telefone'
);
SET @ddl3 := IF(@idx_telefone_exists = 0,
    'ALTER TABLE comanda ADD INDEX idx_telefone (telefone)',
    'SELECT 1'
);
PREPARE stmt3 FROM @ddl3;
EXECUTE stmt3;
DEALLOCATE PREPARE stmt3;

-- Executa depois de aplicar as alterações
SHOW COLUMNS FROM comanda;
