"""OTP de login via WhatsApp (5 min, uso único)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import traceback
from datetime import datetime, timedelta

from config import Config
from database import conectar_admin
from services import uazapi
from services.login_tenant_db import LoginAmbienteError, locate_login_user

OTP_TTL_MINUTES = 5
OTP_MSG_GENERIC = (
    "Se o usuário existir e tiver WhatsApp cadastrado, enviaremos um código em instantes."
)


def mascara_whatsapp(telefone: str) -> str:
    """Ex.: (11) 9••••-7534"""
    d = "".join(ch for ch in str(telefone or "") if ch.isdigit())
    if len(d) >= 12 and d.startswith("55"):
        d = d[2:]
    if len(d) < 10:
        return "••••"
    ddd = d[:2]
    last4 = d[-4:]
    if len(d) == 11:
        return f"({ddd}) 9••••-{last4}"
    return f"({ddd}) ••••-{last4}"


def _hash_codigo(usuario: str, codigo: str) -> str:
    secret = (Config.SECRET_KEY or "otp-dev").encode()
    msg = f"{usuario.strip().lower()}:{codigo}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def _fetch_usuario_whatsapp(cur, usuario: str) -> dict | None:
    login = str(usuario or "").strip().lower()
    if not login:
        return None
    try:
        cur.execute(
            """
            SELECT usuario, whatsapp, id_cliente, funcao, ativo
            FROM usuarios WHERE LOWER(usuario) = %s LIMIT 1
            """,
            (login,),
        )
    except Exception as e:
        if getattr(e, "errno", None) != 1054:
            raise
        cur.execute(
            "SELECT usuario, id_cliente, funcao, ativo FROM usuarios WHERE LOWER(usuario) = %s LIMIT 1",
            (login,),
        )
    row = cur.fetchone()
    if not row or not isinstance(row, dict):
        return None
    row.setdefault("whatsapp", None)
    row.setdefault("ativo", 1)
    row.setdefault("funcao", "gerente")
    return row


def _gerar_codigo() -> str:
    return f"{secrets.randbelow(900000) + 100000:06d}"


def _formatar_mensagem(usuario: str, codigo: str) -> str:
    c1, c2 = codigo[:3], codigo[3:]
    return (
        f"🔐 *PcTrim Commerce*\n\n"
        f"Seu código de acesso:\n\n"
        f"*{c1} {c2}*\n\n"
        f"⏱ Válido por *5 minutos*\n"
        f"👤 Usuário: *{usuario}*\n\n"
        f"Não compartilhe este código com ninguém."
    )


def _telefone_valido(tel: str) -> bool:
    d = "".join(ch for ch in str(tel or "") if ch.isdigit())
    return len(d) >= 10


def _check_rate_limit(session_store: dict, usuario: str) -> bool:
    """True se pode enviar."""
    now = time.time()
    key = str(usuario or "").strip().lower()
    bucket = session_store.setdefault("otp_send_times", {})
    times = [t for t in bucket.get(key, []) if now - t < 3600]
    if len(times) >= 5:
        return False
    if times and now - times[-1] < 60:
        return False
    times.append(now)
    bucket[key] = times
    return True


def solicitar_codigo_whatsapp(usuario: str, session_store: dict | None = None) -> dict:
    """Retorna {enviado, whatsapp_mascara, codigo_erro?}."""
    session_store = session_store if session_store is not None else {}
    login = str(usuario or "").strip().lower()
    if not login:
        return {"enviado": False, "whatsapp_mascara": None}

    if not _check_rate_limit(session_store, login):
        return {"enviado": False, "whatsapp_mascara": None, "codigo_erro": "rate_limit"}

    if not (Config.UZAPI_URL and Config.UZAPI_TOKEN):
        return {"enviado": False, "whatsapp_mascara": None, "codigo_erro": "whatsapp_nao_configurado"}

    st = uazapi.status_instancia_plataforma()
    if not st.get("connected"):
        print("[LOGIN OTP] instância plataforma desconectada:", st, flush=True)
        return {"enviado": False, "whatsapp_mascara": None, "codigo_erro": "whatsapp_desconectado"}

    conn = None
    cur = None
    try:
        try:
            tenant_target, _row = locate_login_user(login)
        except LoginAmbienteError:
            return {"enviado": False, "whatsapp_mascara": None}

        conn = conectar_admin(tenant_target)
        cur = conn.cursor(dictionary=True)
        row = _fetch_usuario_whatsapp(cur, login)
        if not row:
            return {"enviado": False, "whatsapp_mascara": None}
        if row.get("ativo") is not None and int(row.get("ativo")) == 0:
            return {"enviado": False, "whatsapp_mascara": None}

        whatsapp = str(row.get("whatsapp") or "").strip()
        if not whatsapp or not _telefone_valido(whatsapp):
            return {"enviado": False, "whatsapp_mascara": None}

        codigo = _gerar_codigo()
        expira = datetime.now() + timedelta(minutes=OTP_TTL_MINUTES)
        codigo_hash = _hash_codigo(login, codigo)

        cur.execute(
            "UPDATE usuario_login_otp SET usado = 1 WHERE usuario = %s AND usado = 0",
            (login,),
        )
        cur.execute(
            """
            INSERT INTO usuario_login_otp (usuario, codigo_hash, expira_em, usado)
            VALUES (%s, %s, %s, 0)
            """,
            (login, codigo_hash, expira),
        )
        conn.commit()

        id_cliente = row.get("id_cliente") or 0
        msg = _formatar_mensagem(str(row.get("usuario") or login), codigo)
        result = uazapi.enviar_texto_plataforma(
            whatsapp, msg, evento="login_otp", id_cliente_log=id_cliente
        )
        if not result.get("ok"):
            err = str(result.get("erro") or "").lower()
            print("[LOGIN OTP] falha envio:", result, flush=True)
            codigo_erro = "whatsapp_desconectado" if "disconnect" in err else "whatsapp_falha_envio"
            return {"enviado": False, "whatsapp_mascara": None, "codigo_erro": codigo_erro}

        return {"enviado": True, "whatsapp_mascara": mascara_whatsapp(whatsapp)}
    except Exception as e:
        print("[LOGIN OTP solicitar ERRO]", e, flush=True)
        traceback.print_exc()
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return {"enviado": False, "whatsapp_mascara": None}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def validar_codigo_whatsapp(usuario: str, codigo: str) -> bool:
    login = str(usuario or "").strip().lower()
    digits = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    if not login or len(digits) != 6:
        return False

    codigo_hash = _hash_codigo(login, digits)
    conn = None
    cur = None
    try:
        try:
            tenant_target, _row = locate_login_user(login)
        except LoginAmbienteError:
            return False

        conn = conectar_admin(tenant_target)
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT id FROM usuario_login_otp
            WHERE usuario = %s AND codigo_hash = %s AND usado = 0 AND expira_em > NOW()
            ORDER BY id DESC LIMIT 1
            """,
            (login, codigo_hash),
        )
        row = cur.fetchone()
        if not row:
            return False
        cur.execute("UPDATE usuario_login_otp SET usado = 1 WHERE id = %s", (row["id"],))
        conn.commit()
        return True
    except Exception as e:
        print("[LOGIN OTP validar ERRO]", e, flush=True)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
