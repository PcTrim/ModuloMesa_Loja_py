-- Menu Engineering Module Schema
-- Multi-tenant tables for cost and margin intelligence
-- All tables include client_id for multi-tenancy

-- Ingredients table
CREATE TABLE IF NOT EXISTS ingredients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    unit_type VARCHAR(50) NOT NULL COMMENT 'g, kg, unit, liter, ml, etc',
    current_cost_per_unit DECIMAL(10, 4) NOT NULL DEFAULT 0.0000,
    category VARCHAR(100) NOT NULL COMMENT 'protein, dairy, bakery, vegetables, etc',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_ingredient_client (name, client_id),
    INDEX idx_client_id (client_id),
    INDEX idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Ingredient price history table
CREATE TABLE IF NOT EXISTS ingredient_price_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    ingredient_id INT NOT NULL,
    cost_per_unit DECIMAL(10, 4) NOT NULL,
    source VARCHAR(255) NOT NULL COMMENT 'NF-e import, manual, etc',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_client_id (client_id),
    INDEX idx_ingredient_id (ingredient_id),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Ingredient categories table (custom categories per client)
CREATE TABLE IF NOT EXISTS ingredient_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_category_client (slug, client_id),
    INDEX idx_client_id (client_id),
    INDEX idx_slug (slug)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Recipes table
CREATE TABLE IF NOT EXISTS recipes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    product_id INT NOT NULL COMMENT 'Logical reference to existing product (read-only)',
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_client_id (client_id),
    INDEX idx_product_id (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Recipe ingredients table (junction)
CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    recipe_id INT NOT NULL,
    ingredient_id INT NOT NULL,
    quantity DECIMAL(10, 4) NOT NULL COMMENT 'Quantity in ingredient unit_type',
    INDEX idx_client_id (client_id),
    INDEX idx_recipe_id (recipe_id),
    INDEX idx_ingredient_id (ingredient_id),
    FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
