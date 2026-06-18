-- Criação e configuração da tabela de impressoras
CREATE TABLE IF NOT EXISTS impressoras (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nomedaimpressora VARCHAR(255) NOT NULL,
    imprenro TINYINT NOT NULL DEFAULT 0
);

-- Defina aqui o nome EXATO da impressora. Exemplos:
-- Local: 'Bematech'
-- Compartilhada (UNC): '\\SERVIDOR\FilaCompartilhada'

-- Regra: manter apenas uma com imprenro=1 (ativa)
UPDATE impressoras SET imprenro = 0;

-- Insere ou atualiza a impressora ativa
INSERT INTO impressoras (nomedaimpressora, imprenro)
VALUES ('Bematech', 1);
