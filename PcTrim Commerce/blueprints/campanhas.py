"""Rotas de campanhas promocionais."""
from __future__ import annotations

import traceback

from flask import Blueprint, jsonify, render_template, request, session

from database import conectar
from decorators import login_required
from services.business_mode import is_retail
from services.campanhas import (
    CampanhaError,
    aplicar_campanha_pedido,
    listar_campanhas,
    listar_categorias_opcoes,
    listar_elegiveis,
    listar_elegiveis_detalhado,
    obter_campanha,
    remover_campanhas_pedido,
    salvar_campanha,
    set_campanha_ativo,
    ensure_campanhas_schema,
    _carregar_itens_pedido,
)

campanhas_bp = Blueprint("campanhas", __name__)

_MSG_CASA_BLOQUEADO = "Comanda cancelada ou pedido em ROTA/RECEBIDO não pode ser alterado na tela /casa."


def _rota_exige_schema_campanhas() -> bool:
    path = str(request.path or "")
    if path.startswith("/api/campanhas"):
        return True
    if "/aplicar-campanha" in path:
        return True
    if request.method == "DELETE" and "/api/casa/" in path and path.rstrip("/").endswith("/campanha"):
        return True
    return False


@campanhas_bp.before_request
def _before_request_ensure_campanhas_schema():
    if _rota_exige_schema_campanhas():
        ensure_campanhas_schema()


def _origem_valida(origem: str) -> bool:
    return str(origem or "").strip().upper() in ("DELIVERY", "BALCAO")


def _casa_pedido_bloqueado(cur, id_cliente, nropedido, origem=None) -> bool:
    params = [int(nropedido), int(id_cliente)]
    if origem and _origem_valida(origem):
        orig_clause = " AND origem = %s "
        params.append(str(origem).strip().upper())
    else:
        orig_clause = " AND origem IN ('DELIVERY','BALCAO') "
    cur.execute(
        f"""
        SELECT 1 FROM pedido_diarios
        WHERE nropedido = %s AND id_cliente = %s {orig_clause}
          AND UPPER(TRIM(COALESCE(status_comanda, ''))) = 'CANCELADA'
        LIMIT 1
        """,
        tuple(params),
    )
    if cur.fetchone():
        return True
    cur.execute(
        f"""
        SELECT 1 FROM pedido_diarios
        WHERE nropedido = %s AND id_cliente = %s {orig_clause}
          AND UPPER(TRIM(COALESCE(status_pedido, ''))) IN ('RECEBIDO','ROTA')
        LIMIT 1
        """,
        tuple(params),
    )
    return cur.fetchone() is not None


def _resolver_cod_usuario(cur, id_cliente) -> int | None:
    id_usuario_sessao = session.get("id_usuario")
    if id_usuario_sessao is not None:
        try:
            return int(id_usuario_sessao)
        except Exception:
            pass
    usuario_logado = str(session.get("usuario_logado") or "").strip()
    if usuario_logado:
        cur.execute(
            "SELECT chave FROM usuarios WHERE usuario = %s AND id_cliente = %s LIMIT 1",
            (usuario_logado, id_cliente),
        )
        row = cur.fetchone() or {}
        ch = row.get("chave")
        if ch is not None:
            return int(ch)
    return None


@campanhas_bp.route("/campanhas", methods=["GET"])
@login_required
def campanhas_page():
    return render_template(
        "campanhas.html",
        id_cliente=session.get("id_cliente"),
        is_retail=is_retail(),
    )


@campanhas_bp.route("/api/campanhas", methods=["GET"])
@login_required
def api_listar_campanhas():
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        rows = listar_campanhas(cur, int(id_cliente))
        return jsonify({"sucesso": True, "campanhas": rows})
    except Exception as e:
        print("[CAMPANHAS LISTAR]", e, flush=True)
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@campanhas_bp.route("/api/campanhas", methods=["POST"])
@login_required
def api_criar_campanha():
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
    payload = request.get_json(silent=True) or {}
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        row = salvar_campanha(cur, int(id_cliente), payload)
        conn.commit()
        return jsonify({"sucesso": True, "campanha": row})
    except CampanhaError as e:
        if conn:
            conn.rollback()
        return jsonify({"sucesso": False, "erro": str(e)}), 400
    except Exception as e:
        if conn:
            conn.rollback()
        print("[CAMPANHAS CRIAR]", e, flush=True)
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@campanhas_bp.route("/api/campanhas/<int:campanha_id>", methods=["GET"])
@login_required
def api_obter_campanha(campanha_id: int):
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        row = obter_campanha(cur, int(id_cliente), campanha_id)
        if not row:
            return jsonify({"sucesso": False, "erro": "Campanha não encontrada."}), 404
        return jsonify({"sucesso": True, "campanha": row})
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@campanhas_bp.route("/api/campanhas/<int:campanha_id>", methods=["PUT"])
@login_required
def api_atualizar_campanha(campanha_id: int):
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
    payload = request.get_json(silent=True) or {}
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        existing = obter_campanha(cur, int(id_cliente), campanha_id)
        if not existing:
            return jsonify({"sucesso": False, "erro": "Campanha não encontrada."}), 404
        merged = {**existing, **payload}
        row = salvar_campanha(cur, int(id_cliente), merged, campanha_id=campanha_id)
        conn.commit()
        return jsonify({"sucesso": True, "campanha": row})
    except CampanhaError as e:
        if conn:
            conn.rollback()
        return jsonify({"sucesso": False, "erro": str(e)}), 400
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@campanhas_bp.route("/api/campanhas/<int:campanha_id>/ativo", methods=["PATCH"])
@login_required
def api_campanha_ativo(campanha_id: int):
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
    payload = request.get_json(silent=True) or {}
    ativo = payload.get("ativo", True)
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        row = set_campanha_ativo(cur, int(id_cliente), campanha_id, bool(ativo))
        conn.commit()
        return jsonify({"sucesso": True, "campanha": row})
    except CampanhaError as e:
        if conn:
            conn.rollback()
        return jsonify({"sucesso": False, "erro": str(e)}), 400
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@campanhas_bp.route("/api/campanhas/elegiveis", methods=["GET"])
@login_required
def api_campanhas_elegiveis():
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
    nropedido = request.args.get("nropedido")
    origem = request.args.get("origem")
    if not nropedido or not origem:
        return jsonify({"sucesso": False, "erro": "Informe nropedido e origem."}), 400
    if not _origem_valida(origem):
        return jsonify({"sucesso": False, "erro": "Origem inválida."}), 400
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        itens = _carregar_itens_pedido(cur, int(id_cliente), int(nropedido), origem)
        resultado = listar_elegiveis_detalhado(cur, int(id_cliente), itens, origem=origem)
        return jsonify({
            "sucesso": True,
            "campanhas": resultado.get("campanhas") or [],
            "indisponiveis": resultado.get("indisponiveis") or [],
        })
    except Exception as e:
        print("[CAMPANHAS ELEGIVEIS]", e, flush=True)
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@campanhas_bp.route("/api/campanhas/categorias-opcoes", methods=["GET"])
@login_required
def api_campanhas_categorias_opcoes():
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        rows = listar_categorias_opcoes(cur, int(id_cliente), retail=is_retail())
        return jsonify({"sucesso": True, "opcoes": rows})
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@campanhas_bp.route("/api/casa/<int:nropedido>/aplicar-campanha", methods=["POST"])
@login_required
def api_aplicar_campanha_pedido(nropedido: int):
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
    data = request.get_json(silent=True) or {}
    campanha_id = data.get("campanha_id")
    origem = data.get("origem")
    if campanha_id is None:
        return jsonify({"sucesso": False, "erro": "Informe campanha_id."}), 400
    if not _origem_valida(origem):
        return jsonify({"sucesso": False, "erro": "Origem inválida."}), 400
    conn = None
    cur = None
    try:
        from app import _insert_pedido_diarios_from_casa

        conn = conectar()
        cur = conn.cursor(dictionary=True)
        if _casa_pedido_bloqueado(cur, int(id_cliente), nropedido, origem):
            return jsonify({"sucesso": False, "erro": _MSG_CASA_BLOQUEADO}), 409
        cod_usuario = _resolver_cod_usuario(cur, int(id_cliente))
        if cod_usuario is None:
            return jsonify({"sucesso": False, "erro": "Não foi possível resolver cod_usuario do usuário logado."}), 400
        result = aplicar_campanha_pedido(
            cur,
            int(id_cliente),
            int(nropedido),
            str(origem),
            int(campanha_id),
            cod_usuario=cod_usuario,
            insert_line=_insert_pedido_diarios_from_casa,
        )
        conn.commit()
        return jsonify(result)
    except CampanhaError as e:
        if conn:
            conn.rollback()
        return jsonify({"sucesso": False, "erro": str(e)}), 400
    except Exception as e:
        if conn:
            conn.rollback()
        print("[APLICAR CAMPANHA]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@campanhas_bp.route("/api/casa/<int:nropedido>/campanha", methods=["DELETE"])
@login_required
def api_remover_campanha_pedido(nropedido: int):
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
    origem = request.args.get("origem")
    if not _origem_valida(origem):
        return jsonify({"sucesso": False, "erro": "Informe origem válida."}), 400
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        if _casa_pedido_bloqueado(cur, int(id_cliente), nropedido, origem):
            return jsonify({"sucesso": False, "erro": _MSG_CASA_BLOQUEADO}), 409
        remover_campanhas_pedido(cur, int(id_cliente), int(nropedido), origem)
        conn.commit()
        return jsonify({"sucesso": True, "taxa_entrega_zerada": False})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
