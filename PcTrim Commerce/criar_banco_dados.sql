-- ======================================
-- SCRIPT DE CRIAÇÃO DO BANCO DE DADOS
-- Sistema Novaloja
-- ======================================

-- Criar banco de dados
CREATE DATABASE IF NOT EXISTS novaloja;
USE novaloja;

-- ======================================
-- TABELA: usuarios
-- ======================================
CREATE TABLE IF NOT EXISTS usuarios (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    usuario VARCHAR(100) NOT NULL UNIQUE,
    senha VARCHAR(255) NOT NULL,
    ativo TINYINT DEFAULT 1,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ======================================
-- TABELA: classificacao
-- ======================================
CREATE TABLE IF NOT EXISTS classificacao (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nomeclassificacao VARCHAR(100) NOT NULL UNIQUE,
    quantidadepartes INT,
    nrofoto INT,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ======================================
-- TABELA: produtos
-- ======================================
CREATE TABLE IF NOT EXISTS produtos (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    produto VARCHAR(150) NOT NULL,
    preco DECIMAL(10, 2) NOT NULL,
    classe INT,
    porkilo TINYINT DEFAULT 0,
    impressora VARCHAR(100),
    cfop VARCHAR(10),
    ncm VARCHAR(20),
    display TINYINT DEFAULT 0,
    vendaliberada TINYINT DEFAULT 1,
    descricao TEXT,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (classe) REFERENCES classificacao(chave)
);

-- ======================================
-- TABELA: entregador
-- ======================================
CREATE TABLE IF NOT EXISTS entregador (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    telefone VARCHAR(20),
    endereco VARCHAR(255),
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ======================================
-- TABELA: cliente
-- ======================================
CREATE TABLE IF NOT EXISTS cliente (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(150) NOT NULL,
    telefone VARCHAR(20),
    email VARCHAR(100),
    endereco VARCHAR(255),
    bairro VARCHAR(100),
    cidade VARCHAR(100),
    estado VARCHAR(2),
    cep VARCHAR(10),
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ======================================
-- TABELA: pedido
-- ======================================
CREATE TABLE IF NOT EXISTS pedido (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    numero_pedido INT UNIQUE,
    cliente_chave INT NOT NULL,
    data_pedido TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total DECIMAL(10, 2),
    taxa_entrega DECIMAL(10, 2) DEFAULT 0,
    observacoes TEXT,
    status VARCHAR(50) DEFAULT 'aberto',
    FOREIGN KEY (cliente_chave) REFERENCES cliente(chave)
);

-- ======================================
-- TABELA: pedido_item
-- ======================================
CREATE TABLE IF NOT EXISTS pedido_item (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    pedido_chave INT NOT NULL,
    produto_chave INT NOT NULL,
    quantidade DECIMAL(10, 3),
    preco_unitario DECIMAL(10, 2),
    subtotal DECIMAL(10, 2),
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pedido_chave) REFERENCES pedido(chave),
    FOREIGN KEY (produto_chave) REFERENCES produtos(chave)
);

-- ======================================
-- TABELA: contadorpedido
-- ======================================
CREATE TABLE IF NOT EXISTS contadorpedido (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    numero_atual INT DEFAULT 1,
    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ======================================
-- TABELA: impressoras
-- ======================================
CREATE TABLE IF NOT EXISTS impressoras (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nome_impressora VARCHAR(100) NOT NULL,
    tipo VARCHAR(50),
    ativa TINYINT DEFAULT 1,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ======================================
-- TABELA: deliverypendente
-- ======================================
CREATE TABLE IF NOT EXISTS deliverypendente (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    pedido_chave INT NOT NULL,
    entregador_chave INT,
    status_entrega VARCHAR(50) DEFAULT 'pendente',
    data_agendamento DATETIME,
    data_entrega DATETIME,
    observacoes TEXT,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pedido_chave) REFERENCES pedido(chave),
    FOREIGN KEY (entregador_chave) REFERENCES entregador(chave)
);

-- ======================================
-- TABELA: formadecobrar
-- ======================================
CREATE TABLE IF NOT EXISTS formadecobrar (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    nome_forma VARCHAR(100) NOT NULL,
    tipo VARCHAR(50),
    ativa TINYINT DEFAULT 1,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ======================================
-- ÍNDICES PARA OTIMIZAÇÃO
-- ======================================
CREATE INDEX idx_produtos_classe ON produtos(classe);
CREATE INDEX idx_pedido_cliente ON pedido(cliente_chave);
CREATE INDEX idx_pedido_item_pedido ON pedido_item(pedido_chave);
CREATE INDEX idx_pedido_item_produto ON pedido_item(produto_chave);
CREATE INDEX idx_cliente_telefone ON cliente(telefone);
CREATE INDEX idx_deliverypendente_pedido ON deliverypendente(pedido_chave);
CREATE INDEX idx_deliverypendente_entregador ON deliverypendente(entregador_chave);

-- ======================================
-- DADOS INICIAIS
-- ======================================

-- Inserir usuário padrão
INSERT INTO usuarios (usuario, senha, ativo) VALUES ('admin', 'admin123', 1);

-- Inserir contador de pedido
INSERT INTO contadorpedido (numero_atual) VALUES (1);

-- Inserir classificações padrão
INSERT INTO classificacao (nomeclassificacao, quantidadepartes, nrofoto) VALUES 
('PIZZA', 4, 1),
('ESFIHA', 1, 2),
('BEBIDA', 1, 3),
('LANCHE', 1, 4);

-- ======================================
-- FIM DO SCRIPT
-- ======================================
