"""Promoção de catálogo/config: homologação → produção (por id_cliente)."""
from __future__ import annotations

import mysql.connector

from config import Config
from database import conectar_admin, conectar_admin_optional
from services.loja_ambiente import AMBIENTE_HOMOLOGATION, AMBIENTE_PRODUCTION
from services.tenant_provision import TenantProvisionError, hml_admin_disponivel


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


def _loja_exists(cur, id_cliente: int) -> bool:
    cur.execute(
        "SELECT 1 FROM dadosloja WHERE id_cliente = %s LIMIT 1",
        (id_cliente,),
    )
    return cur.fetchone() is not None


def _loja_tipo_negocio(cur, id_cliente: int) -> str:
    cur.execute(
        "SELECT tipo_negocio FROM dadosloja WHERE id_cliente = %s LIMIT 1",
        (id_cliente,),
    )
    row = cur.fetchone() or {}
    return str(row.get("tipo_negocio") or "restaurante").strip().lower()


def _count_produtos(cur, id_cliente: int) -> int:
    cur.execute(
        "SELECT COUNT(*) AS n FROM produtos WHERE id_cliente = %s",
        (id_cliente,),
    )
    row = cur.fetchone() or {}
    return int(row.get("n") or 0)


def _delete_retail_catalog(cur, id_cliente: int) -> dict:
    counts = {}
    try:
        cur.execute(
            """
            DELETE pr FROM produto_retail pr
            INNER JOIN produtos p ON p.chave = pr.product_id
            WHERE p.id_cliente = %s
            """,
            (id_cliente,),
        )
        counts["produto_retail"] = cur.rowcount
    except mysql.connector.Error as e:
        if getattr(e, "errno", None) not in (1146, 1054):
            raise
        counts["produto_retail"] = 0

    for table in ("produtos", "subcategoria", "categoria"):
        cur.execute(f"DELETE FROM {table} WHERE id_cliente = %s", (id_cliente,))
        counts[table] = cur.rowcount
    return counts


def _insert_copy(
    cur,
    table: str,
    row: dict,
    *,
    skip: set[str],
    overrides: dict | None = None,
) -> int:
    overrides = overrides or {}
    cols = [c for c in row.keys() if c not in skip and c in _table_columns(cur, table)]
    if not cols:
        raise TenantProvisionError(
            f"Nenhuma coluna para copiar em {table}.",
            status=500,
        )
    vals = [overrides.get(c, row[c]) for c in cols]
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    cur.execute(
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
        tuple(vals),
    )
    return int(cur.lastrowid)


def _copy_retail_catalog(hml_cur, prod_cur, id_cliente: int) -> dict:
    stats = {
        "categoria": 0,
        "subcategoria": 0,
        "produtos": 0,
        "produto_retail": 0,
    }

    hml_cur.execute(
        "SELECT * FROM categoria WHERE id_cliente = %s ORDER BY id",
        (id_cliente,),
    )
    cat_map: dict[int, int] = {}
    for row in hml_cur.fetchall() or []:
        old_id = int(row["id"])
        new_id = _insert_copy(prod_cur, "categoria", row, skip={"id"})
        cat_map[old_id] = new_id
        stats["categoria"] += 1

    hml_cur.execute(
        "SELECT * FROM subcategoria WHERE id_cliente = %s ORDER BY id",
        (id_cliente,),
    )
    sub_map: dict[int, int] = {}
    for row in hml_cur.fetchall() or []:
        old_id = int(row["id"])
        old_cat = int(row["categoria_id"])
        new_cat = cat_map.get(old_cat)
        if new_cat is None:
            raise TenantProvisionError(
                f"Subcategoria órfã (categoria_id={old_cat}) no HML.",
                status=500,
            )
        new_id = _insert_copy(
            prod_cur,
            "subcategoria",
            row,
            skip={"id"},
            overrides={"categoria_id": new_cat},
        )
        sub_map[old_id] = new_id
        stats["subcategoria"] += 1

    hml_cur.execute(
        "SELECT * FROM produtos WHERE id_cliente = %s ORDER BY chave",
        (id_cliente,),
    )
    chave_map: dict[int, int] = {}
    prod_cols = _table_columns(prod_cur, "produtos")
    for row in hml_cur.fetchall() or []:
        old_chave = int(row["chave"])
        overrides = {}
        if "category_id" in prod_cols and row.get("category_id") is not None:
            old_cat = int(row["category_id"])
            overrides["category_id"] = cat_map.get(old_cat)
        if "subcategory_id" in prod_cols and row.get("subcategory_id") is not None:
            old_sub = int(row["subcategory_id"])
            overrides["subcategory_id"] = sub_map.get(old_sub)
        new_chave = _insert_copy(
            prod_cur,
            "produtos",
            row,
            skip={"chave"},
            overrides=overrides,
        )
        chave_map[old_chave] = new_chave
        stats["produtos"] += 1

    pr_cols = _table_columns(hml_cur, "produto_retail")
    if not pr_cols:
        return stats

    hml_cur.execute(
        "SELECT * FROM produto_retail WHERE id_cliente = %s ORDER BY id",
        (id_cliente,),
    )
    for row in hml_cur.fetchall() or []:
        old_pid = int(row.get("product_id") or row.get("produto_id") or 0)
        new_pid = chave_map.get(old_pid)
        if not new_pid:
            raise TenantProvisionError(
                f"produto_retail sem produto correspondente (product_id={old_pid}).",
                status=500,
            )
        _insert_copy(
            prod_cur,
            "produto_retail",
            row,
            skip={"id"},
            overrides={"product_id": new_pid},
        )
        stats["produto_retail"] += 1

    return stats


def _replace_config_rows(hml_cur, prod_cur, table: str, id_cliente: int) -> int:
    if table not in _table_columns(hml_cur, table):
        return 0
    prod_cur.execute(f"DELETE FROM {table} WHERE id_cliente = %s", (id_cliente,))
    hml_cur.execute(f"SELECT * FROM {table} WHERE id_cliente = %s", (id_cliente,))
    rows = hml_cur.fetchall() or []
    skip = {"chave", "id"}
    n = 0
    for row in rows:
        _insert_copy(prod_cur, table, row, skip=skip)
        n += 1
    return n


def promote_tenant_hml_to_production(
    id_cliente: int,
    *,
    substituir: bool = False,
) -> dict:
    """
    Copia catálogo varejo e configurações do HML para produção.
    Não altera dadosloja.ambiente — use update_tenant_loja depois.
    """
    try:
        id_cliente = int(id_cliente)
    except (TypeError, ValueError):
        raise TenantProvisionError("ID cliente inválido.", status=400)
    if id_cliente <= 0:
        raise TenantProvisionError("ID cliente inválido.", status=400)

    if not hml_admin_disponivel():
        raise TenantProvisionError(
            "Banco de homologação não configurado neste servidor.",
            status=503,
        )
    if not Config.admin_db_configured(AMBIENTE_PRODUCTION):
        raise TenantProvisionError(
            "Banco de produção não configurado neste servidor.",
            status=503,
        )

    hml_conn = conectar_admin(AMBIENTE_HOMOLOGATION)
    prod_conn = conectar_admin(AMBIENTE_PRODUCTION)
    hml_cur = None
    prod_cur = None
    try:
        hml_cur = hml_conn.cursor(dictionary=True)
        prod_cur = prod_conn.cursor(dictionary=True)

        if not _loja_exists(hml_cur, id_cliente):
            raise TenantProvisionError(
                f"Loja #{id_cliente} não encontrada em homologação.",
                status=404,
            )
        if not _loja_exists(prod_cur, id_cliente):
            raise TenantProvisionError(
                f"Loja #{id_cliente} não encontrada em produção.",
                status=404,
            )

        tipo = _loja_tipo_negocio(hml_cur, id_cliente)
        if tipo != "varejo":
            raise TenantProvisionError(
                "Promoção de catálogo disponível apenas para lojas varejo no momento.",
                status=400,
            )

        prod_count = _count_produtos(prod_cur, id_cliente)
        if prod_count > 0 and not substituir:
            raise TenantProvisionError(
                f"Produção já tem {prod_count} produto(s) para a loja #{id_cliente}. "
                "Confirme substituição (substituir=true) para sobrescrever.",
                status=409,
            )

        hml_count = _count_produtos(hml_cur, id_cliente)
        if hml_count == 0:
            raise TenantProvisionError(
                "Homologação não tem produtos para copiar.",
                status=400,
            )

        prod_conn.start_transaction()
        deleted = {}
        if prod_count > 0:
            deleted = _delete_retail_catalog(prod_cur, id_cliente)

        catalog_stats = _copy_retail_catalog(hml_cur, prod_cur, id_cliente)
        config_stats = {
            "configuracao": _replace_config_rows(
                hml_cur, prod_cur, "configuracao", id_cliente
            ),
            "formapagamento": _replace_config_rows(
                hml_cur, prod_cur, "formapagamento", id_cliente
            ),
            "txentrega": _replace_config_rows(hml_cur, prod_cur, "txentrega", id_cliente),
        }

        prod_conn.commit()

        prod_db = Config.admin_db_profile(AMBIENTE_PRODUCTION)["database"]
        hml_db = Config.admin_db_profile(AMBIENTE_HOMOLOGATION)["database"]
        return {
            "sucesso": True,
            "id_cliente": id_cliente,
            "origem": hml_db,
            "destino": prod_db,
            "substituido": prod_count > 0,
            "removido_producao": deleted,
            "catalogo": catalog_stats,
            "config": config_stats,
            "mensagem": (
                f"Catálogo copiado de {hml_db} para {prod_db} "
                f"({catalog_stats['produtos']} produtos). "
                "Altere o ambiente para Produção e peça logout/login ao gerente."
            ),
        }
    except TenantProvisionError:
        if prod_conn:
            prod_conn.rollback()
        raise
    except mysql.connector.Error as e:
        if prod_conn:
            prod_conn.rollback()
        raise TenantProvisionError(f"Erro no banco de dados: {e}", status=500) from e
    finally:
        if hml_cur:
            hml_cur.close()
        if prod_cur:
            prod_cur.close()
        hml_conn.close()
        prod_conn.close()
