"""Consultas read-only na base interna (clientes PcTrim)."""
from __future__ import annotations

from database import conectar_interno


def fetch_clientes_ativos() -> list[dict]:
    """Clientes com ValorMensal >= 1 na base interno.clientes."""
    conn = None
    cur = None
    try:
        conn = conectar_interno()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
                KeyChave AS id,
                Cliente AS cliente,
                Fantasia AS fantasia,
                cnpj AS documento
            FROM clientes
            WHERE COALESCE(ValorMensal, 0) >= 1
            ORDER BY KeyChave DESC
            """
        )
        return list(cur.fetchall() or [])
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def fetch_cliente_ativo_by_id(key_chave: int) -> dict | None:
    conn = None
    cur = None
    try:
        conn = conectar_interno()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
                KeyChave AS id,
                Cliente AS cliente,
                Fantasia AS fantasia,
                cnpj AS documento
            FROM clientes
            WHERE KeyChave = %s
              AND COALESCE(ValorMensal, 0) >= 1
            LIMIT 1
            """,
            (int(key_chave),),
        )
        return cur.fetchone()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
