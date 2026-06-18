-- Criar tabela de usuários para login
CREATE TABLE IF NOT EXISTS usuarios (
    chave INT AUTO_INCREMENT PRIMARY KEY,
    usuario VARCHAR(100) NOT NULL UNIQUE,
    senha VARCHAR(255) NOT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Inserir usuário padrão (admin/admin)
INSERT IGNORE INTO usuarios (usuario, senha) VALUES ('admin', 'admin');
