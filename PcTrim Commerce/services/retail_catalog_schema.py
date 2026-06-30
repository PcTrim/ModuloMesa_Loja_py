"""Schema idempotente do catálogo retail (categoria, subcategoria, produto_retail)."""
from __future__ import annotations

import traceback
from pathlib import Path

from database import conectar

_SQL_FILE = Path(__file__).resolve().parent.parent / "deploy" / "sql" / "retail_catalog_v1.sql"


def _column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        LIMIT 1
        """,
        (table, column),
    )
    return cur.fetchone() is not None


def _index_exists(cur, table: str, index_name: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s
        LIMIT 1
        """,
        (table, index_name),
    )
    return cur.fetchone() is not None


def _fk_exists(cur, table: str, constraint_name: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND CONSTRAINT_NAME = %s
          AND CONSTRAINT_TYPE = 'FOREIGN KEY'
        LIMIT 1
        """,
        (table, constraint_name),
    )
    return cur.fetchone() is not None


def _ensure_categoria_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS categoria (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_cliente INT NOT NULL,
            nome VARCHAR(120) NOT NULL,
            ordem_exibicao INT NOT NULL DEFAULT 0,
            ativo TINYINT(1) NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_categoria_cliente_nome (id_cliente, nome),
            KEY idx_categoria_id_cliente (id_cliente),
            KEY idx_categoria_cliente_ativo_ordem (id_cliente, ativo, ordem_exibicao)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def _ensure_subcategoria_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS subcategoria (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_cliente INT NOT NULL,
            categoria_id INT NOT NULL,
            nome VARCHAR(120) NOT NULL,
            ordem_exibicao INT NOT NULL DEFAULT 0,
            ativo TINYINT(1) NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_subcategoria_cliente_cat_nome (id_cliente, categoria_id, nome),
            KEY idx_subcategoria_id_cliente (id_cliente),
            KEY idx_subcategoria_categoria (categoria_id),
            KEY idx_subcategoria_cliente_ativo_ordem (id_cliente, ativo, ordem_exibicao)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    if not _fk_exists(cur, "subcategoria", "fk_subcategoria_categoria"):
        cur.execute(
            """
            ALTER TABLE subcategoria
            ADD CONSTRAINT fk_subcategoria_categoria
            FOREIGN KEY (categoria_id) REFERENCES categoria(id)
            ON UPDATE CASCADE ON DELETE RESTRICT
            """
        )


def _ensure_produtos_retail_columns(cur) -> None:
    if not _column_exists(cur, "produtos", "category_id"):
        cur.execute(
            "ALTER TABLE produtos ADD COLUMN category_id INT NULL DEFAULT NULL AFTER id_cliente"
        )
    if not _column_exists(cur, "produtos", "subcategory_id"):
        cur.execute(
            "ALTER TABLE produtos ADD COLUMN subcategory_id INT NULL DEFAULT NULL AFTER category_id"
        )
    if not _index_exists(cur, "produtos", "idx_produtos_category_id"):
        cur.execute("ALTER TABLE produtos ADD KEY idx_produtos_category_id (category_id)")
    if not _index_exists(cur, "produtos", "idx_produtos_subcategory_id"):
        cur.execute("ALTER TABLE produtos ADD KEY idx_produtos_subcategory_id (subcategory_id)")
    if not _fk_exists(cur, "produtos", "fk_produtos_category"):
        cur.execute(
            """
            ALTER TABLE produtos
            ADD CONSTRAINT fk_produtos_category
            FOREIGN KEY (category_id) REFERENCES categoria(id)
            ON UPDATE CASCADE ON DELETE SET NULL
            """
        )
    if not _fk_exists(cur, "produtos", "fk_produtos_subcategory"):
        cur.execute(
            """
            ALTER TABLE produtos
            ADD CONSTRAINT fk_produtos_subcategory
            FOREIGN KEY (subcategory_id) REFERENCES subcategoria(id)
            ON UPDATE CASCADE ON DELETE SET NULL
            """
        )


def _ensure_produto_retail_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS produto_retail (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_cliente INT NOT NULL,
            product_id INT NOT NULL COMMENT 'FK produtos.chave',
            nome_vitrine VARCHAR(200) NULL,
            descricao_vitrine TEXT NULL,
            preco_varejo DECIMAL(10,2) NULL,
            preco_atacado DECIMAL(10,2) NULL,
            comissao DECIMAL(5,2) NULL DEFAULT NULL,
            estoque DECIMAL(12,3) NOT NULL DEFAULT 0,
            permite_venda_sem_estoque TINYINT(1) NOT NULL DEFAULT 0,
            destaque TINYINT(1) NOT NULL DEFAULT 0,
            ativo TINYINT(1) NOT NULL DEFAULT 1,
            ordem_exibicao INT NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_produto_retail_product (product_id),
            KEY idx_produto_retail_id_cliente (id_cliente),
            KEY idx_produto_retail_vitrine (id_cliente, ativo, destaque, ordem_exibicao)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    if not _fk_exists(cur, "produto_retail", "fk_produto_retail_product"):
        cur.execute(
            """
            ALTER TABLE produto_retail
            ADD CONSTRAINT fk_produto_retail_product
            FOREIGN KEY (product_id) REFERENCES produtos(chave)
            ON UPDATE CASCADE ON DELETE CASCADE
            """
        )


def ensure_retail_catalog_schema() -> None:
    """Cria estrutura retail idempotente. Não altera dados existentes."""
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        _ensure_categoria_table(cur)
        _ensure_subcategoria_table(cur)
        _ensure_produtos_retail_columns(cur)
        _ensure_produto_retail_table(cur)
        conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        print("[RETAIL CATALOG SCHEMA ERRO]", e, flush=True)
        traceback.print_exc()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def sql_file_path() -> Path:
    """Caminho do script SQL para execução manual em produção."""
    return _SQL_FILE
