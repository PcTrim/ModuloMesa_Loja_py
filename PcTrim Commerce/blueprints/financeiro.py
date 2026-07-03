"""API financeira — inadimplência por loja."""
from flask import Blueprint, jsonify, request, session

from decorators import login_required
from services.financeiro_aviso_pagamento import AvisoPagamentoError, enviar_aviso_pagamento
from services.financeiro_inadimplencia import get_status_financeiro

financeiro_bp = Blueprint("financeiro", __name__)


@financeiro_bp.route("/financeiro/status", methods=["GET"])
@login_required
def financeiro_status():
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({
            "temAVencer": False,
            "temVencidas": False,
            "diasAtrasoMax": 0,
            "bloqueadoVenda": False,
        })
    return jsonify(get_status_financeiro(id_cliente))


@financeiro_bp.route("/financeiro/avisar-pagamento", methods=["POST"])
@login_required
def financeiro_avisar_pagamento():
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401

    arquivo = request.files.get("comprovante")
    observacao = request.form.get("observacao") or ""
    try:
        result = enviar_aviso_pagamento(id_cliente, arquivo, observacao=observacao)
        return jsonify(result)
    except AvisoPagamentoError as e:
        return jsonify({"sucesso": False, "erro": e.message}), e.status
    except Exception:
        return jsonify({"sucesso": False, "erro": "Não foi possível enviar o comprovante."}), 500
