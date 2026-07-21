"""Helpers para separar catálogo restaurante (classificacao) de varejo (categoria)."""


def produto_tem_coluna_category_id(cur) -> bool:
    try:
        cur.execute("SHOW COLUMNS FROM produtos LIKE 'category_id'")
        return cur.fetchone() is not None
    except Exception:
        return False


def sql_filtro_produto_restaurante(alias: str = "p") -> str:
    """SQL AND-clauses: produto pertence ao catálogo restaurante, não varejo."""
    a = alias.strip() or "p"
    return f"""
                  AND {a}.category_id IS NULL
                  AND UPPER(TRIM(COALESCE({a}.classe, ''))) NOT IN (
                      SELECT UPPER(TRIM(nome)) FROM categoria WHERE id_cliente = %s
                  )"""


def contar_produtos_varejo_ocultos(cur, id_cliente) -> int:
    if not produto_tem_coluna_category_id(cur):
        return 0
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM produtos
        WHERE id_cliente = %s AND category_id IS NOT NULL
        """,
        (id_cliente,),
    )
    row = cur.fetchone()
    if isinstance(row, dict):
        return int(row.get("n") or 0)
    if row:
        return int(row[0] or 0)
    return 0
