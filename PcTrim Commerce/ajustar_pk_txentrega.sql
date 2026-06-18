-- Ajusta PRIMARY KEY da tabela txentrega para permitir múltiplos clientes
-- Remove PRIMARY KEY de 'chave' e cria PRIMARY KEY composta (chave, id_cliente)

USE loja2001;

-- Remove a PRIMARY KEY atual
ALTER TABLE txentrega DROP PRIMARY KEY;

-- Adiciona PRIMARY KEY composta (chave, id_cliente)
ALTER TABLE txentrega ADD PRIMARY KEY (chave, id_cliente);

-- Verifica a estrutura
DESCRIBE txentrega;
