"""Consultas read-only de duplicatas na base interna."""
from __future__ import annotations

import mysql.connector

from database import conectar_interno


def fetch_resumo_duplicatas_cliente(cliente_id: int) -> dict | None:
    """
    Agregados de inadimplência para um ClienteID.
    Retorna None se Interno indisponível ou erro de conexão.
    """
    conn = None
    cur = None
    try:
        conn = conectar_interno()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
              MAX(CASE
                WHEN DATEDIFF(duplicatavencimento, CURDATE()) BETWEEN 0 AND 2
                THEN 1 ELSE 0 END) AS tem_a_vencer,
              MAX(CASE WHEN duplicatavencimento < CURDATE() THEN 1 ELSE 0 END) AS tem_vencidas,
              MAX(CASE
                WHEN duplicatavencimento < CURDATE()
                THEN DATEDIFF(CURDATE(), duplicatavencimento) END) AS dias_atraso_max,
              MAX(CASE
                WHEN duplicatavencimento < DATE_SUB(CURDATE(), INTERVAL 3 DAY)
                THEN 1 ELSE 0 END) AS bloqueado_venda
            FROM duplicatas
            WHERE id_cliente = %s
              AND liquidada NOT IN ('SIM', 'PRE')
            """,
            (int(cliente_id),),
        )
        row = cur.fetchone() or {}
        return {
            "tem_a_vencer": int(row.get("tem_a_vencer") or 0),
            "tem_vencidas": int(row.get("tem_vencidas") or 0),
            "dias_atraso_max": int(row.get("dias_atraso_max") or 0),
            "bloqueado_venda": int(row.get("bloqueado_venda") or 0),
        }
    except mysql.connector.Error:
        return None
    except Exception:
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
