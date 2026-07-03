"""Shared Flask route decorators."""
from functools import wraps

from flask import flash, jsonify, redirect, request, session, url_for

from config import Config
from models import normalize_funcao
from services.business_mode import is_retail


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
            flash(
                "Acesso restrito. Seu usuário não está autorizado a cadastrar lojas (PLATFORM_ADMIN_USERS).",
                "error",
            )
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function


def restaurant_only(f):
    """Bloqueia rotas de mesa/delivery/entrega em lojas varejo."""

    @wraps(f)
    def wrapped(*args, **kwargs):
        if is_retail():
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"sucesso": False, "erro": "Recurso indisponível no modo varejo."}), 403
            return redirect(url_for("casa") + "?modo=balcao")
        return f(*args, **kwargs)

    return wrapped


def retail_only(f):
    """Restringe rotas ao catálogo retail (lojas varejo)."""

    @wraps(f)
    def wrapped(*args, **kwargs):
        if not is_retail():
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"sucesso": False, "erro": "Recurso disponível apenas no modo varejo."}), 403
            return redirect(url_for("configuracoes"))
        return f(*args, **kwargs)

    return wrapped


def gerente_required(f):
    """Restringe rotas a usuários com funcao gerente na sessão."""

    @wraps(f)
    def wrapped(*args, **kwargs):
        if normalize_funcao(session.get("funcao")) != "gerente":
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"sucesso": False, "erro": "Acesso restrito a gerentes."}), 403
            return redirect(url_for("configuracoes"))
        return f(*args, **kwargs)

    return wrapped
