-- Script para criar tabela contadorpedido
-- Execute este script no MySQL antes de usar o sistema

USE novaloja;

CREATE TABLE IF NOT EXISTS contadorpedido (
    id INT PRIMARY KEY,
    contador INT NOT NULL DEFAULT 0
);

-- Insere o registro inicial se não existir
INSERT IGNORE INTO contadorpedido (id, contador) VALUES (1, 0);

-- Verifica o conteúdo
SELECT * FROM contadorpedido;
