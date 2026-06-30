-- =============================================================================
-- Retail catalog v1 — idempotente, MySQL 8 / MariaDB (Hostinger)
-- Seguro: IF NOT EXISTS + ALTER condicional via information_schema
-- NÃO altera dados existentes. Restaurante: category_id/subcategory_id ficam NULL.
--
-- Execução manual (após backup):
--   mysql -u USER -p loja2001 < deploy/sql/retail_catalog_v1.sql
--
-- Gate: executar em produção somente após confirmação explícita "CONFIRMAR EXECUÇÃO"
-- =============================================================================

SET NAMES utf8mb4;
SET @db := DATABASE();

-- -----------------------------------------------------------------------------
-- 1) categoria (por loja)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categoria (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_cliente INT NOT NULL,
    nome VARCHAR(120) NOT NULL,
    ordem_exibicao INT NOT NULL DEFAULT 0,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_categoria_cliente_nome (id_cliente, nome),
    KEY idx_categoria_id_cliente (id_cliente),
    KEY idx_categoria_cliente_ativo_ordem (id_cliente, ativo, ordem_exibicao)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 2) subcategoria (por loja, ligada à categoria)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subcategoria (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_cliente INT NOT NULL,
    categoria_id INT NOT NULL,
    nome VARCHAR(120) NOT NULL,
    ordem_exibicao INT NOT NULL DEFAULT 0,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_subcategoria_cliente_cat_nome (id_cliente, categoria_id, nome),
    KEY idx_subcategoria_id_cliente (id_cliente),
    KEY idx_subcategoria_categoria (categoria_id),
    KEY idx_subcategoria_cliente_ativo_ordem (id_cliente, ativo, ordem_exibicao)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @fk_sub := (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = @db
      AND TABLE_NAME = 'subcategoria'
      AND CONSTRAINT_NAME = 'fk_subcategoria_categoria'
      AND CONSTRAINT_TYPE = 'FOREIGN KEY'
);
SET @sql_sub := IF(@fk_sub = 0,
    'ALTER TABLE subcategoria ADD CONSTRAINT fk_subcategoria_categoria FOREIGN KEY (categoria_id) REFERENCES categoria(id) ON UPDATE CASCADE ON DELETE RESTRICT',
    'SELECT 1');
PREPARE stmt FROM @sql_sub; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- -----------------------------------------------------------------------------
-- 3) produtos — colunas nullable (restaurante: permanecem NULL)
-- -----------------------------------------------------------------------------
SET @col_cat := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'produtos' AND COLUMN_NAME = 'category_id'
);
SET @sql_cat := IF(@col_cat = 0,
    'ALTER TABLE produtos ADD COLUMN category_id INT NULL DEFAULT NULL AFTER id_cliente',
    'SELECT 1');
PREPARE stmt FROM @sql_cat; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_sub := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'produtos' AND COLUMN_NAME = 'subcategory_id'
);
SET @sql_subcol := IF(@col_sub = 0,
    'ALTER TABLE produtos ADD COLUMN subcategory_id INT NULL DEFAULT NULL AFTER category_id',
    'SELECT 1');
PREPARE stmt FROM @sql_subcol; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_cat := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'produtos' AND INDEX_NAME = 'idx_produtos_category_id'
);
SET @sql_idx_cat := IF(@idx_cat = 0,
    'ALTER TABLE produtos ADD KEY idx_produtos_category_id (category_id)',
    'SELECT 1');
PREPARE stmt FROM @sql_idx_cat; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_sub := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'produtos' AND INDEX_NAME = 'idx_produtos_subcategory_id'
);
SET @sql_idx_sub := IF(@idx_sub = 0,
    'ALTER TABLE produtos ADD KEY idx_produtos_subcategory_id (subcategory_id)',
    'SELECT 1');
PREPARE stmt FROM @sql_idx_sub; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @fk_pcat := (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = @db AND TABLE_NAME = 'produtos' AND CONSTRAINT_NAME = 'fk_produtos_category'
);
SET @sql_fk_pcat := IF(@fk_pcat = 0,
    'ALTER TABLE produtos ADD CONSTRAINT fk_produtos_category FOREIGN KEY (category_id) REFERENCES categoria(id) ON UPDATE CASCADE ON DELETE SET NULL',
    'SELECT 1');
PREPARE stmt FROM @sql_fk_pcat; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @fk_psub := (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = @db AND TABLE_NAME = 'produtos' AND CONSTRAINT_NAME = 'fk_produtos_subcategory'
);
SET @sql_fk_psub := IF(@fk_psub = 0,
    'ALTER TABLE produtos ADD CONSTRAINT fk_produtos_subcategory FOREIGN KEY (subcategory_id) REFERENCES subcategoria(id) ON UPDATE CASCADE ON DELETE SET NULL',
    'SELECT 1');
PREPARE stmt FROM @sql_fk_psub; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- -----------------------------------------------------------------------------
-- 4) produto_retail — contexto vitrine (1:1 com produtos.chave)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS produto_retail (
    id INT AUTO_INCREMENT PRIMARY KEY,
    id_cliente INT NOT NULL,
    product_id INT NOT NULL COMMENT 'FK produtos.chave — fonte única da verdade',
    nome_vitrine VARCHAR(200) NULL,
    descricao_vitrine TEXT NULL,
    preco_varejo DECIMAL(10,2) NULL,
    preco_atacado DECIMAL(10,2) NULL,
    comissao DECIMAL(5,2) NULL DEFAULT NULL COMMENT 'Percentual ou valor conforme regra de negócio futura',
    estoque DECIMAL(12,3) NOT NULL DEFAULT 0,
    permite_venda_sem_estoque TINYINT(1) NOT NULL DEFAULT 0,
    destaque TINYINT(1) NOT NULL DEFAULT 0,
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    ordem_exibicao INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_produto_retail_product (product_id),
    KEY idx_produto_retail_id_cliente (id_cliente),
    KEY idx_produto_retail_vitrine (id_cliente, ativo, destaque, ordem_exibicao)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET @fk_pr := (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = @db
      AND TABLE_NAME = 'produto_retail'
      AND CONSTRAINT_NAME = 'fk_produto_retail_product'
      AND CONSTRAINT_TYPE = 'FOREIGN KEY'
);
SET @sql_pr := IF(@fk_pr = 0,
    'ALTER TABLE produto_retail ADD CONSTRAINT fk_produto_retail_product FOREIGN KEY (product_id) REFERENCES produtos(chave) ON UPDATE CASCADE ON DELETE CASCADE',
    'SELECT 1');
PREPARE stmt FROM @sql_pr; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- =============================================================================
-- Fim — retail_catalog_v1
-- =============================================================================
