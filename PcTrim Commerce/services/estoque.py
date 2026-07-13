"""Controle simples de estoque baseado em movimentos."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import traceback
from typing import Any

from database import conectar

TIPOS_MOVIMENTO = frozenset({"entrada", "venda", "ajuste"})
ORIGENS_MOVIMENTO = frozenset({"manual", "venda"})


class EstoqueError(ValueError):
    """Erro de validação do controle de estoque."""


def _column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        LIMIT 1
        """,
        (table, column),
    )
    return cur.fetchone() is not None


def _index_exists(cur, table: str, index_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        LIMIT 1
        """,
        (table, index_name),
    )
    return cur.fetchone() is not None


def _ensure_produtos_controla_estoque(cur) -> None:
    if not _column_exists(cur, "produtos", "controla_estoque"):
        cur.execute(
            "ALTER TABLE produtos ADD COLUMN controla_estoque TINYINT(1) NOT NULL DEFAULT 0 AFTER id_cliente"
        )


def _ensure_produto_retail_estoque_minimo(cur) -> None:
    if not _column_exists(cur, "produto_retail", "estoque_minimo"):
        cur.execute(
            "ALTER TABLE produto_retail ADD COLUMN estoque_minimo DECIMAL(12,3) NOT NULL DEFAULT 0 AFTER estoque"
        )


def _ensure_estoque_movimentos_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS estoque_movimentos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            id_cliente INT NOT NULL,
            produto_id INT NOT NULL,
            tipo VARCHAR(20) NOT NULL,
            quantidade DECIMAL(12,3) NOT NULL,
            nropedido INT NULL,
            origem VARCHAR(20) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            KEY idx_estoque_cliente_produto (id_cliente, produto_id),
            KEY idx_estoque_pedido_produto_tipo (nropedido, produto_id, tipo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    if not _index_exists(cur, "estoque_movimentos", "idx_estoque_cliente_produto"):
        cur.execute(
            "ALTER TABLE estoque_movimentos ADD KEY idx_estoque_cliente_produto (id_cliente, produto_id)"
        )
    if not _index_exists(cur, "estoque_movimentos", "idx_estoque_pedido_produto_tipo"):
        cur.execute(
            "ALTER TABLE estoque_movimentos ADD KEY idx_estoque_pedido_produto_tipo (nropedido, produto_id, tipo)"
        )


def _migrar_estoque_legado(cur) -> None:
    if not _column_exists(cur, "produto_retail", "estoque"):
        return
    cur.execute(
        """
        INSERT INTO estoque_movimentos (id_cliente, produto_id, tipo, quantidade, nropedido, origem)
        SELECT pr.id_cliente,
               pr.product_id,
               'entrada',
               pr.estoque,
               NULL,
               'manual'
        FROM produto_retail pr
        LEFT JOIN (
            SELECT id_cliente, produto_id
            FROM estoque_movimentos
            GROUP BY id_cliente, produto_id
        ) em ON em.id_cliente = pr.id_cliente AND em.produto_id = pr.product_id
        WHERE pr.estoque > 0
          AND em.produto_id IS NULL
        """
    )


def ensure_estoque_schema() -> None:
    """Cria estrutura idempotente do estoque e migra saldo legado quando existir."""
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        _ensure_produtos_controla_estoque(cur)
        _ensure_produto_retail_estoque_minimo(cur)
        _ensure_estoque_movimentos_table(cur)
        _migrar_estoque_legado(cur)
        conn.commit()
    except Exception as exc:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        print("[ESTOQUE SCHEMA ERRO]", exc, flush=True)
        traceback.print_exc()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _parse_quantidade(value: Any) -> Decimal:
    try:
        quantidade = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise EstoqueError("Quantidade invalida.") from exc
    if quantidade <= 0:
        raise EstoqueError("Informe uma quantidade maior que zero.")
    return quantidade


def _formatar_quantidade(value: Any) -> str:
    quantidade = Decimal(str(value or 0))
    texto = format(quantidade.normalize(), "f")
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto or "0"


def _row_para_produto(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    saldo = Decimal(str(row.get("estoque_atual") or 0))
    minimo = Decimal(str(row.get("estoque_minimo") or 0))
    return {
        "produto_id": int(row["produto_id"]),
        "nome": str(row.get("nome") or ""),
        "estoque_atual": float(saldo),
        "estoque_minimo": float(minimo),
        "controla_estoque": bool(int(row.get("controla_estoque") or 0)),
        "estoque_baixo": saldo <= minimo,
    }


def _query_produtos_com_saldo(cur, id_cliente: int, produto_id: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT
            p.chave AS produto_id,
            p.produto AS nome,
            p.controla_estoque,
            COALESCE(pr.estoque_minimo, 0) AS estoque_minimo,
            COALESCE(mv.saldo_atual, 0) AS estoque_atual
        FROM produtos p
        LEFT JOIN produto_retail pr
               ON pr.product_id = p.chave
              AND pr.id_cliente = p.id_cliente
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
        ) mv
               ON mv.id_cliente = p.id_cliente
              AND mv.produto_id = p.chave
        WHERE p.id_cliente = %s
          AND COALESCE(p.controla_estoque, 0) = 1
    """
    params: list[Any] = [id_cliente, id_cliente]
    if produto_id is not None:
        sql += " AND p.chave = %s"
        params.append(int(produto_id))
    sql += " ORDER BY p.produto"
    cur.execute(sql, tuple(params))
    return cur.fetchall() or []


def calcular_saldo(id_cliente: int, produto_id: int, cur=None) -> float:
    """Retorna o saldo calculado do produto."""
    conn = None
    owns_cursor = cur is None
    try:
        if owns_cursor:
            conn = conectar()
            cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT COALESCE(
                SUM(
                    CASE
                        WHEN tipo = 'entrada' THEN quantidade
                        WHEN tipo = 'venda' THEN -quantidade
                        WHEN tipo = 'ajuste' THEN -quantidade
                        ELSE 0
                    END
                ),
                0
            ) AS saldo
            FROM estoque_movimentos
            WHERE id_cliente = %s AND produto_id = %s
            """,
            (id_cliente, produto_id),
        )
        row = cur.fetchone() or {}
        return float(row.get("saldo") or 0)
    finally:
        if owns_cursor:
            if cur:
                cur.close()
            if conn:
                conn.close()


def listar_produtos_com_saldo(id_cliente: int, cur=None) -> list[dict[str, Any]]:
    """Lista produtos com controle de estoque e saldo calculado."""
    conn = None
    owns_cursor = cur is None
    try:
        if owns_cursor:
            conn = conectar()
            cur = conn.cursor(dictionary=True)
        rows = _query_produtos_com_saldo(cur, id_cliente)
        return [_row_para_produto(row) for row in rows]
    finally:
        if owns_cursor:
            if cur:
                cur.close()
            if conn:
                conn.close()


def obter_produto_com_saldo(id_cliente: int, produto_id: int, cur=None) -> dict[str, Any] | None:
    """Obtém um produto com saldo calculado."""
    conn = None
    owns_cursor = cur is None
    try:
        if owns_cursor:
            conn = conectar()
            cur = conn.cursor(dictionary=True)
        rows = _query_produtos_com_saldo(cur, id_cliente, produto_id=produto_id)
        return _row_para_produto(rows[0]) if rows else None
    finally:
        if owns_cursor:
            if cur:
                cur.close()
            if conn:
                conn.close()


def registrar_movimento(
    id_cliente: int,
    produto_id: int,
    *,
    tipo: str,
    quantidade: Any,
    nropedido: int | None = None,
    origem: str = "manual",
    cur=None,
) -> dict[str, Any]:
    """Registra um movimento de estoque sem editar saldo diretamente."""
    tipo_norm = str(tipo or "").strip().lower()
    origem_norm = str(origem or "").strip().lower()
    if tipo_norm not in TIPOS_MOVIMENTO:
        raise EstoqueError("Tipo de movimentacao invalido.")
    if origem_norm not in ORIGENS_MOVIMENTO:
        raise EstoqueError("Origem da movimentacao invalida.")

    quantidade_dec = _parse_quantidade(quantidade)
    conn = None
    owns_cursor = cur is None
    try:
        if owns_cursor:
            conn = conectar()
            conn.start_transaction()
            cur = conn.cursor(dictionary=True)

        cur.execute(
            """
            SELECT chave, produto, COALESCE(controla_estoque, 0) AS controla_estoque
            FROM produtos
            WHERE chave = %s AND id_cliente = %s
            LIMIT 1
            """,
            (produto_id, id_cliente),
        )
        produto = cur.fetchone()
        if not produto:
            raise EstoqueError("Produto nao encontrado.")
        if int(produto.get("controla_estoque") or 0) != 1:
            raise EstoqueError("Este produto nao esta com controle de estoque ativo.")

        if tipo_norm == "venda" and nropedido:
            cur.execute(
                """
                SELECT id
                FROM estoque_movimentos
                WHERE id_cliente = %s
                  AND produto_id = %s
                  AND tipo = 'venda'
                  AND nropedido = %s
                LIMIT 1
                """,
                (id_cliente, produto_id, int(nropedido)),
            )
            existente = cur.fetchone()
            if existente:
                if owns_cursor and conn:
                    conn.commit()
                return {"id": int(existente["id"]), "duplicado": True}

        cur.execute(
            """
            INSERT INTO estoque_movimentos (
                id_cliente, produto_id, tipo, quantidade, nropedido, origem
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                id_cliente,
                produto_id,
                tipo_norm,
                quantidade_dec,
                int(nropedido) if nropedido not in (None, "") else None,
                origem_norm,
            ),
        )
        movimento_id = int(cur.lastrowid)
        saldo_atual = calcular_saldo(id_cliente, produto_id, cur=cur)

        if owns_cursor and conn:
            conn.commit()
        return {"id": movimento_id, "duplicado": False, "saldo_atual": saldo_atual}
    except Exception:
        if owns_cursor and conn:
            conn.rollback()
        raise
    finally:
        if owns_cursor:
            if cur:
                cur.close()
            if conn:
                conn.close()


def listar_historico(id_cliente: int, produto_id: int, limit: int = 20, cur=None) -> list[dict[str, Any]]:
    """Lista os movimentos mais recentes do produto."""
    conn = None
    owns_cursor = cur is None
    try:
        if owns_cursor:
            conn = conectar()
            cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT id, tipo, quantidade, nropedido, origem, created_at
            FROM estoque_movimentos
            WHERE id_cliente = %s AND produto_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (id_cliente, produto_id, max(1, int(limit))),
        )
        rows = cur.fetchall() or []
        historico: list[dict[str, Any]] = []
        for row in rows:
            tipo = str(row.get("tipo") or "").lower()
            quantidade = row.get("quantidade") or 0
            sinal = "+" if tipo == "entrada" else "-"
            rotulo = {"entrada": "Entrada", "venda": "Venda", "ajuste": "Ajuste"}.get(tipo, "Movimento")
            historico.append(
                {
                    "id": int(row["id"]),
                    "tipo": tipo,
                    "quantidade": float(quantidade),
                    "nropedido": row.get("nropedido"),
                    "origem": row.get("origem"),
                    "created_at": row.get("created_at"),
                    "descricao": f"{rotulo} {sinal}{_formatar_quantidade(quantidade)}",
                }
            )
        return historico
    finally:
        if owns_cursor:
            if cur:
                cur.close()
            if conn:
                conn.close()
