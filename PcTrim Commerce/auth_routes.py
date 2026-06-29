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
from services.passwords import hash_password, password_is_bcrypt, verify_password

auth_bp = Blueprint("auth", __name__)


def _issue_login_csrf() -> str:
    token = secrets.token_urlsafe(32)
    session["login_csrf"] = token
    return token


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


@auth_bp.route("/login", methods=["POST"])
def login():
    """Autenticação: mensagens genéricas para credenciais inválidas (anti-enumeração)."""
    payload = parse_login_json(request.get_json(silent=True))

    vazios = collect_empty_login_fields(payload.usuario, payload.senha)
    if vazios:
        return (
            jsonify(
                {
                    "sucesso": False,
                    "codigo": "campos_obrigatorios",
                    "erro": "Preencha usuário e senha.",
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

        row = None
        try:
            cursor.execute(
                "SELECT usuario, senha, id_cliente, funcao, ativo FROM usuarios WHERE usuario = %s LIMIT 1",
                (payload.usuario,),
            )
            row = cursor.fetchone()
        except mysql.connector.Error as col_err:
            if getattr(col_err, "errno", None) != 1054:
                raise
            try:
                cursor.execute(
                    "SELECT usuario, senha, id_cliente, funcao FROM usuarios WHERE usuario = %s LIMIT 1",
                    (payload.usuario,),
                )
                row = cursor.fetchone()
            except mysql.connector.Error:
                cursor.execute(
                    "SELECT usuario, senha, id_cliente FROM usuarios WHERE usuario = %s LIMIT 1",
                    (payload.usuario,),
                )
                row = cursor.fetchone()
        user = UsuarioAuthRow.from_db_row(row)

        if user is not None and isinstance(row, dict):
            ativo_val = row.get("ativo")
            if ativo_val is not None and int(ativo_val) == 0:
                return (
                    jsonify({"sucesso": False, "erro": AUTH_CREDENTIALS_INVALID_MSG}),
                    401,
                )

        senha_ok = user is not None and verify_password(user.senha, payload.senha)
        if not senha_ok:
            return (
                jsonify({"sucesso": False, "erro": AUTH_CREDENTIALS_INVALID_MSG}),
                401,
            )

        assert user is not None
        session["usuario_logado"] = user.usuario
        session["id_cliente"] = user.id_cliente
        session["funcao"] = normalize_funcao(user.funcao)
        session.pop("login_csrf", None)

        # Migração progressiva: se login veio de senha legada em texto, atualiza para bcrypt.
        if user.senha and not password_is_bcrypt(user.senha):
            novo_hash = hash_password(payload.senha)
            cursor.execute(
                "UPDATE usuarios SET senha = %s WHERE usuario = %s",
                (novo_hash, user.usuario),
            )
            conn.commit()

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
