"""Login autenticado no banco MySQL correspondente ao ambiente da loja."""
from __future__ import annotations

import mysql.connector

from config import Config
from database import TENANT_DB_SESSION_KEY, conectar_admin_optional
from models import AUTH_CREDENTIALS_INVALID_MSG, UsuarioAuthRow
from services.loja_ambiente import (
    AMBIENTE_HOMOLOGATION,
    AMBIENTE_PRODUCTION,
    fetch_loja_ambiente_for_cliente,
    normalize_ambiente,
)


class LoginAmbienteError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message = message
        self.status = status


def _fetch_user_row(cursor, usuario: str):
    row = None
    try:
        cursor.execute(
            """
            SELECT usuario, senha, id_cliente, funcao, ativo
            FROM usuarios WHERE usuario = %s LIMIT 1
            """,
            (usuario,),
        )
        row = cursor.fetchone()
    except mysql.connector.Error as col_err:
        if getattr(col_err, "errno", None) != 1054:
            raise
        try:
            cursor.execute(
                "SELECT usuario, senha, id_cliente, funcao FROM usuarios WHERE usuario = %s LIMIT 1",
                (usuario,),
            )
            row = cursor.fetchone()
        except mysql.connector.Error:
            cursor.execute(
                "SELECT usuario, senha, id_cliente FROM usuarios WHERE usuario = %s LIMIT 1",
                (usuario,),
            )
            row = cursor.fetchone()
    return row


def _lookup_user_in_target(target: str, usuario: str) -> dict | None:
    """Busca usuário em um banco; None se indisponível ou não encontrado."""
    if not Config.admin_db_configured(target):
        return None
    conn = None
    cur = None
    try:
        conn = conectar_admin_optional(target=target)
        if conn is None:
            return None
        cur = conn.cursor(dictionary=True)
        return _fetch_user_row(cur, usuario)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def locate_login_user(usuario: str) -> tuple[str, dict]:
    """
    Localiza usuário para autenticação; banco operacional = dadosloja.ambiente.
    Retorna (target_db, row_dict).
    """
    usuario = (usuario or "").strip()
    candidates: list[tuple[str, dict]] = []

    for target in (AMBIENTE_PRODUCTION, AMBIENTE_HOMOLOGATION):
        row = _lookup_user_in_target(target, usuario)
        if row:
            candidates.append((target, row))

    if not candidates:
        raise LoginAmbienteError(AUTH_CREDENTIALS_INVALID_MSG, status=401)

    id_cliente = candidates[0][1].get("id_cliente")
    target = fetch_loja_ambiente_for_cliente(id_cliente)

    if target == AMBIENTE_HOMOLOGATION and not Config.admin_db_configured(AMBIENTE_HOMOLOGATION):
        raise LoginAmbienteError(
            "Loja em homologação, mas o servidor ainda não tem acesso ao banco de testes. "
            "Contate o suporte.",
            status=503,
        )

    auth_row = None
    for cand_target, row in candidates:
        if cand_target == target:
            auth_row = row
            break
    if auth_row is None:
        auth_row = candidates[0][1]

    return target, auth_row


def bind_tenant_db_to_session(session, target: str) -> None:
    """Cache na sessão do banco derivado de dadosloja.ambiente (definido no login)."""
    session[TENANT_DB_SESSION_KEY] = normalize_ambiente(target)
    session.modified = True


def user_is_inactive(row) -> bool:
    if row is None or not isinstance(row, dict):
        return False
    ativo_val = row.get("ativo")
    return ativo_val is not None and int(ativo_val) == 0


def row_to_auth_user(row: dict) -> UsuarioAuthRow | None:
    return UsuarioAuthRow.from_db_row(row)
