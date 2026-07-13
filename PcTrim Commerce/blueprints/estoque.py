"""Tela simples de estoque."""
from __future__ import annotations

import traceback

from flask import Blueprint, jsonify, render_template, request, session

from decorators import login_required
from services.dados_loja import obter_dados_loja
from services.estoque import (
    EstoqueError,
    ensure_estoque_schema,
    listar_historico,
    listar_produtos_com_saldo,
    obter_produto_com_saldo,
    registrar_movimento,
)

estoque_bp = Blueprint("estoque", __name__)


def _id_cliente() -> int | None:
    return session.get("id_cliente")


def _payload() -> dict:
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict()


@estoque_bp.before_request
def _before_request_ensure_estoque_schema():
    if str(request.path or "").startswith("/estoque"):
        ensure_estoque_schema()


@estoque_bp.route("/estoque", methods=["GET"])
@login_required
def estoque_lista():
    id_cliente = _id_cliente()
    dados_loja = obter_dados_loja(id_cliente)
    produtos = listar_produtos_com_saldo(id_cliente)
    return render_template(
        "estoque.html",
        id_cliente=id_cliente,
        nome_fantasia=dados_loja.get("nome", "Minha Loja"),
        produtos=produtos,
    )


@estoque_bp.route("/estoque/<int:produto_id>", methods=["GET"])
@login_required
def estoque_detalhe(produto_id: int):
    id_cliente = _id_cliente()
    dados_loja = obter_dados_loja(id_cliente)
    produto = obter_produto_com_saldo(id_cliente, produto_id)
    if not produto:
        return render_template(
            "estoque_detalhe.html",
            id_cliente=id_cliente,
            nome_fantasia=dados_loja.get("nome", "Minha Loja"),
            produto=None,
            historico=[],
            tipo_padrao="entrada",
        ), 404
    historico = listar_historico(id_cliente, produto_id)
    tipo_padrao = str(request.args.get("tipo") or "entrada").strip().lower()
    if tipo_padrao not in ("entrada", "ajuste"):
        tipo_padrao = "entrada"
    return render_template(
        "estoque_detalhe.html",
        id_cliente=id_cliente,
        nome_fantasia=dados_loja.get("nome", "Minha Loja"),
        produto=produto,
        historico=historico,
        tipo_padrao=tipo_padrao,
    )


@estoque_bp.route("/estoque/<int:produto_id>/historico", methods=["GET"])
@login_required
def estoque_historico(produto_id: int):
    id_cliente = _id_cliente()
    produto = obter_produto_com_saldo(id_cliente, produto_id)
    if not produto:
        return jsonify({"sucesso": False, "erro": "Produto nao encontrado."}), 404
    return jsonify({"sucesso": True, "historico": listar_historico(id_cliente, produto_id)})


def _registrar_manual(tipo: str):
    id_cliente = _id_cliente()
    dados = _payload()
    produto_id = dados.get("produto_id")
    quantidade = dados.get("quantidade")
    try:
        if produto_id in (None, ""):
            raise EstoqueError("Produto nao informado.")
        movimento = registrar_movimento(
            id_cliente,
            int(produto_id),
            tipo=tipo,
            quantidade=quantidade,
            origem="manual",
        )
        return jsonify({"sucesso": True, "movimento": movimento})
    except EstoqueError as err:
        return jsonify({"sucesso": False, "erro": str(err)}), 400
    except Exception as exc:
        print("[ESTOQUE MOVIMENTO ERRO]", exc, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": "Nao foi possivel salvar o estoque."}), 500


@estoque_bp.route("/estoque/entrada", methods=["POST"])
@login_required
def estoque_entrada():
    return _registrar_manual("entrada")


@estoque_bp.route("/estoque/ajuste", methods=["POST"])
@login_required
def estoque_ajuste():
    return _registrar_manual("ajuste")
