-- Criação da tabela dadosloja para armazenar informações da loja

DROP TABLE IF EXISTS dadosloja;

CREATE TABLE dadosloja (
    chave INT PRIMARY KEY,
    nome VARCHAR(255) NOT NULL,
    endereco TEXT NOT NULL,
    bairro VARCHAR(100),
    cidade VARCHAR(100),
    cep VARCHAR(10),
    telefone VARCHAR(20) NOT NULL,
    cnpj VARCHAR(20),
    latitude VARCHAR(20) NOT NULL,
    longitude VARCHAR(20) NOT NULL,
    ddd VARCHAR(3),
    tipo_negocio VARCHAR(20) NOT NULL DEFAULT 'restaurante',
    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Inserir dados padrão (pode ser atualizado pelo formulário)
INSERT INTO dadosloja (chave, nome, endereco, bairro, cidade, cep, telefone, cnpj, latitude, longitude, ddd)
VALUES (
    1, 
    'Minha Loja', 
    'Praça São Pedro', 
    'Aerolândia', 
    'Picos - PI',
    '64600-000',
    '(89) 99999-9999', 
    '', 
    '-7.0793693', 
    '-41.4687021',
    '89'
);
