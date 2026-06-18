
-- Script para criar a tabela 'liquidadas' com a mesma estrutura da tabela 'deliverypendente'

-- Drop da tabela se existir (comentado por segurança, descomente se necessário)
-- DROP TABLE IF EXISTS liquidadas;

-- Criação da tabela liquidadas

CREATE TABLE IF NOT EXISTS liquidada (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nropedido VARCHAR(50),
    telefone VARCHAR(20),
    cep VARCHAR(10),
    nome VARCHAR(100),
    endereco VARCHAR(200),
    nrocasa VARCHAR(20),
    complemento VARCHAR(100),
    produto VARCHAR(200),
    preco DECIMAL(10,2),
    quantidade DECIMAL(10,3),
    codigoproduto VARCHAR(50),
    classe VARCHAR(50),
    data_liquidacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_nropedido (nropedido),
    INDEX idx_data (data_liquidacao)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

