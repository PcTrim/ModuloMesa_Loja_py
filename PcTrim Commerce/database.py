"""MySQL connection helper."""
import os
from contextlib import contextmanager

import mysql.connector

TENANT_DB_SESSION_KEY = "tenant_db_target"


def resolve_tenant_db_target(session=None):
    """Banco MySQL da loja logada — lê dadosloja.ambiente (atualiza cache na sessão)."""
    from config import Config

    if session is None:
        try:
            from flask import has_request_context, session as flask_session

            if has_request_context():
                session = flask_session
        except ImportError:
            pass

    if session is not None:
        id_cliente = session.get("id_cliente")
        if id_cliente is not None:
            from services.loja_ambiente import fetch_loja_ambiente_for_cliente

            target = fetch_loja_ambiente_for_cliente(id_cliente)
            if session.get(TENANT_DB_SESSION_KEY) != target:
                session[TENANT_DB_SESSION_KEY] = target
                if hasattr(session, "modified"):
                    session.modified = True
            return target

        raw = session.get(TENANT_DB_SESSION_KEY)
        if raw in Config.ADMIN_DB_TARGETS:
            return raw
    return None


def _connect_profile(profile: dict):
    host = profile["host"]
    user = profile["user"]
    password = profile["password"]
    port = int(profile["port"] or 3308)
    database = profile["database"]
    if not all([host, user, port, database]):
        raise Exception(f"Credenciais incompletas para base {profile.get('label', database)}")
    if password is None or password == "":
        raise Exception(
            f"Senha ausente para base {profile.get('label', database)} ({database})."
        )
    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        port=port,
        database=database,
        autocommit=False,
    )


def conectar_admin(target: str, session=None):
    """Conexão MySQL explícita em produção ou homologação (cadastro admin / login)."""
    from config import Config

    if not target:
        raise ValueError("conectar_admin exige target=production ou homologation")
    if not Config.admin_db_configured(target):
        profile = Config.admin_db_profile(target)
        raise Exception(
            f"Senha ausente para base {profile['label']} ({profile['database']}). "
            f"Configure MYSQL_PASSWORD_{'HML' if target == 'homologation' else 'PROD'} no .env."
        )
    profile = Config.admin_db_profile(target)
    return _connect_profile(profile)


def conectar_admin_optional(target: str, session=None):
    """Conexão admin ou None se credenciais do banco não estão configuradas."""
    from config import Config

    if not target or not Config.admin_db_configured(target):
        return None
    profile = Config.admin_db_profile(target)
    return _connect_profile(profile)


def conectar():
    """Conexão MySQL — loja logada usa banco de dadosloja.ambiente; demais casos = produção."""
    from config import Config

    Config.validate_database_environment()

    target = resolve_tenant_db_target()
    if target:
        return conectar_admin(target)

    # Bootstrap / scripts / pré-login: produção (não usa MYSQL_DATABASE do .env para roteamento)
    profile = Config.admin_db_profile("production")
    if profile.get("password"):
        return _connect_profile(profile)

    host = os.getenv("MYSQL_HOST")
    user = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PASSWORD")
    port = int(os.getenv("MYSQL_PORT") or 3308)
    database = os.getenv("MYSQL_DATABASE")
    if not all([host, user, password, port, database]):
        raise Exception("Missing MySQL environment variables")
    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        port=port,
        database=database,
        autocommit=False,
    )


@contextmanager
def transaction():
    conn = conectar()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
