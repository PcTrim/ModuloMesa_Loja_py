"""Shared Flask route decorators."""
from functools import wraps

from flask import jsonify, redirect, request, session, url_for

from config import Config


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario_logado" not in session:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.headers.get(
                "Accept"
            ) == "application/json":
                return jsonify({"sucesso": False, "mensagem": "Sessão expirada ou não autenticada."}), 401
            return redirect(url_for("auth.login_page"))
        return f(*args, **kwargs)

    return decorated_function


def platform_admin_required(f):
    """Restringe rotas à equipe técnica (PLATFORM_ADMIN_USERS no .env)."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario_logado" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"sucesso": False, "erro": "Sessão expirada. Faça login."}), 401
            return redirect(url_for("auth.login_page"))
        if not Config.is_platform_admin(session.get("usuario_logado")):
            if request.path.startswith("/api/"):
                return jsonify({"sucesso": False, "erro": "Acesso restrito à administração da plataforma."}), 403
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function
