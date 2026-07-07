"""CRUD de usuários da loja (tabela usuarios, filtrado por id_cliente)."""
from __future__ import annotations

import re

import mysql.connector

from database import conectar
from models import normalize_funcao
from services.passwords import hash_password

_LOGIN_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,50}$")


class UsuariosLojaError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _normalize_login(usuario: str) -> str:
    return str(usuario or "").strip().lower()


def _validate_login(usuario: str) -> str:
    login = _normalize_login(usuario)
    if not login:
        raise UsuariosLojaError("Login é obrigatório.")
    if not _LOGIN_RE.match(login):
        raise UsuariosLojaError(
            "Login inválido. Use 3–50 caracteres: letras, números, ponto, hífen ou sublinhado."
        )
    return login


def _validate_senha(senha: str, *, required: bool = True) -> str:
    s = str(senha or "")
    if not s:
        if required:
            raise UsuariosLojaError("Senha é obrigatória.")
        return ""
    if len(s) < 4:
        raise UsuariosLojaError("Senha deve ter no mínimo 4 caracteres.")
    return s


def _normalize_whatsapp(whatsapp: str | None) -> str:
    return "".join(ch for ch in str(whatsapp or "") if ch.isdigit())


def insert_usuario_row(
    cur,
    usuario: str,
    senha_hash: str,
    id_cliente: int,
    funcao: str = "gerente",
    ativo: int = 1,
    whatsapp: str | None = None,
) -> None:
    """INSERT em usuarios com fallback se colunas funcao/ativo/whatsapp não existirem."""
    funcao = normalize_funcao(funcao)
    wa = _normalize_whatsapp(whatsapp).strip() or ""
    try:
        cur.execute(
            """
            INSERT INTO usuarios (usuario, senha, id_cliente, funcao, ativo, whatsapp)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (usuario, senha_hash, id_cliente, funcao, int(ativo), wa),
        )
    except mysql.connector.Error as e:
        if getattr(e, "errno", None) == 1054:
            try:
                cur.execute(
                    """
                    INSERT INTO usuarios (usuario, senha, id_cliente, funcao, ativo)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (usuario, senha_hash, id_cliente, funcao, int(ativo)),
                )
            except mysql.connector.Error:
                try:
                    cur.execute(
                        """
                        INSERT INTO usuarios (usuario, senha, id_cliente, funcao)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (usuario, senha_hash, id_cliente, funcao),
                    )
                except mysql.connector.Error:
                    cur.execute(
                        "INSERT INTO usuarios (usuario, senha, id_cliente) VALUES (%s, %s, %s)",
                        (usuario, senha_hash, id_cliente),
                    )
        elif getattr(e, "errno", None) == 1062:
            raise UsuariosLojaError(f"Login '{usuario}' já está em uso.", status=409) from e
        else:
            raise


def _fetch_usuario(cur, id_cliente: int, chave: int) -> dict | None:
    try:
        cur.execute(
            """
            SELECT chave, usuario, funcao, ativo, whatsapp, data_criacao
            FROM usuarios
            WHERE chave = %s AND id_cliente = %s
            LIMIT 1
            """,
            (chave, id_cliente),
        )
    except mysql.connector.Error as e:
        if getattr(e, "errno", None) != 1054:
            raise
        cur.execute(
            """
            SELECT chave, usuario, data_criacao
            FROM usuarios
            WHERE chave = %s AND id_cliente = %s
            LIMIT 1
            """,
            (chave, id_cliente),
        )
    row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        row.setdefault("funcao", "gerente")
        row.setdefault("ativo", 1)
        row.setdefault("whatsapp", None)
        return row
    return {
        "chave": row[0],
        "usuario": row[1],
        "funcao": row[2] if len(row) > 4 else "gerente",
        "ativo": row[3] if len(row) > 4 else 1,
        "data_criacao": row[-1],
    }


def _count_gerentes_ativos(cur, id_cliente: int, exclude_chave: int | None = None) -> int:
    try:
        if exclude_chave is not None:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM usuarios
                WHERE id_cliente = %s AND funcao = 'gerente' AND ativo = 1 AND chave <> %s
                """,
                (id_cliente, exclude_chave),
            )
        else:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM usuarios
                WHERE id_cliente = %s AND funcao = 'gerente' AND ativo = 1
                """,
                (id_cliente,),
            )
    except mysql.connector.Error as e:
        if getattr(e, "errno", None) != 1054:
            raise
        if exclude_chave is not None:
            cur.execute(
                """
                SELECT COUNT(*) AS n FROM usuarios
                WHERE id_cliente = %s AND chave <> %s
                """,
                (id_cliente, exclude_chave),
            )
        else:
            cur.execute(
                "SELECT COUNT(*) AS n FROM usuarios WHERE id_cliente = %s",
                (id_cliente,),
            )
    row = cur.fetchone() or {}
    if isinstance(row, dict):
        return int(row.get("n") or 0)
    return int(row[0] if row else 0)


def list_usuarios(id_cliente: int) -> list[dict]:
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                """
                SELECT chave, usuario, funcao, ativo, whatsapp, data_criacao
                FROM usuarios
                WHERE id_cliente = %s
                ORDER BY usuario
                """,
                (id_cliente,),
            )
        except mysql.connector.Error as e:
            if getattr(e, "errno", None) != 1054:
                raise
            cur.execute(
                """
                SELECT chave, usuario, data_criacao
                FROM usuarios
                WHERE id_cliente = %s
                ORDER BY usuario
                """,
                (id_cliente,),
            )
        rows = cur.fetchall() or []
        out = []
        for r in rows:
            out.append(
                {
                    "chave": r.get("chave"),
                    "usuario": r.get("usuario"),
                    "funcao": normalize_funcao(r.get("funcao")),
                    "ativo": int(r.get("ativo") if r.get("ativo") is not None else 1),
                    "whatsapp": r.get("whatsapp") or "",
                    "data_criacao": (
                        r.get("data_criacao").isoformat()
                        if hasattr(r.get("data_criacao"), "isoformat")
                        else r.get("data_criacao")
                    ),
                }
            )
        return out
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def create_usuario(id_cliente: int, usuario: str, senha: str, funcao: str, whatsapp: str | None = None) -> dict:
    login = _validate_login(usuario)
    senha_plain = _validate_senha(senha, required=True)
    funcao_norm = normalize_funcao(funcao)

    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT 1 FROM usuarios WHERE usuario = %s LIMIT 1", (login,))
        if cur.fetchone():
            raise UsuariosLojaError(f"Login '{login}' já está em uso.", status=409)

        senha_hash = hash_password(senha_plain)
        insert_usuario_row(cur, login, senha_hash, id_cliente, funcao_norm, 1, whatsapp)
        conn.commit()
        chave = cur.lastrowid
        return {
            "chave": chave,
            "usuario": login,
            "funcao": funcao_norm,
            "ativo": 1,
            "whatsapp": _normalize_whatsapp(whatsapp).strip() or "",
        }
    except UsuariosLojaError:
        if conn:
            conn.rollback()
        raise
    except mysql.connector.Error as e:
        if conn:
            conn.rollback()
        if getattr(e, "errno", None) == 1062:
            raise UsuariosLojaError(f"Login '{login}' já está em uso.", status=409) from e
        raise UsuariosLojaError(f"Erro no banco de dados: {e}", status=500) from e
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def update_usuario(
    id_cliente: int,
    chave: int,
    *,
    funcao: str | None = None,
    ativo: int | None = None,
    senha: str | None = None,
    whatsapp: str | None = None,
    usuario_logado: str | None = None,
) -> dict:
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        row = _fetch_usuario(cur, id_cliente, chave)
        if not row:
            raise UsuariosLojaError("Usuário não encontrado nesta loja.", status=404)

        login_alvo = str(row.get("usuario") or "")
        funcao_atual = normalize_funcao(row.get("funcao"))
        ativo_atual = int(row.get("ativo") if row.get("ativo") is not None else 1)

        funcao_nova = normalize_funcao(funcao) if funcao is not None else funcao_atual
        ativo_novo = int(ativo) if ativo is not None else ativo_atual

        if ativo_novo not in (0, 1):
            raise UsuariosLojaError("Status ativo inválido.")

        if usuario_logado and login_alvo == str(usuario_logado).strip():
            if ativo_novo == 0:
                raise UsuariosLojaError("Você não pode desativar o seu próprio usuário.")
            if funcao_nova != "gerente" and funcao_atual == "gerente":
                raise UsuariosLojaError("Você não pode remover seu próprio perfil de gerente.")

        if funcao_atual == "gerente" and (funcao_nova != "gerente" or ativo_novo == 0):
            restantes = _count_gerentes_ativos(cur, id_cliente, exclude_chave=chave)
            if restantes < 1 and funcao_nova != "gerente":
                raise UsuariosLojaError("A loja precisa de pelo menos um gerente ativo.")
            if restantes < 1 and ativo_novo == 0:
                raise UsuariosLojaError("Não é possível desativar o último gerente ativo da loja.")

        senha_hash = None
        if senha is not None and str(senha).strip():
            senha_hash = hash_password(_validate_senha(senha, required=True))

        sets = []
        params = []
        if funcao is not None:
            sets.append("funcao = %s")
            params.append(funcao_nova)
        if ativo is not None:
            sets.append("ativo = %s")
            params.append(ativo_novo)
        if senha_hash:
            sets.append("senha = %s")
            params.append(senha_hash)
        if whatsapp is not None:
            sets.append("whatsapp = %s")
            params.append(_normalize_whatsapp(whatsapp).strip() or "")

        if not sets:
            raise UsuariosLojaError("Nenhuma alteração informada.")

        params.extend([chave, id_cliente])
        try:
            cur.execute(
                f"UPDATE usuarios SET {', '.join(sets)} WHERE chave = %s AND id_cliente = %s",
                tuple(params),
            )
        except mysql.connector.Error as e:
            if getattr(e, "errno", None) == 1054:
                sets_fallback = []
                params_fallback = []
                if senha_hash:
                    sets_fallback.append("senha = %s")
                    params_fallback.append(senha_hash)
                if not sets_fallback:
                    raise UsuariosLojaError(
                        "Banco sem colunas funcao/ativo. Execute adicionar_coluna_funcao_usuarios.sql.",
                        status=500,
                    ) from e
                params_fallback.extend([chave, id_cliente])
                cur.execute(
                    f"UPDATE usuarios SET {', '.join(sets_fallback)} WHERE chave = %s AND id_cliente = %s",
                    tuple(params_fallback),
                )
            else:
                raise

        if cur.rowcount == 0:
            raise UsuariosLojaError("Usuário não encontrado nesta loja.", status=404)

        conn.commit()
        updated = _fetch_usuario(cur, id_cliente, chave) or row
        return {
            "chave": updated.get("chave"),
            "usuario": updated.get("usuario"),
            "funcao": normalize_funcao(updated.get("funcao")),
            "ativo": int(updated.get("ativo") if updated.get("ativo") is not None else 1),
            "whatsapp": updated.get("whatsapp") or "",
        }
    except UsuariosLojaError:
        if conn:
            conn.rollback()
        raise
    except mysql.connector.Error as e:
        if conn:
            conn.rollback()
        raise UsuariosLojaError(f"Erro no banco de dados: {e}", status=500) from e
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
