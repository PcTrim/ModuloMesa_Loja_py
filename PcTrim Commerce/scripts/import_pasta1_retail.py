#!/usr/bin/env python3
"""Importação one-shot: Pasta1.xls → catálogo retail (categoria, subcategoria, produtos)."""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal, InvalidOperation

# bootstrap app path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

import xlrd  # noqa: E402

from database import conectar_admin  # noqa: E402
from services.loja_ambiente import (  # noqa: E402
    AMBIENTE_HOMOLOGATION,
    AMBIENTE_PRODUCTION,
    fetch_loja_ambiente_for_cliente,
    normalize_ambiente,
)
from services.retail_catalog import (  # noqa: E402
    apply_retail_produto_save,
    criar_categoria,
    criar_subcategoria,
    listar_categorias,
    listar_subcategorias,
)
from services.retail_catalog_schema import (  # noqa: E402
    _ensure_categoria_table,
    _ensure_produto_retail_table,
    _ensure_produtos_retail_columns,
    _ensure_subcategoria_table,
)

DEFAULT_ID_CLIENTE = 2003
DEFAULT_XLS_PATH = r"c:\Users\user\Desktop\Pasta1.xls"
SHEET = "Plan1"

HEADER_MARKERS = {
    "categoria\\sub",
    "categoria",
    "subcategoria",
    "subcategorias",
    "código",
    "codigo",
    "titulo",
    "descrição",
    "descricao",
}


def _cell_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val).strip()


def _is_header_row(cat: str, cod: str, titulo: str) -> bool:
    blob = " ".join([cat, cod, titulo]).lower()
    if titulo.lower() in ("titulo", "descrição", "descricao"):
        return True
    if cat.lower() in ("categoria\\sub", "categoria") and not cod:
        return True
    for m in HEADER_MARKERS:
        if m in blob and not titulo:
            return True
    return False


def _parse_decimal(val) -> Decimal | None:
    if val is None or val == "":
        return None
    try:
        return Decimal(str(val).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _build_descricao(row: list) -> str:
    parts = []
    base = _cell_str(row[5]) if len(row) > 5 else ""
    if base:
        parts.append(base)
    extras = []
    labels = [
        (7, "Tamanho"),
        (8, "Peso kg"),
        (9, "Variação"),
        (10, "Acabamento"),
        (11, "Valor bruto"),
        (15, "Marca"),
    ]
    for idx, label in labels:
        if len(row) > idx:
            v = _cell_str(row[idx])
            if v:
                extras.append(f"{label}: {v}")
    if extras:
        parts.append(" | ".join(extras))
    return "\n".join(parts).strip() or None


def _ensure_schema(cur) -> None:
    _ensure_categoria_table(cur)
    _ensure_subcategoria_table(cur)
    _ensure_produtos_retail_columns(cur)
    _ensure_produto_retail_table(cur)


def _resolve_target(id_cliente: int, target_override: str | None) -> str:
    if target_override:
        return normalize_ambiente(target_override)
    return fetch_loja_ambiente_for_cliente(id_cliente)


def _get_or_create_categoria(cur, id_cliente: int, cache: dict, nome: str) -> int:
    key = nome.strip().lower()
    if key in cache:
        return cache[key]
    for row in listar_categorias(cur, id_cliente):
        if (row.get("nome") or "").strip().lower() == key:
            cache[key] = int(row["id"])
            return cache[key]
    cid = criar_categoria(cur, id_cliente, {"nome": nome, "ordem_exibicao": len(cache), "ativo": 1})
    cache[key] = cid
    return cid


def _get_or_create_subcategoria(
    cur, id_cliente: int, cache: dict, cat_id: int, nome: str
) -> int:
    key = (cat_id, nome.strip().lower())
    if key in cache:
        return cache[key]
    for row in listar_subcategorias(cur, id_cliente, categoria_id=cat_id):
        if (row.get("nome") or "").strip().lower() == nome.strip().lower():
            cache[key] = int(row["id"])
            return cache[key]
    sid = criar_subcategoria(
        cur,
        id_cliente,
        {"categoria_id": cat_id, "nome": nome, "ordem_exibicao": 0, "ativo": 1},
    )
    cache[key] = sid
    return sid


def _produto_exists_barcode(cur, id_cliente: int, barcode: str) -> int | None:
    if not barcode:
        return None
    cur.execute(
        "SELECT chave FROM produtos WHERE id_cliente = %s AND barcode = %s LIMIT 1",
        (id_cliente, barcode),
    )
    row = cur.fetchone()
    return int(row["chave"]) if row else None


def cleanup_retail_catalog(id_cliente: int, *, target: str) -> dict:
    """Remove catálogo retail da loja no banco admin indicado."""
    target = normalize_ambiente(target)
    conn = conectar_admin(target)
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM produto_retail WHERE id_cliente = %s", (id_cliente,))
        pr = cur.rowcount
        cur.execute("DELETE FROM produtos WHERE id_cliente = %s", (id_cliente,))
        prod = cur.rowcount
        cur.execute("DELETE FROM subcategoria WHERE id_cliente = %s", (id_cliente,))
        sub = cur.rowcount
        cur.execute("DELETE FROM categoria WHERE id_cliente = %s", (id_cliente,))
        cat = cur.rowcount
        conn.commit()
        return {
            "target": target,
            "id_cliente": id_cliente,
            "produto_retail": pr,
            "produtos": prod,
            "subcategoria": sub,
            "categoria": cat,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def import_sheet(
    path: str,
    *,
    id_cliente: int,
    target: str | None = None,
) -> dict:
    resolved_target = _resolve_target(id_cliente, target)
    conn = conectar_admin(resolved_target)
    cur = conn.cursor(dictionary=True)
    try:
        _ensure_schema(cur)
        conn.commit()

        wb = xlrd.open_workbook(path)
        sh = wb.sheet_by_name(SHEET)

        stats = {
            "target": resolved_target,
            "id_cliente": id_cliente,
            "categorias_novas": 0,
            "subcategorias_novas": 0,
            "produtos_inseridos": 0,
            "produtos_pulados": 0,
            "erros": [],
        }
        cat_cache: dict[str, int] = {}
        sub_cache: dict[tuple, int] = {}
        current_cat = ""

        cur.execute(
            "SELECT tipo_negocio, nome FROM dadosloja WHERE id_cliente = %s LIMIT 1",
            (id_cliente,),
        )
        loja = cur.fetchone()
        if not loja:
            raise RuntimeError(
                f"Loja id_cliente={id_cliente} não encontrada em dadosloja "
                f"(banco {resolved_target})."
            )
        tipo = (loja.get("tipo_negocio") or "").strip().lower()
        if tipo != "varejo":
            raise RuntimeError(
                f"Loja {id_cliente} tipo_negocio={tipo!r} — esperado 'varejo'."
            )

        cats_before = len(listar_categorias(cur, id_cliente))

        for r in range(sh.nrows):
            row = [sh.cell_value(r, c) for c in range(sh.ncols)]
            cat = _cell_str(row[0]) if len(row) > 0 else ""
            sub = _cell_str(row[1]) if len(row) > 1 else ""
            cod = _cell_str(row[2]) if len(row) > 2 else ""
            titulo = _cell_str(row[4]) if len(row) > 4 else ""

            if cat:
                current_cat = cat
            if _is_header_row(current_cat, cod, titulo):
                continue
            if not titulo and not cod:
                continue
            if not titulo:
                stats["produtos_pulados"] += 1
                continue
            if not current_cat:
                stats["erros"].append(f"Linha {r+1}: sem categoria para '{titulo}'")
                continue
            if not sub:
                sub = "Geral"

            cat_id = _get_or_create_categoria(cur, id_cliente, cat_cache, current_cat)
            sub_id = _get_or_create_subcategoria(cur, id_cliente, sub_cache, cat_id, sub)

            existing_id = _produto_exists_barcode(cur, id_cliente, cod)
            if existing_id:
                stats["produtos_pulados"] += 1
                continue

            preco_cheio = _parse_decimal(row[13] if len(row) > 13 else None)
            preco = preco_cheio if preco_cheio is not None else Decimal("0")
            descricao = _build_descricao(row)

            cur.execute(
                """
                INSERT INTO produtos (
                    produto, preco, classe, porkilo, impressora, cfop, ncm,
                    display, vendaliberada, descricao, barcode, id_cliente
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    titulo,
                    preco,
                    current_cat.upper(),
                    "Nao",
                    1,
                    "5102",
                    "",
                    1,
                    "Sim",
                    descricao,
                    cod or None,
                    id_cliente,
                ),
            )
            product_id = int(cur.lastrowid)

            estoque_raw = row[16] if len(row) > 16 else ""
            estoque = _parse_decimal(estoque_raw)
            apply_retail_produto_save(
                cur,
                id_cliente,
                product_id,
                {
                    "category_id": cat_id,
                    "subcategory_id": sub_id,
                    "retail": {
                        "nome_vitrine": titulo,
                        "descricao_vitrine": descricao,
                        "preco_varejo": preco_cheio,
                        "preco_atacado": _parse_decimal(row[12] if len(row) > 12 else None),
                        "comissao": _parse_decimal(row[14] if len(row) > 14 else None),
                        "estoque": estoque if estoque is not None else Decimal("0"),
                        "ativo": 1,
                    },
                },
            )
            stats["produtos_inseridos"] += 1

        conn.commit()
        cats_after = len(listar_categorias(cur, id_cliente))
        subs_after = len(listar_subcategorias(cur, id_cliente))
        stats["categorias_total"] = cats_after
        stats["categorias_novas"] = max(0, cats_after - cats_before)
        stats["subcategorias_total"] = subs_after
        stats["subcategorias_novas"] = len(sub_cache)
        stats["loja"] = loja.get("nome")
        return stats
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Importa Pasta1.xls para catálogo retail.")
    parser.add_argument(
        "--id-cliente",
        type=int,
        default=DEFAULT_ID_CLIENTE,
        help=f"ID da loja (default: {DEFAULT_ID_CLIENTE})",
    )
    parser.add_argument(
        "--target",
        choices=[AMBIENTE_PRODUCTION, AMBIENTE_HOMOLOGATION, "production", "homologation", "hml"],
        default=None,
        help="Força banco admin (production ou homologation)",
    )
    parser.add_argument(
        "--xls-path",
        default=DEFAULT_XLS_PATH,
        help="Caminho do arquivo .xls",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove catálogo retail da loja no banco indicado por --target",
    )
    parser.add_argument(
        "--cleanup-prod",
        action="store_true",
        help="(Legado) Remove catálogo em production para --id-cliente",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    xls_path = os.path.abspath(args.xls_path)
    if not args.cleanup and not args.cleanup_prod and not os.path.isfile(xls_path):
        print("Arquivo não encontrado:", xls_path)
        sys.exit(1)

    id_cliente = int(args.id_cliente)
    target = args.target
    if args.cleanup_prod:
        target = target or AMBIENTE_PRODUCTION
        if not target:
            print("--cleanup-prod exige --target ou usa production por padrão")
            sys.exit(1)

    if args.cleanup or args.cleanup_prod:
        if not target:
            print("--cleanup exige --target homologation ou production")
            sys.exit(1)
        removed = cleanup_retail_catalog(id_cliente, target=target)
        print("Limpeza:", removed)

    if not args.cleanup:
        result = import_sheet(xls_path, id_cliente=id_cliente, target=target)
        print(
            f"Importação concluída — id_cliente {id_cliente} banco {result.get('target')}"
        )
        for k, v in result.items():
            print(f"  {k}: {v}")
