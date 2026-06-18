"""Confirma impressão feita no Print Bridge (PC local) — registrado em wsgi.py."""
from flask import jsonify, request, session

from database import conectar
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
            conn_status = None
            cur_status = None
            try:
                conn_status = conectar()
                cur_status = conn_status.cursor()
                id_cliente = session.get("id_cliente")
                cur_status.execute(
                    """
                    UPDATE pedido_diarios
                    SET status_pedido = 'ABERTO'
                    WHERE nropedido = %s
                      AND id_cliente = %s
                      AND origem IN ('DELIVERY','BALCAO')
                      AND UPPER(COALESCE(status_pedido, '')) = 'AGUARDE'
                    """,
                    (nropedido, id_cliente),
                )
                conn_status.commit()
            except Exception as e:
                if conn_status:
                    conn_status.rollback()
                return jsonify({"sucesso": False, "erro": str(e)}), 500
            finally:
                if cur_status:
                    cur_status.close()
                if conn_status:
                    conn_status.close()

        return jsonify({
            "sucesso": True,
            "printer": printer,
            "via": "confirmar",
            "copias": int(dados.get("copias", 1) or 1),
        })
