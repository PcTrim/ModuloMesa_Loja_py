"""

Print Bridge — impressão local no Windows para o LojaOnline na web.

Duplo clique: iniciar-print-bridge.bat

"""

from __future__ import annotations



import getpass
import os
import re
import socket
import sys



from flask import Flask, jsonify, request

from flask_cors import CORS



from printer_core import list_installed_printers, send_to_printer_resolved



app = Flask(__name__)

# Bridge só escuta 127.0.0.1 — CORS aberto evita bloqueio por origem (pedidofacil / localhost:5000).

CORS(

    app,

    resources={

        r"/*": {

            "origins": "*",

            "methods": ["GET", "POST", "OPTIONS"],

            "allow_headers": ["Content-Type"],

        }

    },

)





@app.after_request

def _cors_private_network(resp):

    """Chrome: site HTTPS → http://127.0.0.1 (Private Network Access)."""

    resp.headers["Access-Control-Allow-Private-Network"] = "true"

    return resp





def get_terminal_id():
    host = (socket.gethostname() or "HOST").strip()
    user = (getpass.getuser() or "USER").strip()
    raw = f"{host}-{user}"
    tid = re.sub(r"[^A-Z0-9_-]", "", raw.upper().replace(" ", ""))
    return tid[:120] if tid else "TERMINAL"


@app.route("/health", methods=["GET", "OPTIONS"])

def health():

    return jsonify({

        "ok": True,

        "platform": sys.platform,

        "pywin32": win32print_ok(),

        "terminal_id": get_terminal_id(),

        "impressoras_windows": list_installed_printers()[:20],

    })





def win32print_ok():

    try:

        import win32print  # noqa: F401

        return True

    except Exception:

        return False





@app.route("/imprimir", methods=["POST", "OPTIONS"])

def imprimir():

    if request.method == "OPTIONS":

        return "", 204

    if sys.platform != "win32":

        return jsonify({"sucesso": False, "erro": "Print Bridge requer Windows."}), 400

    dados = request.get_json(silent=True) or {}

    conteudo = str(dados.get("conteudo", "") or "").strip()

    if not conteudo:

        return jsonify({"sucesso": False, "erro": "Conteúdo vazio."}), 400

    try:

        copias = int(dados.get("copias", 1) or 1)

    except (TypeError, ValueError):

        return jsonify({"sucesso": False, "erro": "Cópias inválidas."}), 400

    copias = max(1, min(5, copias))

    printer_cadastro = str(dados.get("printer", "") or "").strip()

    if not printer_cadastro:

        return jsonify({

            "sucesso": False,

            "erro": "Impressora não informada (cadastro MySQL).",

        }), 400

    marca = dados.get("marca_impressora")

    erros = []

    printer_windows = None

    for i in range(copias):

        ok, err, pw = send_to_printer_resolved(conteudo, printer_cadastro, marca)

        if pw:

            printer_windows = pw

        if not ok:

            erros.append(f"Cópia {i + 1}: {err}")

    if erros:

        disp = list_installed_printers()

        return jsonify({

            "sucesso": False,

            "erro": "; ".join(erros),

            "printer": printer_cadastro,

            "printer_windows": printer_windows,

            "impressoras_disponiveis": disp[:15] if disp else [],

        }), 500

    return jsonify({

        "sucesso": True,

        "printer": printer_cadastro,

        "printer_windows": printer_windows,

        "copias": copias,

        "via": "bridge",

    })





if __name__ == "__main__":

    port = int(os.environ.get("PRINT_BRIDGE_PORT", "9123"))

    if not win32print_ok():

        print("[ERRO] Instale pywin32: pip install pywin32")

        input("Enter para sair...")

        sys.exit(1)

    print(f"Print Bridge em http://127.0.0.1:{port}")

    print("Deixe esta janela ABERTA. Teste: /health")

    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


