"""Metadados para cabeçalho de impressão de pedidos."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database import conectar

_TZ_BR = ZoneInfo("America/Sao_Paulo")


def _normalize_origem(origem: str | None) -> str:
    o = str(origem or "DELIVERY").strip().upper()
    if o in ("CASA", "DELIVERY", "BALCAO", "MESA", "PREPARO"):
        return o
    if o == "BALCÃO":
        return "BALCAO"
    return "DELIVERY"


def _to_sao_paulo(dt: datetime | None) -> datetime:
    """Converte datetime para America/Sao_Paulo. Naive = UTC (VPS Hostinger)."""
    if dt is None:
        return datetime.now(_TZ_BR).replace(microsecond=0)
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_TZ_BR).replace(microsecond=0)


def _format_meta_datetime(dt: datetime | None) -> tuple[str, str]:
    br = _to_sao_paulo(dt)
    data_iso = br.isoformat()
    data_hora = br.strftime("%d/%m/%Y %H:%M")
    return data_iso, data_hora


def get_impressao_meta(id_cliente: int, nropedido: int, origem: str | None, usuario_sessao: str | None) -> dict:
    """Retorna data_criacao e atendente do pedido para impressão."""
    origem_db = _normalize_origem(origem)
    if origem_db == "CASA":
        origem_db = "DELIVERY"

    fallback_atendente = str(usuario_sessao or "").strip() or None
    now_iso, now_hora = _format_meta_datetime(None)

    if not id_cliente or nropedido <= 0:
        return {
            "data_criacao": now_iso,
            "data_hora": now_hora,
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
            data_iso, data_hora = now_iso, now_hora
        elif hasattr(data_criacao, "isoformat"):
            data_iso, data_hora = _format_meta_datetime(data_criacao)
        else:
            try:
                parsed = datetime.fromisoformat(str(data_criacao).replace(" ", "T"))
                data_iso, data_hora = _format_meta_datetime(parsed)
            except ValueError:
                data_iso, data_hora = now_iso, now_hora

        return {
            "data_criacao": data_iso,
            "data_hora": data_hora,
            "atendente": atendente,
            "atendente_chave": atendente_chave,
        }
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
