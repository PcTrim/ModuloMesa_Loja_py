"""
Rotas de autenticação (login) — blueprint separado do monólito app.py.
"""

from __future__ import annotations

import secrets
import traceback

import mysql.connector
from flask import Blueprint, jsonify, render_template, request, session, url_for

from auth_validation import (
    collect_empty_login_fields,
    parse_login_json,
    validate_login_csrf,
)
from database import conectar
from models import AUTH_CREDENTIALS_INVALID_MSG, UsuarioAuthRow, normalize_funcao
from services.login_otp import OTP_MSG_GENERIC, solicitar_codigo_whatsapp, validar_codigo_whatsapp
from services.passwords import hash_password, password_is_bcrypt, verify_password

auth_bp = Blueprint("auth", __name__)


def _issue_login_csrf() -> str:
    token = secrets.token_urlsafe(32)
    session["login_csrf"] = token
    return token


def _fetch_user_row(cursor, usuario: str):
    row = None
    try:
        cursor.execute(
            """
            SELECT usuario, senha, id_cliente, funcao, ativo
            FROM usuarios WHERE usuario = %s LIMIT 1
            """,
            (usuario,),
        )
        row = cursor.fetchone()
    except mysql.connector.Error as col_err:
        if getattr(col_err, "errno", None) != 1054:
            raise
        try:
            cursor.execute(
                "SELECT usuario, senha, id_cliente, funcao FROM usuarios WHERE usuario = %s LIMIT 1",
                (usuario,),
            )
            row = cursor.fetchone()
        except mysql.connector.Error:
            cursor.execute(
                "SELECT usuario, senha, id_cliente FROM usuarios WHERE usuario = %s LIMIT 1",
                (usuario,),
            )
            row = cursor.fetchone()
    return row


def _user_is_inactive(row) -> bool:
    if row is None or not isinstance(row, dict):
        return False
    ativo_val = row.get("ativo")
    return ativo_val is not None and int(ativo_val) == 0


def _complete_login_response(user: UsuarioAuthRow):
    session["usuario_logado"] = user.usuario
    session["id_cliente"] = user.id_cliente
    session["funcao"] = normalize_funcao(user.funcao)
    session.pop("login_csrf", None)

    id_cliente = user.id_cliente
    conn2 = None
    cursor2 = None
    try:
        conn2 = conectar()
        cursor2 = conn2.cursor(dictionary=True)
        cursor2.execute(
            "SELECT 1 FROM dadosloja WHERE id_cliente = %s LIMIT 1",
            (id_cliente,),
        )
        dadosloja_existe = cursor2.fetchone()
    finally:
        if cursor2:
            cursor2.close()
        if conn2:
            conn2.close()

    if not dadosloja_existe:
        return jsonify(
            {
                "sucesso": True,
                "redirecionar": "/dados-loja",
                "mensagem": "Complete os dados da loja",
                "id_cliente": id_cliente,
            }
        )
    return jsonify(
        {
            "sucesso": True,
            "mensagem": "Login realizado com sucesso",
            "id_cliente": id_cliente,
        }
    )


@auth_bp.route("/login", methods=["GET"])
def login_page():
    """Splash e redirecionamento para o formulário em /login/form (token CSRF emitido lá)."""
    return render_template(
        "splash.html",
        delay_ms=4000,
        redirect_url=url_for("auth.login_form"),
    )


@auth_bp.route("/login/form", methods=["GET"])
def login_form():
    """Página de login com token CSRF na sessão."""
    token = _issue_login_csrf()
    return render_template("login.html", csrf_token=token)


@auth_bp.route("/login/solicitar-codigo", methods=["POST"])
def login_solicitar_codigo():
    """Envia OTP por WhatsApp (instância central). Resposta genérica anti-enumeração."""
    data = request.get_json(silent=True) or {}
    usuario = str(data.get("usuario") or "").strip()
    csrf_token = data.get("csrf_token") or data.get("csrf")

    if not usuario:
        return (
            jsonify(
                {
                    "sucesso": False,
                    "codigo": "campos_obrigatorios",
                    "erro": "Informe o usuário.",
                    "campos_invalidos": ["usuario"],
                }
            ),
            400,
        )

    if not validate_login_csrf(session.get("login_csrf"), csrf_token):
        return (
            jsonify(
                {
                    "sucesso": False,
                    "codigo": "csrf_invalido",
                    "erro": "Sessão de segurança expirada. Atualize a página e tente novamente.",
                }
            ),
            403,
        )

    result = solicitar_codigo_whatsapp(usuario, session)
    body = {"sucesso": True, "mensagem": OTP_MSG_GENERIC}
    if result.get("enviado") and result.get("whatsapp_mascara"):
        body["whatsapp_mascara"] = result["whatsapp_mascara"]
        return jsonify(body)

    codigo_erro = result.get("codigo_erro")
    if codigo_erro == "whatsapp_desconectado":
        return jsonify(
            {
                "sucesso": False,
                "codigo": codigo_erro,
                "erro": (
                    "WhatsApp do sistema está desconectado. "
                    "Use login por senha ou peça ao suporte para reconectar no painel uazapi."
                ),
            }
        ), 503
    if codigo_erro == "whatsapp_nao_configurado":
        return jsonify(
            {
                "sucesso": False,
                "codigo": codigo_erro,
                "erro": "Envio por WhatsApp não configurado no servidor (UZAPI_URL / UZAPI_TOKEN).",
            }
        ), 503
    if codigo_erro == "rate_limit":
        return jsonify(
            {
                "sucesso": False,
                "codigo": codigo_erro,
                "erro": "Aguarde 1 minuto antes de solicitar outro código.",
            }
        ), 429
    return jsonify(body)


@auth_bp.route("/login", methods=["POST"])
def login():
    """Autenticação por senha ou código WhatsApp."""
    payload = parse_login_json(request.get_json(silent=True))

    vazios = collect_empty_login_fields(
        payload.usuario,
        payload.senha,
        metodo=payload.metodo,
        codigo=payload.codigo,
    )
    if vazios:
        msg = (
            "Preencha usuário e código."
            if payload.metodo == "whatsapp"
            else "Preencha usuário e senha."
        )
        return (
            jsonify(
                {
                    "sucesso": False,
                    "codigo": "campos_obrigatorios",
                    "erro": msg,
                    "campos_invalidos": vazios,
                }
            ),
            400,
        )

    if not validate_login_csrf(session.get("login_csrf"), payload.csrf_token):
        return (
            jsonify(
                {
                    "sucesso": False,
                    "codigo": "csrf_invalido",
                    "erro": "Sessão de segurança expirada. Atualize a página e tente novamente.",
                }
            ),
            403,
        )

    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)

        row = _fetch_user_row(cursor, payload.usuario)
        user = UsuarioAuthRow.from_db_row(row)

        if _user_is_inactive(row):
            return (
                jsonify({"sucesso": False, "erro": AUTH_CREDENTIALS_INVALID_MSG}),
                401,
            )

        if payload.metodo == "whatsapp":
            if user is None or not validar_codigo_whatsapp(payload.usuario, payload.codigo):
                return (
                    jsonify({"sucesso": False, "erro": AUTH_CREDENTIALS_INVALID_MSG}),
                    401,
                )
            assert user is not None
            return _complete_login_response(user)

        senha_ok = user is not None and verify_password(user.senha, payload.senha)
        if not senha_ok:
            return (
                jsonify({"sucesso": False, "erro": AUTH_CREDENTIALS_INVALID_MSG}),
                401,
            )

        assert user is not None

        if user.senha and not password_is_bcrypt(user.senha):
            novo_hash = hash_password(payload.senha)
            cursor.execute(
                "UPDATE usuarios SET senha = %s WHERE usuario = %s",
                (novo_hash, user.usuario),
            )
            conn.commit()

        return _complete_login_response(user)

    except mysql.connector.Error as db_err:
        print("[DB ERROR LOGIN]", db_err)
        traceback.print_exc()
        return (
            jsonify(
                {
                    "sucesso": False,
                    "erro": "Não foi possível validar o login no momento. Tente novamente.",
                }
            ),
            500,
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
