import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from database import conectar

conn = conectar()
cur = conn.cursor(dictionary=True)

checks = []

cur.execute("SHOW TABLES LIKE 'categoria'")
checks.append(("categoria", cur.fetchone() is not None))

cur.execute("SHOW TABLES LIKE 'subcategoria'")
checks.append(("subcategoria", cur.fetchone() is not None))

cur.execute("SHOW TABLES LIKE 'produto_retail'")
checks.append(("produto_retail", cur.fetchone() is not None))

cur.execute("SHOW COLUMNS FROM produtos LIKE 'category_id'")
checks.append(("produtos.category_id", cur.fetchone() is not None))

cur.execute("SHOW COLUMNS FROM produtos LIKE 'subcategory_id'")
checks.append(("produtos.subcategory_id", cur.fetchone() is not None))

cur.execute("SELECT COUNT(*) AS n FROM produtos WHERE category_id IS NOT NULL")
checks.append(("produtos com category_id preenchido = 0", cur.fetchone()["n"] == 0))

cur.execute("SELECT COUNT(*) AS n FROM produto_retail")
produto_retail_count = cur.fetchone()["n"]

cur.execute(
    """
    SELECT CONSTRAINT_NAME, TABLE_NAME, REFERENCED_TABLE_NAME
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = DATABASE()
      AND REFERENCED_TABLE_NAME IS NOT NULL
      AND TABLE_NAME IN ('subcategoria','produtos','produto_retail')
    ORDER BY TABLE_NAME, CONSTRAINT_NAME
    """
)
fks = cur.fetchall()

print("=== VERIFICACAO POS-MIGRACAO ===")
for name, ok in checks:
    print(f"  [{'OK' if ok else 'FALHA'}] {name}")
print(f"  [INFO] linhas produto_retail: {produto_retail_count}")
print("FKs retail:")
for row in fks:
    print(
        f"  - {row['TABLE_NAME']}.{row['CONSTRAINT_NAME']} -> {row['REFERENCED_TABLE_NAME']}"
    )

cur.close()
conn.close()
