-- Execute no MySQL do servidor (phpMyAdmin, mysql CLI ou painel Hostinger).
-- Ajuste nomes e senha antes de rodar.

CREATE DATABASE IF NOT EXISTS loja2001
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'loja_app'@'localhost' IDENTIFIED BY 'SUA_SENHA_FORTE';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP
  ON loja2001.* TO 'loja_app'@'localhost';
FLUSH PRIVILEGES;

-- Depois importe a estrutura/dados:
--   mysql -u loja_app -p loja2001 < criar_banco_loja2001_completo.sql
-- ou envie o dump da homologação via FileZilla e importe no painel.
