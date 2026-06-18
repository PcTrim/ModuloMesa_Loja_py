"""Mesa table queries scoped by tenant."""
from database import conectar


def fetch_mesa_recent_for_client(id_cliente, limit=100):
    conn = conectar()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT
            chave AS id,
            nropedido AS mesanro,
            UPPER(COALESCE(status_mesa, '')) AS status_mesa,
            produto,
            preco,
            quantidade,
            codigoproduto,
            classe,
            id_cliente,
            COALESCE(lancamento, nrolancamento) AS lancamento,
            COALESCE(lancamento, nrolancamento) AS nrolancamento,
            obs_item,
            dados_item
        FROM pedido_diarios
        WHERE origem = 'MESA'
          AND id_cliente = %s
          AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
          AND UPPER(COALESCE(status_mesa, '')) <> 'RECEBIDO'
        ORDER BY chave DESC
        LIMIT %s
        """,
        (id_cliente, limit),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows
