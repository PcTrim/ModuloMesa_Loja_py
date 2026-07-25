"""Confirma impressão feita no Print Bridge (PC local) — registrado em wsgi.py."""
from flask import jsonify, request, session

from app import _confirmar_pedido_casa_pos_impressao
from decorators import login_required


def register_impressao_confirm(flask_app):
    @flask_app.route("/api/casa/confirmar-impressao", methods=["POST"])
    @login_required
    def confirmar_impressao_web():
        dados = request.get_json(silent=True) or {}
        origem = (dados.get("origem") or "").strip().lower()
        origem_fc = origem in ("fechamento_caixa", "fechamento")
        try:
            nropedido = int(dados.get("nropedido", 0) or 0)
        except (TypeError, ValueError):
            nropedido = 0
        printer = str(dados.get("printer", "") or "").strip() or "bridge-local"

        if origem == "casa" and nropedido > 0 and not origem_fc:
            err_resp = _confirmar_pedido_casa_pos_impressao(session.get("id_cliente"), nropedido, dados)
            if err_resp is not None:
                return err_resp

        return jsonify({
            "sucesso": True,
            "printer": printer,
            "via": "confirmar",
            "copias": int(dados.get("copias", 1) or 1),
        })
