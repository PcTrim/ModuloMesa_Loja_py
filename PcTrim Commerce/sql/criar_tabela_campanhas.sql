CREATE TABLE IF NOT EXISTS campanhas (
  id INT AUTO_INCREMENT PRIMARY KEY,
  id_cliente INT NOT NULL,
  nome VARCHAR(120) NOT NULL,
  tipo ENUM('desconto_percentual', 'desconto_valor', 'frete_gratis', 'brinde') NOT NULL,
  valor_beneficio DECIMAL(12, 2) NULL,
  condicao_valor_minimo DECIMAL(12, 2) NULL,
  aplica_em ENUM('todos', 'produtos', 'categorias') NOT NULL DEFAULT 'todos',
  produtos_ids TEXT NULL,
  categorias_ids TEXT NULL,
  ativo TINYINT(1) NOT NULL DEFAULT 1,
  data_inicio DATETIME NULL,
  data_fim DATETIME NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_campanhas_cliente (id_cliente, ativo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
