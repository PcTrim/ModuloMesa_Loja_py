-- Script para criar a tabela 'comanda' com toda a estrutura necessária

-- Drop da tabela se existir (comentado por segurança, descomente se necessário)
-- DROP TABLE IF EXISTS comanda;

-- Criação da tabela comanda
CREATE TABLE IF NOT EXISTS comanda (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nropedido INT NOT NULL,
    telefone VARCHAR(20),
    cep VARCHAR(20),
    nome VARCHAR(255),
    endereco VARCHAR(255),
    nrocasa VARCHAR(50),
    complemento VARCHAR(255),
    codigoproduto VARCHAR(50),
    produto VARCHAR(255),
    preco DECIMAL(10,2),
    quantidade INT,
    classe VARCHAR(100),
    entregador VARCHAR(255),
    cliente VARCHAR(255),
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_nropedido (nropedido),
    INDEX idx_telefone (telefone),
    INDEX idx_entregador (entregador),
    INDEX idx_classe (classe)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Adiciona coluna 'cliente' (compatível com MySQL 5.x)
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

-- Verifica a estrutura da tabela
DESCRIBE comanda;

-- Conta registros
SELECT COUNT(*) as total_registros FROM comanda;
