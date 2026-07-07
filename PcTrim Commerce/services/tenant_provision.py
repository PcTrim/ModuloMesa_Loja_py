"""Provisionamento de novos tenants (lojas) no banco multi-tenant."""
from __future__ import annotations

import mysql.connector

from config import Config

from database import conectar_admin, conectar_admin_optional
from services.loja_ambiente import (
    AMBIENTE_HOMOLOGATION,
    AMBIENTE_PRODUCTION,
    ambiente_label,
    normalize_ambiente,
)
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

_LIST_QUERY = """
    SELECT
        d.id_cliente,
        d.nome,
        d.cidade,
        d.telefone,
        d.ddd,
        d.tipo_negocio,
        d.ambiente,
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

_LIST_QUERY_FALLBACK = """
    SELECT d.id_cliente, d.nome, d.cidade, d.telefone, d.ddd,
        (SELECT u.usuario FROM usuarios u WHERE u.id_cliente = d.id_cliente LIMIT 1) AS usuario_gerente
    FROM dadosloja d
    ORDER BY d.id_cliente ASC
"""


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


def hml_admin_disponivel() -> bool:
    return Config.admin_db_configured(AMBIENTE_HOMOLOGATION)


def _admin_targets_for_sync() -> list[str]:
    targets = [AMBIENTE_PRODUCTION]
    if hml_admin_disponivel():
        targets.append(AMBIENTE_HOMOLOGATION)
    return targets


def suggested_next_id_cliente() -> int:
    """Próximo id_cliente sugerido (MAX + 1 em prod e HML configurado)."""
    max_id = 0
    for target in _admin_targets_for_sync():
        conn = None
        cur = None
        try:
            conn = conectar_admin_optional(target=target)
            if conn is None:
                continue
            cur = conn.cursor(dictionary=True)
            max_id = max(max_id, _next_id_cliente(cur) - 1)
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
    return max_id + 1


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


def _usuario_login_exists_in_target(target: str, usuario: str) -> bool:
    conn = conectar_admin_optional(target=target)
    if conn is None:
        return False
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        return _usuario_login_exists(cur, usuario)
    finally:
        if cur:
            cur.close()
        conn.close()


def _usuario_login_exists_any_target(usuario: str) -> bool:
    for target in _admin_targets_for_sync():
        if _usuario_login_exists_in_target(target, usuario):
            return True
    return False


def _id_cliente_exists_in_target(target: str, id_cliente: int) -> bool:
    conn = conectar_admin_optional(target=target)
    if conn is None:
        return False
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        return _id_cliente_exists(cur, id_cliente)
    finally:
        if cur:
            cur.close()
        conn.close()


def _id_cliente_exists_any_target(id_cliente: int) -> bool:
    for target in _admin_targets_for_sync():
        if _id_cliente_exists_in_target(target, id_cliente):
            return True
    return False


def _resolve_id_cliente_global(id_cliente_raw) -> int:
    """Resolve id_cliente verificando ausência em todos os bancos configurados."""
    if id_cliente_raw is None or str(id_cliente_raw).strip() == "":
        return suggested_next_id_cliente()
    try:
        id_cliente = int(id_cliente_raw)
    except (TypeError, ValueError):
        raise TenantProvisionError("id_cliente deve ser um número inteiro positivo.")
    if id_cliente <= 0:
        raise TenantProvisionError("id_cliente deve ser maior que zero.")
    if _id_cliente_exists_any_target(id_cliente):
        raise TenantProvisionError(
            f"id_cliente {id_cliente} já está em uso.",
            status=409,
        )
    return id_cliente


def _build_loja_vals(
    *,
    id_cliente: int,
    nome: str,
    cidade: str,
    telefone: str,
    ddd: str,
    tipo_negocio: str,
    ambiente: str,
) -> dict:
    return {
        "id_cliente": id_cliente,
        "nome": nome,
        "endereco": "",
        "bairro": "",
        "cidade": cidade,
        "cep": "",
        "telefone": telefone,
        "cnpj": "",
        "latitude": "",
        "longitude": "",
        "ddd": ddd or "11",
        "tipo_negocio": tipo_negocio,
        "ambiente": ambiente,
    }


def _insert_tenant_rows(
    cur,
    *,
    loja_vals: dict,
    usuario: str,
    senha_hash: str,
    ddd: str = "",
    telefone: str = "",
) -> None:
    """Insere estrutura mínima do tenant num banco (dentro de transação aberta)."""
    id_cliente = int(loja_vals["id_cliente"])
    cols = _table_columns(cur, "dadosloja")
    loja_cols = [
        "id_cliente",
        "nome",
        "endereco",
        "bairro",
        "cidade",
        "cep",
        "telefone",
        "cnpj",
        "latitude",
        "longitude",
        "ddd",
        "tipo_negocio",
        "ambiente",
    ]
    insert_cols = [c for c in loja_cols if c in cols]
    placeholders = ", ".join(["%s"] * len(insert_cols))
    col_list = ", ".join(insert_cols)
    vals = tuple(loja_vals[c] for c in insert_cols)
    cur.execute(
        f"INSERT INTO dadosloja ({col_list}) VALUES ({placeholders})",
        vals,
    )

    _insert_usuario(cur, usuario, senha_hash, id_cliente, ddd=ddd, telefone=telefone)

    cur.execute(
        "INSERT INTO contadorpedido (contador, id_cliente) VALUES (0, %s)",
        (id_cliente,),
    )

    _insert_configuracao(cur, id_cliente)
    _insert_formapagamento(cur, id_cliente)
    _insert_txentrega(cur, id_cliente)


def _delete_tenant_rows(cur, id_cliente: int) -> None:
    """Remove tenant provisionado (rollback manual entre bancos)."""
    try:
        cur.execute(
            """
            DELETE pr FROM produto_retail pr
            INNER JOIN produtos p ON p.chave = pr.produto_id
            WHERE p.id_cliente = %s
            """,
            (id_cliente,),
        )
    except mysql.connector.Error as e:
        if getattr(e, "errno", None) not in (1146, 1054):
            raise
    for table in (
        "produtos",
        "subcategoria",
        "categoria",
        "formapagamento",
        "txentrega",
        "configuracao",
        "contadorpedido",
        "usuarios",
        "dadosloja",
    ):
        try:
            cur.execute(f"DELETE FROM {table} WHERE id_cliente = %s", (id_cliente,))
        except mysql.connector.Error as e:
            if getattr(e, "errno", None) != 1146:
                raise


def _rollback_tenant_in_target(target: str, id_cliente: int) -> None:
    conn = conectar_admin_optional(target=target)
    if conn is None:
        return
    cur = None
    try:
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        _delete_tenant_rows(cur, id_cliente)
        conn.commit()
    except mysql.connector.Error:
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        conn.close()


def _provision_tenant_in_target(
    target: str,
    *,
    id_cliente: int,
    loja_vals: dict,
    usuario: str,
    senha_hash: str,
    ddd: str = "",
    telefone: str = "",
) -> None:
    if not Config.admin_db_configured(target):
        label = ambiente_label(target)
        raise TenantProvisionError(
            f"Banco de {label} não configurado neste servidor.",
            status=503,
        )

    conn = None
    cur = None
    try:
        conn = conectar_admin(target=target)
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)

        if _id_cliente_exists(cur, id_cliente):
            raise TenantProvisionError(
                f"id_cliente {id_cliente} já está em uso em {ambiente_label(target)}.",
                status=409,
            )
        if _usuario_login_exists(cur, usuario):
            raise TenantProvisionError(
                f"Login '{usuario}' já está em uso em {ambiente_label(target)}.",
                status=409,
            )

        _insert_tenant_rows(
            cur,
            loja_vals=loja_vals,
            usuario=usuario,
            senha_hash=senha_hash,
            ddd=ddd,
            telefone=telefone,
        )
        conn.commit()
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


def _targets_with_tenant(id_cliente: int) -> list[str]:
    found: list[str] = []
    for target in _admin_targets_for_sync():
        if _id_cliente_exists_in_target(target, id_cliente):
            found.append(target)
    return found


def _compose_whatsapp_digits(ddd: str, telefone: str) -> str:
    """DDD + telefone em até 11 dígitos (coluna usuarios.whatsapp)."""
    d = "".join(c for c in (ddd or "") if c.isdigit())
    t = "".join(c for c in (telefone or "") if c.isdigit())
    if not t:
        return ""
    combined = (d + t) if d else t
    return combined[-11:]


def _insert_usuario(
    cur,
    usuario: str,
    senha_hash: str,
    id_cliente: int,
    *,
    ddd: str = "",
    telefone: str = "",
) -> None:
    whatsapp = _compose_whatsapp_digits(ddd, telefone)
    insert_usuario_row(
        cur,
        usuario,
        senha_hash,
        id_cliente,
        funcao="gerente",
        ativo=1,
        whatsapp=whatsapp,
    )


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


def _row_to_tenant(r: dict, *, bancos_cadastrados: list[str] | None = None) -> dict:
    ativo_raw = r.get("ativo")
    ambiente = normalize_ambiente(r.get("ambiente"))
    profile = Config.admin_db_profile(ambiente)
    bancos = bancos_cadastrados or []
    return {
        "id_cliente": int(r.get("id_cliente") or 0),
        "nome": r.get("nome") or "",
        "cidade": r.get("cidade") or "",
        "telefone": r.get("telefone") or "",
        "ddd": r.get("ddd") or "",
        "tipo_negocio": r.get("tipo_negocio") or "restaurante",
        "ambiente": ambiente,
        "ambiente_label": ambiente_label(ambiente),
        "banco_ativo": profile["database"],
        "bancos_cadastrados": bancos,
        "em_ambos_bancos": (
            AMBIENTE_PRODUCTION in bancos and AMBIENTE_HOMOLOGATION in bancos
        ),
        "usuario_gerente": r.get("usuario_gerente") or "",
        "ativo": None if ativo_raw is None else bool(int(ativo_raw)),
    }


def _list_from_target(target: str) -> list[dict]:
    conn = conectar_admin_optional(target=target)
    if conn is None:
        return []
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(_LIST_QUERY)
        except mysql.connector.Error as e:
            if getattr(e, "errno", None) != 1054:
                raise
            cur.execute(_LIST_QUERY_FALLBACK)
        rows = cur.fetchall() or []
        return rows
    finally:
        if cur:
            cur.close()
        conn.close()


def list_tenants() -> list[dict]:
    """Lista lojas de produção e homologação (prioriza registro de produção por id)."""
    presence: dict[int, list[str]] = {}
    rows_by_target: dict[str, list[dict]] = {}
    for target in _admin_targets_for_sync():
        rows = _list_from_target(target)
        rows_by_target[target] = rows
        for row in rows:
            key = int(row.get("id_cliente") or 0)
            if key <= 0:
                continue
            presence.setdefault(key, [])
            if target not in presence[key]:
                presence[key].append(target)

    merged: dict[int, dict] = {}
    for target in _admin_targets_for_sync():
        for r in rows_by_target.get(target, []):
            key = int(r.get("id_cliente") or 0)
            if key <= 0:
                continue
            tenant = _row_to_tenant(r, bancos_cadastrados=presence.get(key, []))
            if key not in merged or target == AMBIENTE_PRODUCTION:
                merged[key] = tenant
    return [merged[k] for k in sorted(merged)]


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
    ambiente: str = AMBIENTE_PRODUCTION,
    criar_ambos_bancos: bool = False,
) -> dict:
    """Cria tenant em um ou dois bancos; ambiente define onde o login opera."""
    nome = (nome or "").strip()
    usuario = (usuario or "").strip()
    senha = senha or ""
    ddd = (ddd or "").strip()
    telefone = (telefone or "").strip()
    cidade = (cidade or "").strip()
    tipo_negocio = str(tipo_negocio or "restaurante").strip().lower()
    ambiente = normalize_ambiente(ambiente)
    if tipo_negocio not in ("restaurante", "varejo"):
        raise TenantProvisionError("tipo_negocio deve ser 'restaurante' ou 'varejo'.")

    if not nome:
        raise TenantProvisionError("Nome fantasia é obrigatório.")
    if not usuario:
        raise TenantProvisionError("Login do gerente é obrigatório.")
    if len(senha) < 4:
        raise TenantProvisionError("Senha deve ter pelo menos 4 caracteres.")

    dual = bool(criar_ambos_bancos)
    if dual:
        if not Config.admin_db_configured(AMBIENTE_PRODUCTION):
            raise TenantProvisionError(
                "Banco de produção não configurado neste servidor.",
                status=503,
            )
        if not hml_admin_disponivel():
            raise TenantProvisionError(
                "Homologação não configurada; não é possível criar nos dois bancos.",
                status=503,
            )
        targets = [AMBIENTE_PRODUCTION, AMBIENTE_HOMOLOGATION]
    else:
        if not Config.admin_db_configured(ambiente):
            if ambiente == AMBIENTE_HOMOLOGATION:
                raise TenantProvisionError(
                    "Para criar loja de homologação, use o painel na URL de homologação "
                    "ou peça ao suporte para configurar o banco de testes neste servidor.",
                    status=503,
                )
            raise TenantProvisionError(
                "Banco de produção não configurado neste servidor.",
                status=503,
            )
        targets = [ambiente]

    if _usuario_login_exists_any_target(usuario):
        raise TenantProvisionError(f"Login '{usuario}' já está em uso.", status=409)

    resolved_id = _resolve_id_cliente_global(id_cliente)
    senha_hash = hash_password(senha)
    loja_vals = _build_loja_vals(
        id_cliente=resolved_id,
        nome=nome,
        cidade=cidade,
        telefone=telefone,
        ddd=ddd,
        tipo_negocio=tipo_negocio,
        ambiente=ambiente,
    )

    created: list[str] = []
    try:
        for target in targets:
            _provision_tenant_in_target(
                target,
                id_cliente=resolved_id,
                loja_vals=loja_vals,
                usuario=usuario,
                senha_hash=senha_hash,
                ddd=ddd,
                telefone=telefone,
            )
            created.append(target)
    except Exception:
        for target in reversed(created):
            try:
                _rollback_tenant_in_target(target, resolved_id)
            except mysql.connector.Error:
                pass
        raise

    active_profile = Config.admin_db_profile(ambiente)
    if dual:
        mensagem = (
            f"Loja '{nome}' criada em {Config.admin_db_profile(AMBIENTE_PRODUCTION)['database']} "
            f"e {Config.admin_db_profile(AMBIENTE_HOMOLOGATION)['database']} "
            f"(id_cliente={resolved_id}). Login ativo em {ambiente_label(ambiente)}."
        )
    else:
        mensagem = (
            f"Loja '{nome}' criada em {ambiente_label(ambiente)} "
            f"({active_profile['database']}, id_cliente={resolved_id})."
        )

    return {
        "sucesso": True,
        "id_cliente": resolved_id,
        "usuario": usuario,
        "ambiente": ambiente,
        "bancos_criados": created,
        "mensagem": mensagem,
    }


def update_tenant_loja(
    id_cliente: int,
    *,
    tipo_negocio: str | None,
    ambiente: str | None,
) -> dict:
    """Atualiza tipo e ambiente da loja (sincroniza ambiente nos 2 bancos se existir)."""
    try:
        id_cliente = int(id_cliente)
    except (TypeError, ValueError):
        raise TenantProvisionError("ID cliente inválido.", status=400)
    if id_cliente <= 0:
        raise TenantProvisionError("ID cliente inválido.", status=400)

    tipo = None
    if tipo_negocio is not None and str(tipo_negocio).strip():
        tipo = str(tipo_negocio).strip().lower()
        if tipo not in ("restaurante", "varejo"):
            raise TenantProvisionError("tipo_negocio deve ser 'restaurante' ou 'varejo'.")

    amb = None
    if ambiente is not None and str(ambiente).strip():
        amb = normalize_ambiente(ambiente)

    targets = _admin_targets_for_sync()

    found = False
    changed = False
    for target in targets:
        conn = None
        cur = None
        try:
            conn = conectar_admin_optional(target=target)
            if conn is None:
                continue
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT id_cliente, tipo_negocio, ambiente FROM dadosloja WHERE id_cliente = %s LIMIT 1",
                (id_cliente,),
            )
            row = cur.fetchone()
            if not row:
                continue
            found = True
            cols = _table_columns(cur, "dadosloja")
            sets = []
            vals = []
            if tipo is not None and "tipo_negocio" in cols:
                sets.append("tipo_negocio = %s")
                vals.append(tipo)
            if amb is not None and "ambiente" in cols:
                sets.append("ambiente = %s")
                vals.append(amb)
            if not sets:
                continue
            vals.append(id_cliente)
            cur2 = conn.cursor()
            cur2.execute(
                f"UPDATE dadosloja SET {', '.join(sets)} WHERE id_cliente = %s",
                tuple(vals),
            )
            if cur2.rowcount:
                changed = True
            cur2.close()
            conn.commit()
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

    if not found:
        raise TenantProvisionError(
            f"Loja #{id_cliente} não encontrada em produção nem homologação.",
            status=404,
        )

    final_amb = amb or AMBIENTE_PRODUCTION
    final_tipo = tipo or "restaurante"
    if not changed:
        return {
            "sucesso": True,
            "id_cliente": id_cliente,
            "tipo_negocio": final_tipo,
            "ambiente": final_amb,
            "mensagem": "Nada a alterar — valores já estavam corretos.",
        }

    return {
        "sucesso": True,
        "id_cliente": id_cliente,
        "tipo_negocio": final_tipo,
        "ambiente": final_amb,
        "banco_ativo": Config.admin_db_profile(final_amb)["database"],
        "mensagem": (
            f"Loja #{id_cliente} atualizada: ambiente {ambiente_label(final_amb)} "
            f"({Config.admin_db_profile(final_amb)['database']}), tipo {final_tipo}. "
            "Faça logout e login de novo para operar no banco correto."
        ),
    }


def update_tenant_tipo_negocio(id_cliente: int, tipo_negocio: str) -> dict:
    """Compatibilidade — atualiza só tipo."""
    return update_tenant_loja(id_cliente, tipo_negocio=tipo_negocio, ambiente=None)
