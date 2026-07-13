"""CRUD do catálogo retail (categoria, subcategoria, produto_retail)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


class RetailCatalogError(ValueError):
    """Erro de validação ou regra de negócio do catálogo retail."""


SQL_JOIN_SALDO_ESTOQUE = """
        LEFT JOIN (
            SELECT
                id_cliente,
                produto_id,
                SUM(
                    CASE
                        WHEN tipo = 'entrada' THEN quantidade
                        WHEN tipo = 'venda' THEN -quantidade
                        WHEN tipo = 'ajuste' THEN -quantidade
                        ELSE 0
                    END
                ) AS saldo_atual
            FROM estoque_movimentos
            WHERE id_cliente = %s
            GROUP BY id_cliente, produto_id
        ) mv ON mv.id_cliente = p.id_cliente AND mv.produto_id = p.chave
"""


def saldo_estoque_de_linha(row: dict) -> float:
    raw = row.get("estoque_atual")
    if raw is None:
        raw = row.get("saldo_atual")
    try:
        return max(0.0, float(raw or 0))
    except (TypeError, ValueError):
        return 0.0


def campos_estoque_pdv(
    row: dict,
    *,
    estoque_minimo: float | None = None,
    sempre_numero: bool = False,
) -> dict[str, Any]:
    controla = int(row.get("controla_estoque") or 0)
    saldo = saldo_estoque_de_linha(row)
    out: dict[str, Any] = {"controla_estoque": controla}
    if controla:
        out["estoque_atual"] = saldo
        if estoque_minimo is not None:
            out["estoque_minimo"] = estoque_minimo
            out["estoque_baixo"] = estoque_minimo > 0 and saldo <= estoque_minimo
    elif sempre_numero:
        out["estoque_atual"] = 0.0
    else:
        out["estoque_atual"] = None
    return out


def _normalize_nome(nome: str) -> str:
    nome = (nome or "").strip()
    if not nome:
        raise RetailCatalogError("Nome é obrigatório.")
    if len(nome) > 120:
        raise RetailCatalogError("Nome deve ter no máximo 120 caracteres.")
    return nome


def _parse_int(value, field: str, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RetailCatalogError(f"{field} inválido.") from exc


def _parse_bool(value, default: int = 1) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) != 0 else 0
    text = str(value).strip().lower()
    if text in ("1", "true", "sim", "s", "yes", "y"):
        return 1
    if text in ("0", "false", "nao", "não", "n", "no"):
        return 0
    raise RetailCatalogError("Valor booleano inválido.")


def _parse_decimal(value, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RetailCatalogError(f"{field} inválido.") from exc


def _ensure_categoria_loja(cur, id_cliente: int, categoria_id: int) -> dict:
    cur.execute(
        "SELECT id, nome FROM categoria WHERE id = %s AND id_cliente = %s LIMIT 1",
        (categoria_id, id_cliente),
    )
    row = cur.fetchone()
    if not row:
        raise RetailCatalogError("Categoria não encontrada.")
    return row


def _ensure_subcategoria_loja(cur, id_cliente: int, subcategoria_id: int) -> dict:
    cur.execute(
        """
        SELECT s.id, s.nome, s.categoria_id, c.nome AS categoria_nome
        FROM subcategoria s
        JOIN categoria c ON c.id = s.categoria_id AND c.id_cliente = s.id_cliente
        WHERE s.id = %s AND s.id_cliente = %s
        LIMIT 1
        """,
        (subcategoria_id, id_cliente),
    )
    row = cur.fetchone()
    if not row:
        raise RetailCatalogError("Subcategoria não encontrada.")
    return row


def _ensure_produto_loja(cur, id_cliente: int, product_id: int) -> dict:
    cur.execute(
        "SELECT chave, produto FROM produtos WHERE chave = %s AND id_cliente = %s LIMIT 1",
        (product_id, id_cliente),
    )
    row = cur.fetchone()
    if not row:
        raise RetailCatalogError("Produto não encontrado.")
    return row


def listar_categorias(cur, id_cliente: int, ativo: int | None = None) -> list[dict]:
    sql = """
        SELECT id, nome, ordem_exibicao, ativo, created_at, updated_at
        FROM categoria
        WHERE id_cliente = %s
    """
    params: list[Any] = [id_cliente]
    if ativo is not None:
        sql += " AND ativo = %s"
        params.append(int(ativo))
    sql += " ORDER BY ordem_exibicao, nome"
    cur.execute(sql, tuple(params))
    return cur.fetchall() or []


def listar_produtos_pdv_retail(
    cur,
    id_cliente: int,
    *,
    categoria_id: int,
    subcategoria_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """Produtos ativos para PDV retail filtrados por categoria/subcategoria."""
    _ensure_categoria_loja(cur, id_cliente, categoria_id)
    if subcategoria_id is not None:
        sub = _ensure_subcategoria_loja(cur, id_cliente, subcategoria_id)
        if int(sub["categoria_id"]) != int(categoria_id):
            raise RetailCatalogError("Subcategoria não pertence à categoria.")

    sql = """
        SELECT
            p.chave,
            COALESCE(NULLIF(TRIM(pr.nome_vitrine), ''), p.produto) AS produto,
            p.descricao,
            p.barcode,
            p.classe,
            s.nome AS subcategoria_nome,
            pr.preco_varejo,
            p.preco AS preco_base,
            COALESCE(p.controla_estoque, 0) AS controla_estoque,
            COALESCE(pr.permite_venda_sem_estoque, 0) AS permite_venda_sem_estoque,
            COALESCE(pr.estoque_minimo, 0) AS estoque_minimo,
            COALESCE(mv.saldo_atual, 0) AS estoque_atual
        FROM produtos p
        JOIN produto_retail pr ON pr.product_id = p.chave AND pr.id_cliente = p.id_cliente
        JOIN categoria c ON c.id = p.category_id AND c.id_cliente = p.id_cliente
        LEFT JOIN subcategoria s ON s.id = p.subcategory_id AND s.id_cliente = p.id_cliente
""" + SQL_JOIN_SALDO_ESTOQUE + """
        WHERE p.id_cliente = %s
          AND p.category_id = %s
          AND UPPER(COALESCE(p.vendaliberada, '')) = 'SIM'
          AND COALESCE(pr.ativo, 1) = 1
          AND c.ativo = 1
    """
    params: list[Any] = [id_cliente, id_cliente, categoria_id]
    if subcategoria_id is not None:
        sql += " AND p.subcategory_id = %s"
        params.append(subcategoria_id)
    sql += """
        ORDER BY pr.ordem_exibicao, pr.nome_vitrine, p.produto
        LIMIT %s
    """
    params.append(max(1, int(limit)))
    cur.execute(sql, tuple(params))
    rows = cur.fetchall() or []
    result: list[dict] = []
    for row in rows:
        preco_raw = row.get("preco_varejo")
        if preco_raw is None:
            preco_raw = row.get("preco_base")
        try:
            preco = float(preco_raw or 0)
        except (TypeError, ValueError):
            preco = 0.0
        estoque_minimo = float(row.get("estoque_minimo") or 0)
        item = {
            "chave": row["chave"],
            "produto": row["produto"],
            "preco": preco,
            "barcode": row.get("barcode"),
            "classe": row.get("classe"),
            "descricao": row.get("descricao"),
            "subcategoria_nome": row.get("subcategoria_nome"),
            "permite_venda_sem_estoque": int(row.get("permite_venda_sem_estoque") or 0),
            **campos_estoque_pdv(row, estoque_minimo=estoque_minimo),
        }
        result.append(item)
    return result


def listar_produtos_por_classificacao(cur, id_cliente: int, classe: str) -> list[dict]:
    """Produtos de uma classificação (PDV restaurante) com saldo agregado."""
    sql = """
        SELECT
            p.chave,
            p.produto AS nome,
            p.preco,
            p.descricao AS observacao,
            p.barcode,
            COALESCE(p.controla_estoque, 0) AS controla_estoque,
            COALESCE(mv.saldo_atual, 0) AS estoque_atual
        FROM produtos p
""" + SQL_JOIN_SALDO_ESTOQUE + """
        WHERE p.classe = %s AND p.id_cliente = %s
        ORDER BY p.produto
    """
    cur.execute(sql, (id_cliente, classe, id_cliente))
    rows = cur.fetchall() or []
    result: list[dict] = []
    for row in rows:
        item = {
            "chave": row["chave"],
            "nome": row["nome"],
            "preco": row["preco"],
            "observacao": row.get("observacao"),
            "barcode": row.get("barcode"),
            **campos_estoque_pdv(row, sempre_numero=True),
        }
        result.append(item)
    return result


def obter_categoria(cur, id_cliente: int, categoria_id: int) -> dict | None:
    cur.execute(
        """
        SELECT id, nome, ordem_exibicao, ativo, created_at, updated_at
        FROM categoria
        WHERE id = %s AND id_cliente = %s
        LIMIT 1
        """,
        (categoria_id, id_cliente),
    )
    return cur.fetchone()


def criar_categoria(cur, id_cliente: int, dados: dict) -> int:
    nome = _normalize_nome(dados.get("nome"))
    ordem = _parse_int(dados.get("ordem_exibicao"), "Ordem de exibição", default=0) or 0
    ativo = _parse_bool(dados.get("ativo"), default=1)
    cur.execute(
        """
        INSERT INTO categoria (id_cliente, nome, ordem_exibicao, ativo)
        VALUES (%s, %s, %s, %s)
        """,
        (id_cliente, nome, ordem, ativo),
    )
    return int(cur.lastrowid)


def editar_categoria(cur, id_cliente: int, categoria_id: int, dados: dict) -> None:
    _ensure_categoria_loja(cur, id_cliente, categoria_id)
    nome = _normalize_nome(dados.get("nome"))
    ordem = _parse_int(dados.get("ordem_exibicao"), "Ordem de exibição", default=0) or 0
    ativo = _parse_bool(dados.get("ativo"), default=1)
    cur.execute(
        """
        UPDATE categoria
        SET nome = %s, ordem_exibicao = %s, ativo = %s
        WHERE id = %s AND id_cliente = %s
        """,
        (nome, ordem, ativo, categoria_id, id_cliente),
    )


def set_categoria_ativo(cur, id_cliente: int, categoria_id: int, ativo: int) -> None:
    _ensure_categoria_loja(cur, id_cliente, categoria_id)
    cur.execute(
        "UPDATE categoria SET ativo = %s WHERE id = %s AND id_cliente = %s",
        (int(ativo), categoria_id, id_cliente),
    )


def listar_subcategorias(
    cur,
    id_cliente: int,
    categoria_id: int | None = None,
    ativo: int | None = None,
) -> list[dict]:
    sql = """
        SELECT s.id, s.categoria_id, c.nome AS categoria_nome,
               s.nome, s.ordem_exibicao, s.ativo, s.created_at, s.updated_at
        FROM subcategoria s
        JOIN categoria c ON c.id = s.categoria_id AND c.id_cliente = s.id_cliente
        WHERE s.id_cliente = %s
    """
    params: list[Any] = [id_cliente]
    if categoria_id is not None:
        sql += " AND s.categoria_id = %s"
        params.append(int(categoria_id))
    if ativo is not None:
        sql += " AND s.ativo = %s"
        params.append(int(ativo))
    sql += " ORDER BY c.ordem_exibicao, c.nome, s.ordem_exibicao, s.nome"
    cur.execute(sql, tuple(params))
    return cur.fetchall() or []


def obter_subcategoria(cur, id_cliente: int, subcategoria_id: int) -> dict | None:
    cur.execute(
        """
        SELECT s.id, s.categoria_id, c.nome AS categoria_nome,
               s.nome, s.ordem_exibicao, s.ativo, s.created_at, s.updated_at
        FROM subcategoria s
        JOIN categoria c ON c.id = s.categoria_id AND c.id_cliente = s.id_cliente
        WHERE s.id = %s AND s.id_cliente = %s
        LIMIT 1
        """,
        (subcategoria_id, id_cliente),
    )
    return cur.fetchone()


def criar_subcategoria(cur, id_cliente: int, dados: dict) -> int:
    categoria_id = _parse_int(dados.get("categoria_id"), "Categoria")
    if not categoria_id:
        raise RetailCatalogError("Categoria é obrigatória.")
    _ensure_categoria_loja(cur, id_cliente, categoria_id)
    nome = _normalize_nome(dados.get("nome"))
    ordem = _parse_int(dados.get("ordem_exibicao"), "Ordem de exibição", default=0) or 0
    ativo = _parse_bool(dados.get("ativo"), default=1)
    cur.execute(
        """
        INSERT INTO subcategoria (id_cliente, categoria_id, nome, ordem_exibicao, ativo)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (id_cliente, categoria_id, nome, ordem, ativo),
    )
    return int(cur.lastrowid)


def editar_subcategoria(cur, id_cliente: int, subcategoria_id: int, dados: dict) -> None:
    atual = _ensure_subcategoria_loja(cur, id_cliente, subcategoria_id)
    categoria_id = atual["categoria_id"]
    if dados.get("categoria_id") is not None:
        categoria_id = _parse_int(dados.get("categoria_id"), "Categoria")
    if not categoria_id:
        raise RetailCatalogError("Categoria é obrigatória.")
    _ensure_categoria_loja(cur, id_cliente, categoria_id)
    nome = _normalize_nome(dados.get("nome"))
    ordem = _parse_int(dados.get("ordem_exibicao"), "Ordem de exibição", default=0) or 0
    ativo = _parse_bool(dados.get("ativo"), default=1)
    cur.execute(
        """
        UPDATE subcategoria
        SET categoria_id = %s, nome = %s, ordem_exibicao = %s, ativo = %s
        WHERE id = %s AND id_cliente = %s
        """,
        (categoria_id, nome, ordem, ativo, subcategoria_id, id_cliente),
    )


def set_subcategoria_ativo(cur, id_cliente: int, subcategoria_id: int, ativo: int) -> None:
    _ensure_subcategoria_loja(cur, id_cliente, subcategoria_id)
    cur.execute(
        "UPDATE subcategoria SET ativo = %s WHERE id = %s AND id_cliente = %s",
        (int(ativo), subcategoria_id, id_cliente),
    )


def sync_produto_categorias(
    cur,
    id_cliente: int,
    product_id: int,
    category_id: int | None,
    subcategory_id: int | None,
) -> None:
    _ensure_produto_loja(cur, id_cliente, product_id)

    cat_id = _parse_int(category_id, "Categoria", default=None) if category_id not in (None, "") else None
    sub_id = _parse_int(subcategory_id, "Subcategoria", default=None) if subcategory_id not in (None, "") else None

    if sub_id and not cat_id:
        raise RetailCatalogError("Informe a categoria ao vincular uma subcategoria.")

    if cat_id:
        _ensure_categoria_loja(cur, id_cliente, cat_id)

    if sub_id:
        sub = _ensure_subcategoria_loja(cur, id_cliente, sub_id)
        if int(sub["categoria_id"]) != int(cat_id):
            raise RetailCatalogError("Subcategoria não pertence à categoria selecionada.")

    cur.execute(
        """
        UPDATE produtos
        SET category_id = %s, subcategory_id = %s
        WHERE chave = %s AND id_cliente = %s
        """,
        (cat_id, sub_id, product_id, id_cliente),
    )


def get_produto_retail(cur, id_cliente: int, product_id: int) -> dict | None:
    cur.execute(
        """
        SELECT id, product_id, nome_vitrine, descricao_vitrine,
               preco_varejo, preco_atacado, comissao, estoque, estoque_minimo,
               permite_venda_sem_estoque, destaque, ativo, ordem_exibicao
        FROM produto_retail
        WHERE product_id = %s AND id_cliente = %s
        LIMIT 1
        """,
        (product_id, id_cliente),
    )
    return cur.fetchone()


def upsert_produto_retail(cur, id_cliente: int, product_id: int, dados: dict | None) -> None:
    if not dados:
        return
    _ensure_produto_loja(cur, id_cliente, product_id)

    nome_vitrine = (dados.get("nome_vitrine") or "").strip() or None
    descricao_vitrine = (dados.get("descricao_vitrine") or "").strip() or None
    preco_varejo = _parse_decimal(dados.get("preco_varejo"), "Preço varejo")
    preco_atacado = _parse_decimal(dados.get("preco_atacado"), "Preço atacado")
    comissao = _parse_decimal(dados.get("comissao"), "Comissão")
    estoque_minimo_raw = dados.get("estoque_minimo")
    estoque_minimo = (
        Decimal("0")
        if estoque_minimo_raw in (None, "")
        else _parse_decimal(estoque_minimo_raw, "Estoque mínimo")
    )
    permite = _parse_bool(dados.get("permite_venda_sem_estoque"), default=0)
    destaque = _parse_bool(dados.get("destaque"), default=0)
    ativo = _parse_bool(dados.get("ativo"), default=1)
    ordem = _parse_int(dados.get("ordem_exibicao"), "Ordem de exibição", default=0) or 0

    existing = get_produto_retail(cur, id_cliente, product_id)
    if existing:
        cur.execute(
            """
            UPDATE produto_retail
            SET nome_vitrine = %s, descricao_vitrine = %s,
                preco_varejo = %s, preco_atacado = %s, comissao = %s,
                estoque_minimo = %s, permite_venda_sem_estoque = %s,
                destaque = %s, ativo = %s, ordem_exibicao = %s
            WHERE product_id = %s AND id_cliente = %s
            """,
            (
                nome_vitrine,
                descricao_vitrine,
                preco_varejo,
                preco_atacado,
                comissao,
                estoque_minimo,
                permite,
                destaque,
                ativo,
                ordem,
                product_id,
                id_cliente,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO produto_retail (
                id_cliente, product_id, nome_vitrine, descricao_vitrine,
                preco_varejo, preco_atacado, comissao, estoque_minimo,
                permite_venda_sem_estoque, destaque, ativo, ordem_exibicao
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                id_cliente,
                product_id,
                nome_vitrine,
                descricao_vitrine,
                preco_varejo,
                preco_atacado,
                comissao,
                estoque_minimo,
                permite,
                destaque,
                ativo,
                ordem,
            ),
        )


def apply_retail_produto_save(cur, id_cliente: int, product_id: int, payload: dict) -> None:
    """Persiste category_id/subcategory_id e produto_retail num único passo."""
    category_id = payload.get("category_id")
    subcategory_id = payload.get("subcategory_id")
    if "category_id" in payload or "subcategory_id" in payload:
        sync_produto_categorias(cur, id_cliente, product_id, category_id, subcategory_id)
    retail = payload.get("retail")
    if isinstance(retail, dict):
        upsert_produto_retail(cur, id_cliente, product_id, retail)


def enrich_produto_retail(cur, id_cliente: int, produto: dict) -> dict:
    """Anexa category_id, subcategory_id e bloco retail ao dict do produto."""
    if not produto:
        return produto
    chave = produto.get("chave")
    cur.execute(
        """
        SELECT p.category_id, p.subcategory_id,
               c.nome AS categoria_nome, s.nome AS subcategoria_nome
        FROM produtos p
        LEFT JOIN categoria c ON c.id = p.category_id AND c.id_cliente = p.id_cliente
        LEFT JOIN subcategoria s ON s.id = p.subcategory_id AND s.id_cliente = p.id_cliente
        WHERE p.chave = %s AND p.id_cliente = %s
        LIMIT 1
        """,
        (chave, id_cliente),
    )
    row = cur.fetchone() or {}
    produto["category_id"] = row.get("category_id")
    produto["subcategory_id"] = row.get("subcategory_id")
    produto["categoria_nome"] = row.get("categoria_nome")
    produto["subcategoria_nome"] = row.get("subcategoria_nome")
    retail = get_produto_retail(cur, id_cliente, chave)
    produto["retail"] = retail or {}
    return produto
