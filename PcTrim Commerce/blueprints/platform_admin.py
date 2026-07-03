"""Administração da plataforma — cadastro de novas lojas (tenants)."""
from flask import Blueprint, jsonify, render_template, request, session

from config import Config
from decorators import login_required, platform_admin_required
from database import resolve_tenant_db_target
from services.dados_loja import obter_dados_loja
from services.clientes_internos import (
    ClientesInternosError,
    cliente_interno_disponivel,
    invalidate_clientes_internos_cache,
    list_clientes_internos_disponiveis,
    ensure_cliente_disponivel_para_loja,
)
from services.loja_ambiente import normalize_ambiente
from services.tenant_provision import (
    TenantProvisionError,
    hml_admin_disponivel,
    list_tenants,
    provision_tenant,
    suggested_next_id_cliente,
    update_tenant_loja,
)

platform_admin_bp = Blueprint("platform_admin", __name__)


@platform_admin_bp.route("/admin/lojas")
@login_required
@platform_admin_required
def admin_lojas_page():
    id_cliente = session.get("id_cliente")
    dados = obter_dados_loja(id_cliente)
    tenant = resolve_tenant_db_target(session)
    if tenant:
        db_ativo = Config.admin_db_profile(tenant)["database"]
    elif dados:
        db_ativo = Config.admin_db_profile(normalize_ambiente(dados.get("ambiente")))["database"]
    else:
        db_ativo = Config.admin_db_profile("production")["database"]
    return render_template(
        "admin_lojas.html",
        id_cliente=id_cliente,
        nome_fantasia=dados.get("nome", "Plataforma"),
        app_database=db_ativo,
    )


@platform_admin_bp.route("/api/admin/lojas", methods=["GET"])
@login_required
@platform_admin_required
def api_admin_lojas_list():
    try:
        lojas = list_tenants()
        return jsonify({
            "sucesso": True,
            "lojas": lojas,
            "proximo_id_sugerido": suggested_next_id_cliente(),
            "hml_disponivel": hml_admin_disponivel(),
        })
    except Exception as e:
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@platform_admin_bp.route("/api/clientes-internos-disponiveis", methods=["GET"])
@login_required
@platform_admin_required
def api_clientes_internos_disponiveis():
    try:
        clientes = list_clientes_internos_disponiveis()
        return jsonify({"sucesso": True, "clientes": clientes})
    except ClientesInternosError as e:
        return jsonify({"sucesso": False, "erro": e.message}), e.status
    except Exception:
        return jsonify(
            {"sucesso": False, "erro": "Não foi possível carregar os clientes no momento"}
        ), 503


@platform_admin_bp.route("/api/clientes-internos-disponiveis/<int:key_chave>", methods=["GET"])
@login_required
@platform_admin_required
def api_cliente_interno_disponivel_check(key_chave):
    try:
        ok = cliente_interno_disponivel(key_chave)
        return jsonify({"sucesso": True, "disponivel": ok, "id": key_chave})
    except Exception:
        return jsonify(
            {"sucesso": False, "erro": "Não foi possível carregar os clientes no momento"}
        ), 503


@platform_admin_bp.route("/api/admin/lojas", methods=["POST"])
@login_required
@platform_admin_required
def api_admin_lojas_create():
    data = request.get_json(silent=True) or {}
    senha = data.get("senha") or ""
    senha2 = data.get("senha_confirmacao") or data.get("senha2") or ""
    if senha != senha2:
        return jsonify({"sucesso": False, "erro": "Senha e confirmação não conferem."}), 400

    id_cliente_raw = data.get("id_cliente")
    if id_cliente_raw is None or str(id_cliente_raw).strip() == "":
        return jsonify({"sucesso": False, "erro": "Selecione um cliente."}), 400

    try:
        id_cliente = int(id_cliente_raw)
    except (TypeError, ValueError):
        return jsonify({"sucesso": False, "erro": "Selecione um cliente válido."}), 400

    try:
        ensure_cliente_disponivel_para_loja(id_cliente)
    except ClientesInternosError as e:
        return jsonify({"sucesso": False, "erro": e.message}), e.status

    try:
        result = provision_tenant(
            nome=data.get("nome"),
            usuario=data.get("usuario"),
            senha=senha,
            id_cliente=id_cliente,
            ddd=data.get("ddd"),
            telefone=data.get("telefone"),
            cidade=data.get("cidade"),
            tipo_negocio=data.get("tipo_negocio", "restaurante"),
            ambiente=data.get("ambiente", "production"),
        )
        invalidate_clientes_internos_cache()
        return jsonify(result)
    except TenantProvisionError as e:
        return jsonify({"sucesso": False, "erro": e.message}), e.status


@platform_admin_bp.route("/api/admin/lojas/<int:id_cliente>", methods=["PATCH"])
@login_required
@platform_admin_required
def api_admin_lojas_update(id_cliente):
    data = request.get_json(silent=True) or {}
    try:
        result = update_tenant_loja(
            id_cliente,
            tipo_negocio=data.get("tipo_negocio"),
            ambiente=data.get("ambiente"),
        )
        amb = data.get("ambiente")
        if amb and session.get("id_cliente") == id_cliente:
            result["requer_logout"] = True
        return jsonify(result)
    except TenantProvisionError as e:
        return jsonify({"sucesso": False, "erro": e.message}), e.status
