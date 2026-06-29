"""Consultas de integridade pós-teste E2E."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))
from database import conectar

id_cliente = int(os.getenv("E2E_ID_CLIENTE", "1") or "1")
conn = conectar()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT contador FROM contadorpedido WHERE id_cliente=%s", (id_cliente,))
c = cur.fetchone()
cur.execute(
    """
    SELECT MAX(nropedido) AS mx
    FROM pedido_diarios
    WHERE id_cliente=%s AND origem IN ('BALCAO','DELIVERY')
    """,
    (id_cliente,),
)
m = cur.fetchone()
cur.execute(
    """
    SELECT DISTINCT nropedido, origem
    FROM pedido_diarios
    WHERE id_cliente=%s AND origem IN ('BALCAO','DELIVERY')
    ORDER BY nropedido DESC
    LIMIT 10
    """,
    (id_cliente,),
)
rows = cur.fetchall()
contador = int(c["contador"]) if c else 0
max_nro = int(m["mx"] or 0) if m else 0
print("=== INTEGRIDADE DB id_cliente=%s ===" % id_cliente)
print("contador:", contador)
print("max_nropedido BALCAO/DELIVERY:", max_nro)
print("contador >= max:", contador >= max_nro)
print("ultimos pedidos (distinct):", rows)
cur.close()
conn.close()
