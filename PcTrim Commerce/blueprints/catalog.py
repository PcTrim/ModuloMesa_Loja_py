"""Product catalog pages and JSON API."""
import unicodedata

import mysql.connector
from flask import Blueprint, jsonify, render_template, request, session

from decorators import login_required
from database import conectar
from services.business_mode import is_retail
from services.dados_loja import obter_dados_loja
from services.retail_catalog import RetailCatalogError, apply_retail_produto_save, enrich_produto_retail

catalog_bp = Blueprint("catalog", __name__)


def _proximo_codigo_produto(cursor, id_cliente):
    """Próximo código sugerido: MAX(chave) da loja + 1, evitando colisão global."""
    cursor.execute(
        "SELECT COALESCE(MAX(chave), 0) + 1 AS prox FROM produtos WHERE id_cliente = %s",
        (id_cliente,),
    )
    row = cursor.fetchone()
    candidato = int((row or {}).get("prox") or 1)
    if candidato < 1:
        candidato = 1
    for _ in range(1000):
        cursor.execute("SELECT 1 FROM produtos WHERE chave = %s LIMIT 1", (candidato,))
        if not cursor.fetchone():
            return candidato
        candidato += 1
    return candidato


def _sincronizar_auto_increment_produtos(cursor):
    cursor.execute("SELECT COALESCE(MAX(chave), 0) + 1 AS prox FROM produtos")
    row = cursor.fetchone()
    prox = int((row or {}).get("prox") or 1)
    if prox < 1:
        prox = 1
    cursor.execute("ALTER TABLE produtos AUTO_INCREMENT = %s", (prox,))


def _parse_bool_flag(value, default: int = 0) -> int:
    if value is None or value == "":
        return int(default)
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) != 0 else 0
    return 1 if str(value).strip().lower() in ("1", "true", "sim", "s", "yes", "y") else 0


def _norm_sim_nao(value, default: str = "Nao") -> str:
    """Canonicaliza flag de produto para 'Sim' ou 'Nao' (options do select HTML)."""
    fallback = "Sim" if str(default).strip().lower() in ("sim", "s", "1", "true", "yes", "y") else "Nao"
    if value is None or value == "":
        return fallback

    raw = str(value).strip().upper()
    raw = "".join(c for c in unicodedata.normalize("NFD", raw) if unicodedata.category(c) != "Mn")
    if raw in ("S", "SIM", "1", "TRUE", "Y", "YES", "T"):
        return "Sim"
    if raw in ("N", "NAO", "0", "FALSE", "NO"):
        return "Nao"
    return fallback


def _resolver_classe_retail(cursor, id_cliente: int, dados: dict) -> str:
    """No varejo, classe vem do nome da categoria retail selecionada."""
    category_id = dados.get("category_id")
    if category_id in (None, ""):
        raise RetailCatalogError("Categoria retail é obrigatória.")
    try:
        cat_id = int(category_id)
    except (TypeError, ValueError) as exc:
        raise RetailCatalogError("Categoria retail inválida.") from exc
    cursor.execute(
        "SELECT nome FROM categoria WHERE id = %s AND id_cliente = %s LIMIT 1",
        (cat_id, id_cliente),
    )
    row = cursor.fetchone()
    if not row:
        raise RetailCatalogError("Categoria retail não encontrada.")
    nome = str(row.get("nome") or "").strip().upper()
    return nome or "VAREJO"


@catalog_bp.route("/api/proximo-codigo-produto", methods=["GET"])
@login_required
def proximo_codigo_produto():
    """Sugere o próximo código de produto para a loja logada."""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get("id_cliente")
        codigo = _proximo_codigo_produto(cursor, id_cliente)
        return jsonify({"sucesso": True, "codigo_sugerido": codigo})
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao sugerir código do produto"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@catalog_bp.route("/cadastrar-produto")
@login_required
def cadastrar_produto_view():
    """Página para cadastrar produtos"""
    id_cliente = session.get("id_cliente")
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get("nome", "Minha Loja")
    return render_template("cadastrar_produto.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)


@catalog_bp.route("/api/salvar-produto", methods=["POST"])
@login_required
def salvar_produto():
    """Salva um novo produto na tabela de produtos"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        produto = dados.get("produto", "").strip()
        preco = dados.get("preco", 0)
        classe = dados.get("classe", "").strip().upper()
        porkilo = _norm_sim_nao(dados.get("porkilo", "Nao"), default="Nao")
        impressora = dados.get("impressora", 1)
        cfop = dados.get("cfop", "5102")
        ncm = dados.get("ncm", "")
        display = dados.get("display", 0)
        vendaliberada = _norm_sim_nao(dados.get("vendaliberada", "Sim"), default="Sim")
        descricao = dados.get("descricao", "")
        barcode = (dados.get("barcode") or "").strip() or None
        chave_informada = dados.get("chave")
        controla_estoque = _parse_bool_flag(dados.get("controla_estoque"), default=0)

        if not produto:
            return jsonify({"sucesso": False, "erro": "Nome do produto é obrigatório"}), 400

        conn = conectar()
        cursor = conn.cursor(dictionary=True)

        id_cliente = session.get("id_cliente")
        if is_retail():
            try:
                classe = _resolver_classe_retail(cursor, id_cliente, dados)
            except RetailCatalogError as err:
                return jsonify({"sucesso": False, "erro": str(err)}), 400
        elif not classe:
            return jsonify({"sucesso": False, "erro": "Classe e nome do produto são obrigatórios"}), 400
        chave_explicita = None
        if chave_informada is not None and str(chave_informada).strip() != "":
            try:
                chave_explicita = int(chave_informada)
            except (TypeError, ValueError):
                return jsonify({"sucesso": False, "erro": "Código do produto inválido"}), 400
            if chave_explicita < 1:
                return jsonify({"sucesso": False, "erro": "Código do produto deve ser maior que zero"}), 400
            cursor.execute("SELECT 1 FROM produtos WHERE chave = %s LIMIT 1", (chave_explicita,))
            if cursor.fetchone():
                return jsonify(
                    {"sucesso": False, "erro": f"Código {chave_explicita} já está em uso"}
                ), 409

        valores = (
            produto,
            preco,
            classe,
            porkilo,
            impressora,
            cfop,
            ncm,
            display,
            vendaliberada,
            descricao,
            barcode,
            controla_estoque,
            id_cliente,
        )

        if chave_explicita is not None:
            cursor.execute(
                """
                INSERT INTO produtos (chave, produto, preco, classe, porkilo, impressora, cfop, ncm, display, vendaliberada, descricao, barcode, controla_estoque, id_cliente)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (chave_explicita, *valores),
            )
            chave_gerada = chave_explicita
            _sincronizar_auto_increment_produtos(cursor)
        else:
            cursor.execute(
                """
                INSERT INTO produtos (produto, preco, classe, porkilo, impressora, cfop, ncm, display, vendaliberada, descricao, barcode, controla_estoque, id_cliente)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                valores,
            )
            chave_gerada = cursor.lastrowid

        if is_retail():
            apply_retail_produto_save(cursor, id_cliente, chave_gerada, dados)

        conn.commit()

        print(f"[PRODUTO CADASTRADO] {produto} (código: {chave_gerada}, classe: {classe})")
        return jsonify(
            {"sucesso": True, "mensagem": f"Produto '{produto}' cadastrado com sucesso! (Código: {chave_gerada})"}
        )

    except RetailCatalogError as err:
        if conn:
            conn.rollback()
        return jsonify({"sucesso": False, "erro": str(err)}), 400
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        if getattr(db_err, "errno", None) == 1062:
            return jsonify({"sucesso": False, "erro": "Código do produto já está em uso"}), 409
        return jsonify({"sucesso": False, "erro": "Erro ao salvar produto no banco de dados"}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@catalog_bp.route("/api/listar-produtos", methods=["GET"])
@login_required
def listar_produtos():
    """Lista todos os produtos cadastrados"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)

        id_cliente = session.get("id_cliente")
        if is_retail():
            cursor.execute(
                """
                SELECT p.chave, p.produto, p.preco, p.classe, p.porkilo, p.impressora, p.cfop, p.ncm,
                       p.display, p.vendaliberada, p.descricao, p.barcode,
                       p.controla_estoque,
                       p.category_id, p.subcategory_id,
                       c.nome AS categoria_nome, s.nome AS subcategoria_nome,
                       COALESCE(mv.saldo_atual, 0) AS estoque,
                       COALESCE(pr.estoque_minimo, 0) AS estoque_minimo,
                       pr.destaque, pr.ativo AS retail_ativo
                FROM produtos p
                LEFT JOIN categoria c ON c.id = p.category_id AND c.id_cliente = p.id_cliente
                LEFT JOIN subcategoria s ON s.id = p.subcategory_id AND s.id_cliente = p.id_cliente
                LEFT JOIN produto_retail pr ON pr.product_id = p.chave AND pr.id_cliente = p.id_cliente
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
                WHERE p.id_cliente = %s
                ORDER BY p.produto
                """,
                (id_cliente, id_cliente),
            )
        else:
            cursor.execute(
                """
                SELECT chave, produto, preco, classe, porkilo, impressora, cfop, ncm,
                       display, vendaliberada, descricao, barcode, controla_estoque
                FROM produtos
                WHERE id_cliente = %s
                ORDER BY produto
            """,
                (id_cliente,),
            )

        produtos = cursor.fetchall()

        return jsonify({"sucesso": True, "produtos": produtos})

    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao listar produtos"}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@catalog_bp.route("/api/obter-produto/<int:chave>", methods=["GET"])
@login_required
def obter_produto(chave):
    """Obtém dados de um produto específico"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)

        id_cliente = session.get("id_cliente")
        cursor.execute(
            """
            SELECT chave, produto, preco, classe, porkilo, impressora, cfop, ncm,
                   display, vendaliberada, descricao, barcode, controla_estoque
            FROM produtos
            WHERE chave = %s AND id_cliente = %s
        """,
            (chave, id_cliente),
        )

        produto = cursor.fetchone()

        if produto:
            if is_retail():
                enrich_produto_retail(cursor, id_cliente, produto)
            return jsonify({"sucesso": True, "produto": produto})
        else:
            return jsonify({"sucesso": False, "erro": "Produto não encontrado"}), 404

    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao obter produto"}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@catalog_bp.route("/api/produto/codigo/<codigo>", methods=["GET"])
@login_required
def obter_produto_por_codigo(codigo):
    """Busca produto por código de barras ou chave interna (numérica)."""
    conn = None
    cursor = None
    try:
        codigo = (codigo or "").strip()
        if not codigo:
            return jsonify({"sucesso": False, "erro": "Código inválido"}), 400

        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get("id_cliente")

        if codigo.isdigit():
            cursor.execute(
                """
                SELECT chave, produto AS nome, preco, classe, descricao, barcode
                FROM produtos
                WHERE id_cliente = %s AND (barcode = %s OR chave = %s)
                LIMIT 1
                """,
                (id_cliente, codigo, int(codigo)),
            )
        else:
            cursor.execute(
                """
                SELECT chave, produto AS nome, preco, classe, descricao, barcode
                FROM produtos
                WHERE id_cliente = %s AND barcode = %s
                LIMIT 1
                """,
                (id_cliente, codigo),
            )

        produto = cursor.fetchone()
        if produto:
            return jsonify({"sucesso": True, "produto": produto})
        return jsonify({"sucesso": False, "erro": "Produto não encontrado"}), 404

    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao buscar produto"}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@catalog_bp.route("/api/editar-produto/<int:chave>", methods=["PUT"])
@login_required
def editar_produto(chave):
    """Edita um produto existente"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        produto = dados.get("produto", "").strip()
        preco = dados.get("preco", 0)
        classe = dados.get("classe", "").strip().upper()
        porkilo = _norm_sim_nao(dados.get("porkilo", "Nao"), default="Nao")
        impressora = dados.get("impressora", 1)
        cfop = dados.get("cfop", "5102")
        ncm = dados.get("ncm", "")
        display = dados.get("display", 0)
        vendaliberada = _norm_sim_nao(dados.get("vendaliberada", "Sim"), default="Sim")
        descricao = dados.get("descricao", "")
        barcode = (dados.get("barcode") or "").strip() or None
        controla_estoque_raw = dados.get("controla_estoque")

        if not produto:
            return jsonify({"sucesso": False, "erro": "Nome do produto é obrigatório"}), 400

        conn = conectar()
        cursor = conn.cursor(dictionary=True)

        id_cliente = session.get("id_cliente")
        if is_retail():
            try:
                classe = _resolver_classe_retail(cursor, id_cliente, dados)
            except RetailCatalogError as err:
                return jsonify({"sucesso": False, "erro": str(err)}), 400
        elif not classe:
            return jsonify({"sucesso": False, "erro": "Classe e nome do produto são obrigatórios"}), 400

        cursor.execute(
            "SELECT chave, COALESCE(controla_estoque, 0) AS controla_estoque FROM produtos WHERE chave = %s AND id_cliente = %s LIMIT 1",
            (chave, id_cliente),
        )
        produto_atual = cursor.fetchone()
        if not produto_atual:
            return jsonify({"sucesso": False, "erro": "Produto não encontrado"}), 404
        controla_estoque = _parse_bool_flag(
            controla_estoque_raw,
            default=int(produto_atual.get("controla_estoque") or 0),
        )
        cursor.execute(
            """
            UPDATE produtos
            SET produto = %s, preco = %s, classe = %s, porkilo = %s,
                impressora = %s, cfop = %s, ncm = %s, display = %s,
                vendaliberada = %s, descricao = %s, barcode = %s, controla_estoque = %s
            WHERE chave = %s AND id_cliente = %s
        """,
            (
                produto,
                preco,
                classe,
                porkilo,
                impressora,
                cfop,
                ncm,
                display,
                vendaliberada,
                descricao,
                barcode,
                controla_estoque,
                chave,
                id_cliente,
            ),
        )

        if is_retail():
            apply_retail_produto_save(cursor, id_cliente, chave, dados)

        conn.commit()

        print(f"[PRODUTO ATUALIZADO] {produto} (código: {chave})")
        return jsonify({"sucesso": True, "mensagem": f"Produto '{produto}' atualizado com sucesso!"})

    except RetailCatalogError as err:
        if conn:
            conn.rollback()
        return jsonify({"sucesso": False, "erro": str(err)}), 400
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao editar produto"}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@catalog_bp.route("/api/excluir-produto/<int:chave>", methods=["DELETE"])
@login_required
def excluir_produto(chave):
    """Exclui um produto"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)

        id_cliente = session.get("id_cliente")
        cursor.execute(
            "SELECT produto FROM produtos WHERE chave = %s AND id_cliente = %s", (chave, id_cliente)
        )
        produto = cursor.fetchone()

        if not produto:
            return jsonify({"sucesso": False, "erro": "Produto não encontrado"}), 404

        cursor.execute("DELETE FROM produtos WHERE chave = %s AND id_cliente = %s", (chave, id_cliente))
        conn.commit()

        print(f"[PRODUTO EXCLUÍDO] {produto['produto']} (código: {chave})")
        return jsonify(
            {"sucesso": True, "mensagem": f"Produto '{produto['produto']}' excluído com sucesso!"}
        )

    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao excluir produto"}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
