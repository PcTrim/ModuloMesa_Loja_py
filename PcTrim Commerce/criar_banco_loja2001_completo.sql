-- Script completo para recriar o banco loja2001 (estrutura base do sistema)

CREATE DATABASE IF NOT EXISTS loja2001 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE loja2001;

-- =============================
-- TABELA: usuarios
-- =============================
CREATE TABLE IF NOT EXISTS usuarios (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    usuario VARCHAR(100) NOT NULL UNIQUE,
    senha VARCHAR(255) NOT NULL,
    id_cliente INT DEFAULT 1,
    ativo TINYINT NOT NULL DEFAULT 1,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO usuarios (usuario, senha, id_cliente, ativo)
VALUES ('admin', 'admin', 1, 1);

-- =============================
-- TABELA: classificacao
-- =============================
CREATE TABLE IF NOT EXISTS classificacao (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nomeclassificacao VARCHAR(100) NOT NULL,
    quantidadepartes INT DEFAULT 1,
    nrofoto INT DEFAULT NULL,
    formadecobrar VARCHAR(30) DEFAULT 'normal',
    id_cliente INT NOT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_classificacao_cliente (id_cliente, nomeclassificacao),
    KEY idx_classificacao_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================
-- TABELA: produtos
-- =============================
CREATE TABLE IF NOT EXISTS produtos (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    produto VARCHAR(150) NOT NULL,
    preco DECIMAL(10,2) NOT NULL DEFAULT 0,
    classe VARCHAR(100) NOT NULL,
    porkilo VARCHAR(10) DEFAULT 'Nao',
    impressora VARCHAR(100) DEFAULT NULL,
    cfop VARCHAR(10) DEFAULT '5102',
    ncm VARCHAR(20) DEFAULT NULL,
    display TINYINT DEFAULT 0,
    vendaliberada VARCHAR(10) DEFAULT 'Sim',
    descricao TEXT,
    id_cliente INT NOT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_produtos_classe (classe),
    KEY idx_produtos_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================
-- TABELA: entregador
-- =============================
CREATE TABLE IF NOT EXISTS entregador (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    telefone VARCHAR(20) DEFAULT NULL,
    endereco VARCHAR(255) DEFAULT NULL,
    id_cliente INT NOT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_entregador_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================
-- TABELA: clientes
-- =============================
CREATE TABLE IF NOT EXISTS clientes (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    telefone VARCHAR(20) NOT NULL,
    nome VARCHAR(150) DEFAULT NULL,
    endereco VARCHAR(255) DEFAULT NULL,
    nrocasa VARCHAR(30) DEFAULT NULL,
    complemento VARCHAR(255) DEFAULT NULL,
    referencia VARCHAR(255) DEFAULT NULL,
    bairro VARCHAR(100) DEFAULT NULL,
    cidade VARCHAR(100) DEFAULT NULL,
    estado VARCHAR(2) DEFAULT NULL,
    cep VARCHAR(10) DEFAULT NULL,
    cpf_cnpj VARCHAR(20) DEFAULT NULL,
    taxaentrega DECIMAL(10,2) DEFAULT 0,
    distancia DECIMAL(10,2) DEFAULT 0,
    lat_cliente DECIMAL(10,7) DEFAULT NULL,
    lon_cliente DECIMAL(10,7) DEFAULT NULL,
    id_cliente INT NOT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_clientes_tel_cliente (telefone, id_cliente),
    KEY idx_clientes_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================
-- TABELA: dadosloja
-- =============================
CREATE TABLE IF NOT EXISTS dadosloja (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    id_cliente INT NOT NULL,
    nome VARCHAR(255) NOT NULL,
    endereco TEXT,
    bairro VARCHAR(100),
    cidade VARCHAR(100),
    cep VARCHAR(10),
    telefone VARCHAR(20),
    cnpj VARCHAR(20),
    latitude VARCHAR(20),
    longitude VARCHAR(20),
    ddd VARCHAR(3),
    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_dadosloja_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================
-- TABELA: contadorpedido
-- =============================
CREATE TABLE IF NOT EXISTS contadorpedido (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    contador INT NOT NULL DEFAULT 0,
    id_cliente INT NOT NULL,
    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_contador_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO contadorpedido (contador, id_cliente) VALUES (0, 1);

-- =============================
-- TABELA: txentrega
-- =============================
CREATE TABLE IF NOT EXISTS txentrega (
    id INT AUTO_INCREMENT PRIMARY KEY,
    chave INT NOT NULL DEFAULT 1,
    id_cliente INT NOT NULL,
    faixa1_d DECIMAL(10,2) DEFAULT NULL,
    faixa1_v DECIMAL(10,2) DEFAULT NULL,
    faixa2_d DECIMAL(10,2) DEFAULT NULL,
    faixa2_v DECIMAL(10,2) DEFAULT NULL,
    faixa3_d DECIMAL(10,2) DEFAULT NULL,
    faixa3_v DECIMAL(10,2) DEFAULT NULL,
    faixa4_d DECIMAL(10,2) DEFAULT NULL,
    faixa4_v DECIMAL(10,2) DEFAULT NULL,
    faixa5_d DECIMAL(10,2) DEFAULT NULL,
    faixa5_v DECIMAL(10,2) DEFAULT NULL,
    faixa6_d DECIMAL(10,2) DEFAULT NULL,
    faixa6_v DECIMAL(10,2) DEFAULT NULL,
    faixa7_d DECIMAL(10,2) DEFAULT NULL,
    faixa7_v DECIMAL(10,2) DEFAULT NULL,
    faixa8_d DECIMAL(10,2) DEFAULT NULL,
    faixa8_v DECIMAL(10,2) DEFAULT NULL,
    faixa9_d DECIMAL(10,2) DEFAULT NULL,
    faixa9_v DECIMAL(10,2) DEFAULT NULL,
    faixa10_d DECIMAL(10,2) DEFAULT NULL,
    faixa10_v DECIMAL(10,2) DEFAULT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_txentrega_chave_cliente (chave, id_cliente),
    KEY idx_txentrega_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO txentrega (
    chave, id_cliente,
    faixa1_d, faixa1_v, faixa2_d, faixa2_v, faixa3_d, faixa3_v,
    faixa4_d, faixa4_v, faixa5_d, faixa5_v, faixa6_d, faixa6_v,
    faixa7_d, faixa7_v, faixa8_d, faixa8_v, faixa9_d, faixa9_v,
    faixa10_d, faixa10_v
) VALUES (
    1, 1,
    3.00, 5.00, 5.00, 8.00, 8.00, 10.00,
    10.00, 12.00, 12.00, 15.00, 15.00, 18.00,
    18.00, 20.00, 20.00, 25.00, 25.00, 30.00,
    30.00, 35.00
);

-- =============================
-- TABELA: configuracao
-- =============================
CREATE TABLE IF NOT EXISTS configuracao (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    id_cliente INT NOT NULL,
    nromesa INT DEFAULT 100,
    servicomesa DECIMAL(10,2) DEFAULT 0,
    calculodistancia VARCHAR(10) DEFAULT 'Sim',
    imp_comandadelivery INT DEFAULT 1,
    marca_imp1 VARCHAR(100) DEFAULT NULL,
    marca_imp2 VARCHAR(100) DEFAULT NULL,
    marca_imp3 VARCHAR(100) DEFAULT NULL,
    marca_imp4 VARCHAR(100) DEFAULT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_configuracao_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO configuracao (chave, id_cliente, nromesa, servicomesa, calculodistancia, imp_comandadelivery)
VALUES (1, 1, 100, 0, 'Sim', 1);

-- =============================
-- TABELA: impressoras
-- =============================
CREATE TABLE IF NOT EXISTS impressoras (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nomedaimpressora VARCHAR(255) NOT NULL,
    imprenro TINYINT NOT NULL DEFAULT 0,
    id_cliente INT DEFAULT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================
-- TABELA: formapagamento
-- =============================
CREATE TABLE IF NOT EXISTS formapagamento (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    forma VARCHAR(100) NOT NULL,
    id_cliente INT NOT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_formapagamento_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================
-- TABELA: deliverypendente
-- =============================
CREATE TABLE IF NOT EXISTS deliverypendente (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nropedido INT NOT NULL,
    telefone VARCHAR(20) DEFAULT NULL,
    cep VARCHAR(10) DEFAULT NULL,
    nome VARCHAR(150) DEFAULT NULL,
    endereco VARCHAR(255) DEFAULT NULL,
    nrocasa VARCHAR(30) DEFAULT NULL,
    complemento VARCHAR(255) DEFAULT NULL,
    codigoproduto VARCHAR(50) DEFAULT NULL,
    produto VARCHAR(255) DEFAULT NULL,
    preco DECIMAL(10,2) DEFAULT 0,
    quantidade DECIMAL(10,3) DEFAULT 0,
    classe VARCHAR(100) DEFAULT NULL,
    entregador VARCHAR(150) DEFAULT NULL,
    cliente VARCHAR(255) DEFAULT NULL,
    id_cliente INT NOT NULL,
    formapagamento VARCHAR(100) DEFAULT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_delivery_nropedido (nropedido),
    KEY idx_delivery_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================
-- TABELA: comanda
-- =============================
CREATE TABLE IF NOT EXISTS comanda (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nropedido INT NOT NULL,
    telefone VARCHAR(20) DEFAULT NULL,
    cep VARCHAR(10) DEFAULT NULL,
    nome VARCHAR(150) DEFAULT NULL,
    endereco VARCHAR(255) DEFAULT NULL,
    nrocasa VARCHAR(30) DEFAULT NULL,
    complemento VARCHAR(255) DEFAULT NULL,
    codigoproduto VARCHAR(50) DEFAULT NULL,
    produto VARCHAR(255) DEFAULT NULL,
    preco DECIMAL(10,2) DEFAULT 0,
    quantidade DECIMAL(10,3) DEFAULT 0,
    classe VARCHAR(100) DEFAULT NULL,
    entregador VARCHAR(150) DEFAULT NULL,
    cliente VARCHAR(255) DEFAULT NULL,
    id_cliente INT NOT NULL,
    formapagamento VARCHAR(100) DEFAULT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_comanda_nropedido (nropedido),
    KEY idx_comanda_telefone (telefone),
    KEY idx_comanda_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================
-- TABELA: canceladas
-- =============================
CREATE TABLE IF NOT EXISTS canceladas (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nropedido INT NOT NULL,
    cliente VARCHAR(255) DEFAULT NULL,
    telefone VARCHAR(20) DEFAULT NULL,
    nome VARCHAR(150) DEFAULT NULL,
    cep VARCHAR(10) DEFAULT NULL,
    endereco VARCHAR(255) DEFAULT NULL,
    nrocasa VARCHAR(30) DEFAULT NULL,
    complemento VARCHAR(255) DEFAULT NULL,
    codigoproduto VARCHAR(50) DEFAULT NULL,
    produto VARCHAR(255) DEFAULT NULL,
    preco DECIMAL(10,2) DEFAULT 0,
    quantidade DECIMAL(10,3) DEFAULT 0,
    classe VARCHAR(100) DEFAULT NULL,
    entregador VARCHAR(150) DEFAULT NULL,
    id_cliente INT NOT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_canceladas_nropedido (nropedido),
    KEY idx_canceladas_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================
-- TABELA: liquidada
-- =============================
CREATE TABLE IF NOT EXISTS liquidada (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nropedido INT NOT NULL,
    telefone VARCHAR(20) DEFAULT NULL,
    cep VARCHAR(10) DEFAULT NULL,
    nome VARCHAR(150) DEFAULT NULL,
    endereco VARCHAR(255) DEFAULT NULL,
    nrocasa VARCHAR(30) DEFAULT NULL,
    complemento VARCHAR(255) DEFAULT NULL,
    codigoproduto VARCHAR(50) DEFAULT NULL,
    produto VARCHAR(255) DEFAULT NULL,
    preco DECIMAL(10,2) DEFAULT 0,
    quantidade DECIMAL(10,3) DEFAULT 0,
    classe VARCHAR(100) DEFAULT NULL,
    entregador VARCHAR(150) DEFAULT NULL,
    cliente VARCHAR(255) DEFAULT NULL,
    id_cliente INT NOT NULL,
    formapagamento VARCHAR(100) DEFAULT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_liquidada_nropedido (nropedido),
    KEY idx_liquidada_id_cliente (id_cliente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================
-- TABELA: mesa
-- =============================
CREATE TABLE IF NOT EXISTS mesa (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    id INT DEFAULT NULL,
    mesanro INT DEFAULT NULL,
    nropedido INT DEFAULT NULL,
    telefone VARCHAR(20) DEFAULT NULL,
    cep VARCHAR(10) DEFAULT NULL,
    nome VARCHAR(150) DEFAULT NULL,
    endereco VARCHAR(255) DEFAULT NULL,
    nrocasa VARCHAR(30) DEFAULT NULL,
    complemento VARCHAR(255) DEFAULT NULL,
    codigoproduto VARCHAR(50) DEFAULT NULL,
    produto VARCHAR(255) DEFAULT NULL,
    preco DECIMAL(10,2) DEFAULT 0,
    quantidade DECIMAL(10,3) DEFAULT 0,
    classe VARCHAR(100) DEFAULT NULL,
    entregador VARCHAR(150) DEFAULT NULL,
    cliente VARCHAR(255) DEFAULT NULL,
    id_cliente INT NOT NULL,
    nrolancamento BIGINT DEFAULT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_mesa_mesanro (mesanro),
    KEY idx_mesa_nropedido (nropedido),
    KEY idx_mesa_id_cliente (id_cliente),
    KEY idx_mesa_nrolancamento (nrolancamento)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mantem a coluna id sincronizada com chave para compatibilidade de consultas antigas.
DROP TRIGGER IF EXISTS trg_mesa_sync_id_insert;
DELIMITER $$
CREATE TRIGGER trg_mesa_sync_id_insert
AFTER INSERT ON mesa
FOR EACH ROW
BEGIN
    UPDATE mesa
    SET id = chave
    WHERE chave = NEW.chave AND id IS NULL;
END $$
DELIMITER ;

DROP TRIGGER IF EXISTS trg_mesa_sync_id_update;
DELIMITER $$
CREATE TRIGGER trg_mesa_sync_id_update
BEFORE UPDATE ON mesa
FOR EACH ROW
BEGIN
    IF NEW.id IS NULL THEN
        SET NEW.id = NEW.chave;
    END IF;
END $$
DELIMITER ;
