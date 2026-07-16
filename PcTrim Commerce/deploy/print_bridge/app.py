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

import json

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

from printer_core import list_installed_printers, send_to_printer_resolved

app = Flask(__name__)

# Bridge só escuta 127.0.0.1 — CORS aberto (VPS 85.31 / pedidofacil / localhost).
CORS(
    app,
    resources={
        r"/*": {
            "origins": "*",
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": [
                "Content-Type",
                "Access-Control-Request-Private-Network",
                "Access-Control-Request-Headers",
            ],
        }
    },
)


def _apply_cors_pna(resp):
    """Chrome/Edge: site público (ex. 85.31) → http://127.0.0.1 (Private Network Access)."""
    origin = (request.headers.get("Origin") or "").strip()
    resp.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    req_headers = request.headers.get("Access-Control-Request-Headers")
    if req_headers:
        resp.headers["Access-Control-Allow-Headers"] = req_headers
    else:
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Private-Network"] = "true"
    # Variante mais nova (Local Network Access)
    resp.headers["Access-Control-Allow-Local-Network"] = "true"
    return resp


@app.after_request
def _cors_private_network(resp):
    return _apply_cors_pna(resp)


def _options_ok():
    return _apply_cors_pna(app.make_response(("", 204)))


def get_terminal_id():
    host = (socket.gethostname() or "HOST").strip()
    user = (getpass.getuser() or "USER").strip()
    raw = f"{host}-{user}"
    tid = re.sub(r"[^A-Z0-9_-]", "", raw.upper().replace(" ", ""))
    return tid[:120] if tid else "TERMINAL"


def win32print_ok():
    try:
        import win32print  # noqa: F401

        return True
    except Exception:
        return False


def _health_payload():
    return {
        "ok": True,
        "platform": sys.platform,
        "pywin32": win32print_ok(),
        "terminal_id": get_terminal_id(),
        "impressoras_windows": list_installed_printers()[:20],
    }


@app.route("/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return _options_ok()
    return jsonify(_health_payload())


@app.route("/pair", methods=["GET", "OPTIONS"])
def pair():
    """Página localhost: envia terminal_id ao opener via postMessage (contorna bloqueio VPS→127.0.0.1)."""
    if request.method == "OPTIONS":
        return _options_ok()
    payload = _health_payload()
    body = json.dumps(payload, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Print Bridge</title>
<style>
body{{font-family:Segoe UI,sans-serif;background:#111;color:#eee;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.box{{max-width:28rem;padding:1.25rem 1.5rem;border:1px solid #333;border-radius:10px;background:#1a1a1a}}
code{{word-break:break-all}}
</style>
</head>
<body>
<div class="box">
<p><strong>Print Bridge</strong> — pairing com o site…</p>
<p>Terminal: <code id="tid"></code></p>
<p id="msg">Pode fechar esta janela.</p>
</div>
<script>
(function(){{
  var payload = {body};
  var tidEl = document.getElementById('tid');
  var msgEl = document.getElementById('msg');
  if (tidEl) tidEl.textContent = payload.terminal_id || '—';
  var msg = {{
    type: 'loja-print-bridge-pair',
    ok: !!payload.ok,
    terminal_id: payload.terminal_id || '',
    impressoras_windows: payload.impressoras_windows || [],
    platform: payload.platform || '',
    pywin32: !!payload.pywin32
  }};
  try {{
    if (window.opener && !window.opener.closed) {{
      window.opener.postMessage(msg, '*');
      if (msgEl) msgEl.textContent = 'Enviado ao site. Fechando…';
      setTimeout(function(){{ try {{ window.close(); }} catch (e) {{}} }}, 400);
    }} else if (msgEl) {{
      msgEl.textContent = 'Abra esta página pelo botão Detectar no site (popup).';
    }}
  }} catch (e) {{
    if (msgEl) msgEl.textContent = 'Falha ao enviar: ' + e;
  }}
}})();
</script>
</body>
</html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/agent", methods=["GET", "OPTIONS"])
def agent():
    """Popup localhost: recebe jobs via postMessage e imprime em /imprimir (mesma origem)."""
    if request.method == "OPTIONS":
        return _options_ok()
    payload = _health_payload()
    body = json.dumps(payload, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Print Bridge Agent</title>
<style>
body{{font-family:Segoe UI,sans-serif;background:#111;color:#eee;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.box{{max-width:28rem;padding:1.25rem 1.5rem;border:1px solid #333;border-radius:10px;background:#1a1a1a}}
code{{word-break:break-all}}
.ok{{color:#86efac}}.err{{color:#fca5a5}}
</style>
</head>
<body>
<div class="box">
<p><strong>Print Bridge Agent</strong></p>
<p>Terminal: <code id="tid"></code></p>
<p id="msg" class="ok">Pronto. Deixe esta janela aberta e imprima pelo PDV — não feche.</p>
</div>
<script>
(function(){{
  var health = {body};
  var tidEl = document.getElementById('tid');
  var msgEl = document.getElementById('msg');
  if (tidEl) tidEl.textContent = health.terminal_id || '—';
  var readySent = false;

  function setMsg(text, ok) {{
    if (!msgEl) return;
    msgEl.textContent = text;
    msgEl.className = ok ? 'ok' : 'err';
  }}

  function notifyReady() {{
    if (readySent) return;
    readySent = true;
    try {{
      if (window.opener && !window.opener.closed) {{
        window.opener.postMessage({{
          type: 'loja-print-bridge-agent-ready',
          ok: true,
          terminal_id: health.terminal_id || '',
          impressoras_windows: health.impressoras_windows || [],
          platform: health.platform || '',
          pywin32: !!health.pywin32
        }}, '*');
      }}
    }} catch (e) {{}}
  }}

  async function handlePrint(ev) {{
    var d = ev && ev.data;
    if (!d || d.type !== 'loja-print-bridge-print') return;
    var jobId = d.jobId || '';
    var payload = d.payload || {{}};
    setMsg('Imprimindo…', true);
    var result = {{
      type: 'loja-print-bridge-print-result',
      jobId: jobId,
      ok: false,
      status: 0,
      data: {{}},
      printer: payload.printer || null,
      erro: null
    }};
    try {{
      var r = await fetch('/imprimir', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(payload)
      }});
      var j = await r.json().catch(function(){{ return {{}}; }});
      var ok = r.ok && j.sucesso !== false;
      result.ok = ok;
      result.status = r.status;
      result.data = j;
      result.printer = j.printer || payload.printer || null;
      result.erro = ok ? null : (j.erro || j.mensagem || ('HTTP ' + r.status));
      setMsg(ok ? 'OK — aguardando próximo job.' : ('Erro: ' + result.erro), ok);
    }} catch (e) {{
      result.erro = String((e && e.message) || e || 'Falha ao imprimir');
      setMsg('Erro: ' + result.erro, false);
    }}
    try {{
      if (ev.source) ev.source.postMessage(result, '*');
      else if (window.opener && !window.opener.closed) window.opener.postMessage(result, '*');
    }} catch (e2) {{}}
  }}

  window.addEventListener('message', handlePrint);
  notifyReady();
  setTimeout(notifyReady, 200);
}})();
</script>
</body>
</html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/imprimir", methods=["POST", "OPTIONS"])
def imprimir():
    if request.method == "OPTIONS":
        return _options_ok()

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
    terminal_id = str(dados.get("terminal_id") or "").strip()
    origem = str(dados.get("origem") or "").strip().lower()
    if not printer_cadastro:
        return jsonify(
            {
                "sucesso": False,
                "erro": "Impressora não informada (cadastro MySQL).",
            }
        ), 400

    marca = dados.get("marca_impressora")
    erros = []
    printer_windows = None

    print(
        f"[BRIDGE PRINT] terminal_id={terminal_id or '-'} printer={printer_cadastro!r} "
        f"origem={origem or '-'} copias={copias}",
        flush=True,
    )

    for i in range(copias):
        ok, err, pw = send_to_printer_resolved(conteudo, printer_cadastro, marca)
        if pw:
            printer_windows = pw
        if not ok:
            erros.append(f"Cópia {i + 1}: {err}")

    if erros:
        disp = list_installed_printers()
        print(
            f"[BRIDGE PRINT ERRO] terminal_id={terminal_id or '-'} printer={printer_cadastro!r} "
            f"windows={printer_windows!r} erro={'; '.join(erros)}",
            flush=True,
        )
        return jsonify(
            {
                "sucesso": False,
                "erro": "; ".join(erros),
                "printer": printer_cadastro,
                "printer_windows": printer_windows,
                "impressoras_disponiveis": disp[:15] if disp else [],
            }
        ), 500

    print(
        f"[BRIDGE PRINT OK] terminal_id={terminal_id or '-'} printer={printer_cadastro!r} "
        f"windows={printer_windows!r}",
        flush=True,
    )
    return jsonify(
        {
            "sucesso": True,
            "printer": printer_cadastro,
            "printer_windows": printer_windows,
            "copias": copias,
            "via": "bridge",
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PRINT_BRIDGE_PORT", "9123"))
    if not win32print_ok():
        print("[ERRO] Instale pywin32: pip install pywin32")
        input("Enter para sair...")
        sys.exit(1)
    print(f"Print Bridge em http://127.0.0.1:{port}")
    print("Deixe esta janela ABERTA. Teste: /health")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
