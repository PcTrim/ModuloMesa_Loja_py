"""Páginas e APIs do catálogo retail (categoria, subcategoria)."""
import mysql.connector
from flask import Blueprint, jsonify, render_template, request, session

from decorators import login_required, retail_only
from database import conectar
from services.dados_loja import obter_dados_loja
from services.retail_catalog import (
    RetailCatalogError,
    criar_categoria,
    criar_subcategoria,
    editar_categoria,
    editar_subcategoria,
    listar_categorias,
    listar_produtos_pdv_retail,
    listar_subcategorias,
    obter_categoria,
    obter_subcategoria,
    set_categoria_ativo,
    set_subcategoria_ativo,
)

retail_catalog_bp = Blueprint("retail_catalog", __name__)


def _id_cliente():
    return session.get("id_cliente")


def _parse_ativo_param():
    raw = request.args.get("ativo")
    if raw is None or raw == "":
        return None
    return 1 if str(raw).strip().lower() in ("1", "true", "sim") else 0


@retail_catalog_bp.route("/cadastrar-categoria-retail")
@login_required
@retail_only
def cadastrar_categoria_retail_view():
    id_cliente = _id_cliente()
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get("nome", "Minha Loja")
    return render_template(
        "cadastrar_categoria_retail.html",
        id_cliente=id_cliente,
        nome_fantasia=nome_fantasia,
    )


@retail_catalog_bp.route("/cadastrar-subcategoria")
@login_required
@retail_only
def cadastrar_subcategoria_view():
    id_cliente = _id_cliente()
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get("nome", "Minha Loja")
    return render_template(
        "cadastrar_subcategoria.html",
        id_cliente=id_cliente,
        nome_fantasia=nome_fantasia,
    )


@retail_catalog_bp.route("/api/retail/categorias", methods=["GET"])
@login_required
@retail_only
def api_listar_categorias():
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        rows = listar_categorias(cur, _id_cliente(), ativo=_parse_ativo_param())
        return jsonify({"sucesso": True, "categorias": rows})
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao listar categorias"}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@retail_catalog_bp.route("/api/retail/categorias", methods=["POST"])
@login_required
@retail_only
def api_criar_categoria():
    conn = None
    cur = None
    try:
        dados = request.json or {}
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        new_id = criar_categoria(cur, _id_cliente(), dados)
        conn.commit()
        return jsonify({"sucesso": True, "id": new_id, "mensagem": "Categoria cadastrada com sucesso."})
    except RetailCatalogError as err:
        return jsonify({"sucesso": False, "erro": str(err)}), 400
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        if getattr(db_err, "errno", None) == 1062:
            return jsonify({"sucesso": False, "erro": "Já existe uma categoria com este nome."}), 409
        return jsonify({"sucesso": False, "erro": "Erro ao salvar categoria"}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@retail_catalog_bp.route("/api/retail/categorias/<int:categoria_id>", methods=["GET"])
@login_required
@retail_only
def api_obter_categoria(categoria_id):
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        row = obter_categoria(cur, _id_cliente(), categoria_id)
        if not row:
            return jsonify({"sucesso": False, "erro": "Categoria não encontrada."}), 404
        return jsonify({"sucesso": True, "categoria": row})
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao obter categoria"}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@retail_catalog_bp.route("/api/retail/categorias/<int:categoria_id>", methods=["PUT"])
@login_required
@retail_only
def api_editar_categoria(categoria_id):
    conn = None
    cur = None
    try:
        dados = request.json or {}
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        editar_categoria(cur, _id_cliente(), categoria_id, dados)
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Categoria atualizada com sucesso."})
    except RetailCatalogError as err:
        return jsonify({"sucesso": False, "erro": str(err)}), 400
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        if getattr(db_err, "errno", None) == 1062:
            return jsonify({"sucesso": False, "erro": "Já existe uma categoria com este nome."}), 409
        return jsonify({"sucesso": False, "erro": "Erro ao editar categoria"}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@retail_catalog_bp.route("/api/retail/categorias/<int:categoria_id>/ativo", methods=["PATCH"])
@login_required
@retail_only
def api_categoria_ativo(categoria_id):
    conn = None
    cur = None
    try:
        dados = request.json or {}
        ativo = dados.get("ativo")
        if ativo is None:
            return jsonify({"sucesso": False, "erro": "Campo ativo é obrigatório."}), 400
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        set_categoria_ativo(cur, _id_cliente(), categoria_id, 1 if ativo else 0)
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Status da categoria atualizado."})
    except RetailCatalogError as err:
        return jsonify({"sucesso": False, "erro": str(err)}), 400
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao atualizar categoria"}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@retail_catalog_bp.route("/api/retail/pdv/produtos", methods=["GET"])
@login_required
@retail_only
def api_pdv_produtos():
    conn = None
    cur = None
    try:
        categoria_raw = request.args.get("categoria_id")
        if categoria_raw in (None, ""):
            return jsonify({"sucesso": False, "erro": "categoria_id é obrigatório."}), 400
        try:
            categoria_id = int(categoria_raw)
        except (TypeError, ValueError):
            return jsonify({"sucesso": False, "erro": "categoria_id inválido."}), 400

        subcategoria_id = None
        sub_raw = request.args.get("subcategoria_id")
        if sub_raw not in (None, ""):
            try:
                subcategoria_id = int(sub_raw)
            except (TypeError, ValueError):
                return jsonify({"sucesso": False, "erro": "subcategoria_id inválido."}), 400

        id_cliente = _id_cliente()
        conn = conectar()
        cur = conn.cursor(dictionary=True)

        cat = obter_categoria(cur, id_cliente, categoria_id)
        if not cat:
            return jsonify({"sucesso": False, "erro": "Categoria não encontrada."}), 404

        if subcategoria_id is not None:
            sub = obter_subcategoria(cur, id_cliente, subcategoria_id)
            if not sub:
                return jsonify({"sucesso": False, "erro": "Subcategoria não encontrada."}), 404
            if int(sub["categoria_id"]) != categoria_id:
                return jsonify({"sucesso": False, "erro": "Subcategoria não pertence à categoria."}), 400

        produtos = listar_produtos_pdv_retail(
            cur,
            id_cliente,
            categoria_id=categoria_id,
            subcategoria_id=subcategoria_id,
        )
        return jsonify({"sucesso": True, "produtos": produtos})
    except RetailCatalogError as err:
        return jsonify({"sucesso": False, "erro": str(err)}), 400
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao listar produtos do PDV."}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@retail_catalog_bp.route("/api/retail/subcategorias", methods=["GET"])
@login_required
@retail_only
def api_listar_subcategorias():
    conn = None
    cur = None
    try:
        categoria_id = request.args.get("categoria_id")
        cat_filter = int(categoria_id) if categoria_id not in (None, "") else None
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        rows = listar_subcategorias(cur, _id_cliente(), categoria_id=cat_filter, ativo=_parse_ativo_param())
        return jsonify({"sucesso": True, "subcategorias": rows})
    except (TypeError, ValueError):
        return jsonify({"sucesso": False, "erro": "categoria_id inválido."}), 400
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao listar subcategorias"}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@retail_catalog_bp.route("/api/retail/subcategorias", methods=["POST"])
@login_required
@retail_only
def api_criar_subcategoria():
    conn = None
    cur = None
    try:
        dados = request.json or {}
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        new_id = criar_subcategoria(cur, _id_cliente(), dados)
        conn.commit()
        return jsonify({"sucesso": True, "id": new_id, "mensagem": "Subcategoria cadastrada com sucesso."})
    except RetailCatalogError as err:
        return jsonify({"sucesso": False, "erro": str(err)}), 400
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        if getattr(db_err, "errno", None) == 1062:
            return jsonify({"sucesso": False, "erro": "Já existe uma subcategoria com este nome nesta categoria."}), 409
        return jsonify({"sucesso": False, "erro": "Erro ao salvar subcategoria"}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@retail_catalog_bp.route("/api/retail/subcategorias/<int:subcategoria_id>", methods=["GET"])
@login_required
@retail_only
def api_obter_subcategoria(subcategoria_id):
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        row = obter_subcategoria(cur, _id_cliente(), subcategoria_id)
        if not row:
            return jsonify({"sucesso": False, "erro": "Subcategoria não encontrada."}), 404
        return jsonify({"sucesso": True, "subcategoria": row})
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao obter subcategoria"}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@retail_catalog_bp.route("/api/retail/subcategorias/<int:subcategoria_id>", methods=["PUT"])
@login_required
@retail_only
def api_editar_subcategoria(subcategoria_id):
    conn = None
    cur = None
    try:
        dados = request.json or {}
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        editar_subcategoria(cur, _id_cliente(), subcategoria_id, dados)
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Subcategoria atualizada com sucesso."})
    except RetailCatalogError as err:
        return jsonify({"sucesso": False, "erro": str(err)}), 400
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        if getattr(db_err, "errno", None) == 1062:
            return jsonify({"sucesso": False, "erro": "Já existe uma subcategoria com este nome nesta categoria."}), 409
        return jsonify({"sucesso": False, "erro": "Erro ao editar subcategoria"}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@retail_catalog_bp.route("/api/retail/subcategorias/<int:subcategoria_id>/ativo", methods=["PATCH"])
@login_required
@retail_only
def api_subcategoria_ativo(subcategoria_id):
    conn = None
    cur = None
    try:
        dados = request.json or {}
        ativo = dados.get("ativo")
        if ativo is None:
            return jsonify({"sucesso": False, "erro": "Campo ativo é obrigatório."}), 400
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        set_subcategoria_ativo(cur, _id_cliente(), subcategoria_id, 1 if ativo else 0)
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Status da subcategoria atualizado."})
    except RetailCatalogError as err:
        return jsonify({"sucesso": False, "erro": str(err)}), 400
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao atualizar subcategoria"}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
