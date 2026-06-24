"""Application configuration from environment (python-dotenv)."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY")

    MYSQL_HOST = os.environ.get("MYSQL_HOST", "92.113.33.100")
    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "pctrim")
    MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3308"))
    MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "loja2001")

    # --- uazapi (WhatsApp) — opcional, não obrigatório ---
    # URL do servidor uazapi (mesmo subdomínio para todas as lojas).
    UZAPI_URL = (os.environ.get("UZAPI_URL", "") or "").strip().rstrip("/")
    # Token de administrador do servidor (nível servidor): cria/gerencia instâncias.
    # Aceita UZAPI_ADMIN_TOKEN ou UZAPI_ADMTOKEN (nome curto usado no painel).
    UZAPI_ADMIN_TOKEN = (
        os.environ.get("UZAPI_ADMIN_TOKEN", "")
        or os.environ.get("UZAPI_ADMTOKEN", "")
        or ""
    ).strip()
    # Token de instância legado do .env (fallback/dev). O token "oficial" é por loja, no banco.
    UZAPI_TOKEN = (os.environ.get("UZAPI_TOKEN", "") or "").strip()
    # DDI padrão para normalização de telefone (Brasil = 55).
    UZAPI_DDI_PADRAO = (os.environ.get("UZAPI_DDI_PADRAO", "55") or "55").strip()

    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes")
    SESSION_COOKIE_DOMAIN = os.environ.get("SESSION_COOKIE_DOMAIN") or None

    FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    LOG_SESSION_DEBUG = os.environ.get("LOG_SESSION_DEBUG", "").lower() in ("1", "true", "yes")
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").lower()

    # Subpath em produção (ex.: https://pedidofacil.online/LojaOnline/). Vazio = raiz.
    _raw_prefix = (os.environ.get("LOJA_URL_PREFIX") or "").strip()
    URL_PREFIX = ("/" + _raw_prefix.strip("/")) if _raw_prefix else ""

    # Logins com acesso à área /admin/lojas (equipe técnica / suporte). Separados por vírgula.
    _platform_admins = (os.environ.get("PLATFORM_ADMIN_USERS") or "").strip()
    PLATFORM_ADMIN_USERS = frozenset(
        u.strip().lower() for u in _platform_admins.split(",") if u.strip()
    )

    @classmethod
    def is_platform_admin(cls, usuario: str | None) -> bool:
        raw = (os.environ.get("PLATFORM_ADMIN_USERS") or "").strip()
        admins = frozenset(u.strip().lower() for u in raw.split(",") if u.strip())
        if not admins or not usuario:
            return False
        return str(usuario).strip().lower() in admins

    @classmethod
    def validate_required(cls):
        if not cls.SECRET_KEY and cls.ENVIRONMENT in ("development", "dev", "local"):
            # Não bloquear ambiente local; em produção continua obrigatório via variável.
            cls.SECRET_KEY = "dev-only-change-me"

        missing = []
        if not cls.SECRET_KEY:
            missing.append("FLASK_SECRET_KEY (ou SECRET_KEY)")
        if cls.ENVIRONMENT in ("production", "prod"):
            if not cls.MYSQL_PASSWORD:
                missing.append("MYSQL_PASSWORD")
            # MySQL no mesmo servidor (Hostinger) usa 127.0.0.1 — permitido em produção.
        if missing:
            raise RuntimeError("Configuração obrigatória ausente: " + ", ".join(missing))
