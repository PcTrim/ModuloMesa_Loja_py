"""Consultas de integridade pós-teste E2E."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.test_env import aplicar_env_teste, conectar_teste  # noqa: E402

aplicar_env_teste()

id_cliente = int(os.getenv("E2E_ID_CLIENTE", "1") or "1")
conn = conectar_teste()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT contador FROM contadorpedido WHERE id_cliente=%s", (id_cliente,))
print("contador", cur.fetchone())
cur.execute(
    """
    SELECT MAX(nropedido) AS max_nro FROM pedido_diarios
    WHERE id_cliente=%s AND origem IN ('BALCAO','DELIVERY')
    """,
    (id_cliente,),
)
print("max_nro", cur.fetchone())
cur.execute(
    """
    SELECT COUNT(*) AS n FROM pedido_diarios
    WHERE id_cliente=%s AND origem IN ('BALCAO','DELIVERY')
    """,
    (id_cliente,),
)
print("linhas", cur.fetchone())
print("=== INTEGRIDADE DB id_cliente=%s ===" % id_cliente)
cur.close()
conn.close()
