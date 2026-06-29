"""Provisionamento de novos tenants (lojas) no banco multi-tenant."""
from __future__ import annotations

import mysql.connector

from database import conectar
from services.passwords import hash_password
from services.usuarios_loja import insert_usuario_row

DEFAULT_FORMAS_PAGAMENTO = (
    ("Dinheiro", "S"),
    ("PIX", "N"),
    ("Cartão débito", "N"),
    ("Cartão crédito", "N"),
)

DEFAULT_TXENTREGA_FAIXAS = (
    (3.0, 5.0),
    (5.0, 8.0),
    (8.0, 10.0),
    (10.0, 12.0),
    (12.0, 15.0),
    (15.0, 18.0),
    (18.0, 20.0),
    (20.0, 25.0),
    (25.0, 30.0),
    (30.0, 35.0),
)


class TenantProvisionError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _table_columns(cur, table: str) -> set[str]:
    cur.execute(f"SHOW COLUMNS FROM {table}")
    rows = cur.fetchall() or []
    out: set[str] = set()
    for r in rows:
        if isinstance(r, dict):
            out.add(str(r.get("Field") or ""))
        elif r:
            out.add(str(r[0]))
    return {c for c in out if c}


def _next_id_cliente(cur) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(id_cliente), 0) AS m FROM (
            SELECT id_cliente FROM usuarios WHERE id_cliente IS NOT NULL
            UNION ALL
            SELECT id_cliente FROM dadosloja WHERE id_cliente IS NOT NULL
        ) AS t
        """
    )
    row = cur.fetchone() or {}
    m = row.get("m") if isinstance(row, dict) else (row[0] if row else 0)
    return int(m or 0) + 1


def suggested_next_id_cliente() -> int:
    """Próximo id_cliente sugerido (MAX + 1)."""
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        return _next_id_cliente(cur)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _id_cliente_exists(cur, id_cliente: int) -> bool:
    cur.execute(
        """
        SELECT 1 FROM (
            SELECT id_cliente FROM dadosloja WHERE id_cliente = %s
            UNION ALL
            SELECT id_cliente FROM usuarios WHERE id_cliente = %s
        ) AS t
        LIMIT 1
        """,
        (id_cliente, id_cliente),
    )
    return cur.fetchone() is not None


def _resolve_id_cliente(cur, id_cliente_raw) -> int:
    if id_cliente_raw is None or str(id_cliente_raw).strip() == "":
        return _next_id_cliente(cur)
    try:
        id_cliente = int(id_cliente_raw)
    except (TypeError, ValueError):
        raise TenantProvisionError("id_cliente deve ser um número inteiro positivo.")
    if id_cliente <= 0:
        raise TenantProvisionError("id_cliente deve ser maior que zero.")
    if _id_cliente_exists(cur, id_cliente):
        raise TenantProvisionError(
            f"id_cliente {id_cliente} já está em uso.",
            status=409,
        )
    return id_cliente


def _usuario_login_exists(cur, usuario: str) -> bool:
    cur.execute("SELECT 1 FROM usuarios WHERE usuario = %s LIMIT 1", (usuario,))
    return cur.fetchone() is not None


def _insert_usuario(cur, usuario: str, senha_hash: str, id_cliente: int) -> None:
    insert_usuario_row(cur, usuario, senha_hash, id_cliente, funcao="gerente", ativo=1)


def _insert_formapagamento(cur, id_cliente: int) -> None:
    cur.execute("SHOW COLUMNS FROM formapagamento LIKE 'troco'")
    has_troco = cur.fetchone() is not None
    for forma, troco in DEFAULT_FORMAS_PAGAMENTO:
        if has_troco:
            cur.execute(
                "INSERT INTO formapagamento (forma, troco, id_cliente) VALUES (%s, %s, %s)",
                (forma, troco, id_cliente),
            )
        else:
            cur.execute(
                "INSERT INTO formapagamento (forma, id_cliente) VALUES (%s, %s)",
                (forma, id_cliente),
            )


def _insert_configuracao(cur, id_cliente: int) -> None:
    cols = _table_columns(cur, "configuracao")
    data = {
        "id_cliente": id_cliente,
        "nromesa": 100,
        "servicomesa": 0,
        "calculodistancia": "Sim",
        "imp_comandadelivery": 1,
    }
    insert_cols = [c for c in data if c in cols]
    if not insert_cols:
        raise TenantProvisionError(
            "Tabela configuracao sem colunas reconhecidas para provisionamento.",
            status=500,
        )
    placeholders = ", ".join(["%s"] * len(insert_cols))
    col_list = ", ".join(insert_cols)
    vals = tuple(data[c] for c in insert_cols)
    cur.execute(
        f"INSERT INTO configuracao ({col_list}) VALUES ({placeholders})",
        vals,
    )


def _insert_txentrega(cur, id_cliente: int) -> None:
    cols = ["chave", "id_cliente"]
    vals = [1, id_cliente]
    for i, (d, v) in enumerate(DEFAULT_TXENTREGA_FAIXAS, start=1):
        cols.extend([f"faixa{i}_d", f"faixa{i}_v"])
        vals.extend([d, v])
    placeholders = ", ".join(["%s"] * len(vals))
    col_list = ", ".join(cols)
    cur.execute(f"INSERT INTO txentrega ({col_list}) VALUES ({placeholders})", tuple(vals))


def provision_tenant(
    *,
    nome: str,
    usuario: str,
    senha: str,
    id_cliente=None,
    ddd: str = "",
    telefone: str = "",
    cidade: str = "",
    tipo_negocio: str = "restaurante",
) -> dict:
    """
    Cria tenant completo com registros mínimos para operação.
    Retorna dict com id_cliente, usuario e mensagem.
    """
    nome = (nome or "").strip()
    usuario = (usuario or "").strip()
    senha = senha or ""
    ddd = (ddd or "").strip()
    telefone = (telefone or "").strip()
    cidade = (cidade or "").strip()
    tipo_negocio = str(tipo_negocio or "restaurante").strip().lower()
    if tipo_negocio not in ("restaurante", "varejo"):
        raise TenantProvisionError("tipo_negocio deve ser 'restaurante' ou 'varejo'.")

    if not nome:
        raise TenantProvisionError("Nome fantasia é obrigatório.")
    if not usuario:
        raise TenantProvisionError("Login do gerente é obrigatório.")
    if len(senha) < 4:
        raise TenantProvisionError("Senha deve ter pelo menos 4 caracteres.")

    conn = None
    cur = None
    try:
        conn = conectar()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)

        if _usuario_login_exists(cur, usuario):
            raise TenantProvisionError(f"Login '{usuario}' já está em uso.", status=409)

        id_cliente = _resolve_id_cliente(cur, id_cliente)
        senha_hash = hash_password(senha)

        _insert_usuario(cur, usuario, senha_hash, id_cliente)

        cur.execute(
            """
            INSERT INTO dadosloja (id_cliente, nome, endereco, bairro, cidade, cep, telefone, cnpj, latitude, longitude, ddd, tipo_negocio)
            VALUES (%s, %s, '', '', %s, '', %s, '', '', '', %s, %s)
            """,
            (id_cliente, nome, cidade, telefone, ddd or "11", tipo_negocio),
        )

        cur.execute(
            "INSERT INTO contadorpedido (contador, id_cliente) VALUES (0, %s)",
            (id_cliente,),
        )

        _insert_configuracao(cur, id_cliente)

        _insert_formapagamento(cur, id_cliente)
        _insert_txentrega(cur, id_cliente)

        conn.commit()
        return {
            "sucesso": True,
            "id_cliente": id_cliente,
            "usuario": usuario,
            "mensagem": f"Loja '{nome}' criada com sucesso (id_cliente={id_cliente}).",
        }
    except TenantProvisionError:
        if conn:
            conn.rollback()
        raise
    except mysql.connector.Error as e:
        if conn:
            conn.rollback()
        raise TenantProvisionError(f"Erro no banco de dados: {e}", status=500) from e
    except Exception as e:
        if conn:
            conn.rollback()
        raise TenantProvisionError(f"Falha ao provisionar loja: {e}", status=500) from e
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def update_tenant_tipo_negocio(id_cliente: int, tipo_negocio: str) -> dict:
    """Atualiza tipo_negocio de uma loja existente (restaurante | varejo)."""
    try:
        id_cliente = int(id_cliente)
    except (TypeError, ValueError):
        raise TenantProvisionError("ID cliente inválido.", status=400)
    if id_cliente <= 0:
        raise TenantProvisionError("ID cliente inválido.", status=400)

    tipo = str(tipo_negocio or "restaurante").strip().lower()
    if tipo not in ("restaurante", "varejo"):
        raise TenantProvisionError("tipo_negocio deve ser 'restaurante' ou 'varejo'.")

    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            "UPDATE dadosloja SET tipo_negocio = %s WHERE id_cliente = %s",
            (tipo, id_cliente),
        )
        if cur.rowcount == 0:
            raise TenantProvisionError("Loja não encontrada.", status=404)
        conn.commit()
        return {
            "sucesso": True,
            "id_cliente": id_cliente,
            "tipo_negocio": tipo,
            "mensagem": f"Tipo de negócio atualizado para '{tipo}'.",
        }
    except TenantProvisionError:
        if conn:
            conn.rollback()
        raise
    except mysql.connector.Error as e:
        if conn:
            conn.rollback()
        raise TenantProvisionError(f"Erro no banco de dados: {e}", status=500) from e
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def list_tenants() -> list[dict]:
    """Lista lojas provisionadas com login gerente principal."""
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
                d.id_cliente,
                d.nome,
                d.cidade,
                d.telefone,
                d.ddd,
                d.tipo_negocio,
                (
                    SELECT u.usuario
                    FROM usuarios u
                    WHERE u.id_cliente = d.id_cliente
                    ORDER BY
                        CASE WHEN LOWER(COALESCE(u.funcao, '')) = 'gerente' THEN 0 ELSE 1 END,
                        u.chave ASC
                    LIMIT 1
                ) AS usuario_gerente,
                (
                    SELECT u.ativo
                    FROM usuarios u
                    WHERE u.id_cliente = d.id_cliente
                    ORDER BY u.chave ASC
                    LIMIT 1
                ) AS ativo
            FROM dadosloja d
            ORDER BY d.id_cliente ASC
            """
        )
        rows = cur.fetchall() or []
        out = []
        for r in rows:
            ativo_raw = r.get("ativo")
            out.append(
                {
                    "id_cliente": int(r.get("id_cliente") or 0),
                    "nome": r.get("nome") or "",
                    "cidade": r.get("cidade") or "",
                    "telefone": r.get("telefone") or "",
                    "ddd": r.get("ddd") or "",
                    "tipo_negocio": r.get("tipo_negocio") or "restaurante",
                    "usuario_gerente": r.get("usuario_gerente") or "",
                    "ativo": None if ativo_raw is None else bool(int(ativo_raw)),
                }
            )
        return out
    except mysql.connector.Error as e:
        if getattr(e, "errno", None) == 1054:
            cur.execute(
                """
                SELECT d.id_cliente, d.nome, d.cidade, d.telefone, d.ddd,
                    (SELECT u.usuario FROM usuarios u WHERE u.id_cliente = d.id_cliente LIMIT 1) AS usuario_gerente
                FROM dadosloja d
                ORDER BY d.id_cliente ASC
                """
            )
            rows = cur.fetchall() or []
            return [
                {
                    "id_cliente": int(r.get("id_cliente") or 0),
                    "nome": r.get("nome") or "",
                    "cidade": r.get("cidade") or "",
                    "telefone": r.get("telefone") or "",
                    "ddd": r.get("ddd") or "",
                    "usuario_gerente": r.get("usuario_gerente") or "",
                    "ativo": True,
                }
                for r in rows
            ]
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
