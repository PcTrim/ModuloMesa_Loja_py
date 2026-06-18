-- Compatível com MySQL 5.x
SET @col_exists := (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'dadosloja'
      AND COLUMN_NAME = 'id_cliente'
);
SET @ddl := IF(@col_exists = 0,
    'ALTER TABLE dadosloja ADD COLUMN id_cliente INT NULL',
    'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists := (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'dadosloja'
      AND INDEX_NAME = 'idx_dadosloja_id_cliente'
);
SET @ddl2 := IF(@idx_exists = 0,
    'CREATE UNIQUE INDEX idx_dadosloja_id_cliente ON dadosloja (id_cliente)',
    'SELECT 1'
);
PREPARE stmt2 FROM @ddl2;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;

-- Verifica estrutura
DESCRIBE dadosloja;
SHOW INDEX FROM dadosloja;
