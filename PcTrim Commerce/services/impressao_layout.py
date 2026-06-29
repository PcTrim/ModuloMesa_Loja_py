"""Metadados para cabeçalho de impressão de pedidos."""
from __future__ import annotations

from datetime import datetime

from database import conectar


def _normalize_origem(origem: str | None) -> str:
    o = str(origem or "DELIVERY").strip().upper()
    if o in ("CASA", "DELIVERY", "BALCAO", "MESA", "PREPARO"):
        return o
    if o == "BALCÃO":
        return "BALCAO"
    return "DELIVERY"


def get_impressao_meta(id_cliente: int, nropedido: int, origem: str | None, usuario_sessao: str | None) -> dict:
    """Retorna data_criacao e atendente do pedido para impressão."""
    origem_db = _normalize_origem(origem)
    if origem_db == "CASA":
        origem_db = "DELIVERY"

    fallback_atendente = str(usuario_sessao or "").strip() or None
    now_iso = datetime.now().replace(microsecond=0).isoformat()

    if not id_cliente or nropedido <= 0:
        return {
            "data_criacao": now_iso,
            "atendente": fallback_atendente,
            "atendente_chave": None,
        }

    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT MIN(d.data_criacao) AS data_criacao,
                   MIN(d.chave) AS chave_ref
            FROM pedido_diarios d
            WHERE d.id_cliente = %s
              AND d.nropedido = %s
              AND d.origem = %s
              AND UPPER(COALESCE(d.status_pedido, '')) <> 'ITEM_REMOVIDO'
            """,
            (int(id_cliente), int(nropedido), origem_db),
        )
        row = cur.fetchone() or {}
        data_criacao = row.get("data_criacao")
        chave_ref = row.get("chave_ref")

        atendente = fallback_atendente
        atendente_chave = None

        if chave_ref is not None:
            cur.execute(
                """
                SELECT d.cod_usuario, u.usuario AS login
                FROM pedido_diarios d
                LEFT JOIN usuarios u ON u.chave = d.cod_usuario AND u.id_cliente = d.id_cliente
                WHERE d.chave = %s
                LIMIT 1
                """,
                (int(chave_ref),),
            )
            row_u = cur.fetchone() or {}
            login = str(row_u.get("login") or "").strip()
            if login:
                atendente = login
            if row_u.get("cod_usuario") is not None:
                atendente_chave = int(row_u.get("cod_usuario"))

        if data_criacao is None:
            data_iso = now_iso
        elif hasattr(data_criacao, "isoformat"):
            data_iso = data_criacao.replace(microsecond=0).isoformat()
        else:
            data_iso = str(data_criacao)

        return {
            "data_criacao": data_iso,
            "atendente": atendente,
            "atendente_chave": atendente_chave,
        }
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
