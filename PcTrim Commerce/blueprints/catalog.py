"""Product catalog pages and JSON API."""
import mysql.connector
from flask import Blueprint, jsonify, render_template, request, session

from decorators import login_required
from database import conectar
from services.dados_loja import obter_dados_loja

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
        porkilo = dados.get("porkilo", "Nao")
        impressora = dados.get("impressora", 1)
        cfop = dados.get("cfop", "5102")
        ncm = dados.get("ncm", "")
        display = dados.get("display", 0)
        vendaliberada = dados.get("vendaliberada", "Sim")
        descricao = dados.get("descricao", "")
        barcode = (dados.get("barcode") or "").strip() or None
        chave_informada = dados.get("chave")

        if not classe or not produto:
            return jsonify({"sucesso": False, "erro": "Classe e nome do produto são obrigatórios"}), 400

        conn = conectar()
        cursor = conn.cursor(dictionary=True)

        id_cliente = session.get("id_cliente")
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
            id_cliente,
        )

        if chave_explicita is not None:
            cursor.execute(
                """
                INSERT INTO produtos (chave, produto, preco, classe, porkilo, impressora, cfop, ncm, display, vendaliberada, descricao, barcode, id_cliente)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (chave_explicita, *valores),
            )
            chave_gerada = chave_explicita
            _sincronizar_auto_increment_produtos(cursor)
        else:
            cursor.execute(
                """
                INSERT INTO produtos (produto, preco, classe, porkilo, impressora, cfop, ncm, display, vendaliberada, descricao, barcode, id_cliente)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                valores,
            )
            chave_gerada = cursor.lastrowid

        conn.commit()

        print(f"[PRODUTO CADASTRADO] {produto} (código: {chave_gerada}, classe: {classe})")
        return jsonify(
            {"sucesso": True, "mensagem": f"Produto '{produto}' cadastrado com sucesso! (Código: {chave_gerada})"}
        )

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
        cursor.execute(
            """
            SELECT chave, produto, preco, classe, porkilo, impressora, cfop, ncm, 
                   display, vendaliberada, descricao, barcode
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
                   display, vendaliberada, descricao, barcode
            FROM produtos
            WHERE chave = %s AND id_cliente = %s
        """,
            (chave, id_cliente),
        )

        produto = cursor.fetchone()

        if produto:
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
        porkilo = dados.get("porkilo", "Nao")
        impressora = dados.get("impressora", 1)
        cfop = dados.get("cfop", "5102")
        ncm = dados.get("ncm", "")
        display = dados.get("display", 0)
        vendaliberada = dados.get("vendaliberada", "Sim")
        descricao = dados.get("descricao", "")
        barcode = (dados.get("barcode") or "").strip() or None

        if not classe or not produto:
            return jsonify({"sucesso": False, "erro": "Classe e nome do produto são obrigatórios"}), 400

        conn = conectar()
        cursor = conn.cursor()

        id_cliente = session.get("id_cliente")
        cursor.execute(
            """
            UPDATE produtos 
            SET produto = %s, preco = %s, classe = %s, porkilo = %s, 
                impressora = %s, cfop = %s, ncm = %s, display = %s, 
                vendaliberada = %s, descricao = %s, barcode = %s
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
                chave,
                id_cliente,
            ),
        )

        conn.commit()

        if cursor.rowcount > 0:
            print(f"[PRODUTO ATUALIZADO] {produto} (código: {chave})")
            return jsonify({"sucesso": True, "mensagem": f"Produto '{produto}' atualizado com sucesso!"})
        else:
            return jsonify({"sucesso": False, "erro": "Produto não encontrado"}), 404

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
