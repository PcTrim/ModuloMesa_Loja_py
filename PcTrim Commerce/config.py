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

    MYSQL_DATABASE_INTERNO = (os.environ.get("MYSQL_DATABASE_INTERNO") or "interno").strip()
    MYSQL_INTERN_CONNECT_TIMEOUT = int(os.environ.get("MYSQL_INTERN_CONNECT_TIMEOUT", "5"))

    # WhatsApp(s) que recebem aviso de comprovante de pagamento (vírgula)
    FINANCEIRO_AVISO_WHATSAPP = [
        p.strip()
        for p in (os.environ.get("FINANCEIRO_AVISO_WHATSAPP") or "").split(",")
        if p.strip()
    ]

    # --- uazapi (WhatsApp) — opcional, não obrigatório ---
    # URL do servidor uazapi (mesmo subdomínio para todas as lojas).
    UZAPI_URL = (os.environ.get("UZAPI_URL", "") or "").strip().rstrip("/")
    # Token de administrador do servidor (nível servidor): cria/gerencia instâncias.
    # Aceita UZAPI_ADMIN_TOKEN ou UZAPI_ADMTOKEN (nome curto usado no painel).
    UZAPI_ADMIN_TOKEN = (
        os.environ.get("UZAPI_ADMIN_TOKEN", "")
        or os.environ.get("UZAPI_ADMTOKEN", "")
        or os.environ.get("admintoken", "")
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

    @classmethod
    def is_production(cls) -> bool:
        return cls.ENVIRONMENT in ("production", "prod")

    @classmethod
    def is_homologation(cls) -> bool:
        return cls.ENVIRONMENT in ("homologation", "homolog", "hml", "staging")

    @classmethod
    def runtime_is_homologation(cls) -> bool:
        """True se o app está de fato em homologação (ENVIRONMENT ou banco HML)."""
        return cls.is_homologation() or cls._db_name_is_hml(cls.MYSQL_DATABASE)

    @classmethod
    def environment_label(cls) -> str | None:
        if cls.runtime_is_homologation():
            return "HOMOLOGAÇÃO"
        db = (cls.MYSQL_DATABASE or "").strip().lower()
        if cls.is_production() or db == "pctrim_commerce":
            return "PRODUÇÃO"
        return None

    @classmethod
    def environment_banner(cls) -> tuple[str | None, str | None]:
        """Texto e tipo do banner de ambiente (texto, kind)."""
        if cls.runtime_is_homologation():
            return (
                "AMBIENTE DE HOMOLOGAÇÃO — dados podem ser descartados",
                "hml",
            )
        return None, None

    ADMIN_DB_TARGETS = frozenset({"production", "homologation"})

    @classmethod
    def _db_name_is_hml(cls, database: str | None) -> bool:
        name = (database or "").strip().lower()
        return "hml" in name or "homolog" in name or name.endswith("_staging")

    @classmethod
    def admin_db_target_default(cls) -> str:
        """Alvo padrão do cadastro admin conforme MYSQL_DATABASE do .env."""
        if cls._db_name_is_hml(cls.MYSQL_DATABASE):
            return "homologation"
        return "production"

    @classmethod
    def admin_db_profile(cls, target: str) -> dict:
        """Credenciais MySQL para cadastro admin (prod ou homologação)."""
        target = (target or "").strip().lower()
        if target not in cls.ADMIN_DB_TARGETS:
            raise ValueError(f"Alvo de banco inválido: {target}")

        host = cls.MYSQL_HOST
        port = cls.MYSQL_PORT
        current_is_hml = cls._db_name_is_hml(cls.MYSQL_DATABASE)

        if target == "homologation":
            database = (os.environ.get("MYSQL_DATABASE_HML") or "pctrim_commerce_hml").strip()
            user = (os.environ.get("MYSQL_USER_HML") or "").strip()
            password = os.environ.get("MYSQL_PASSWORD_HML") or ""
            if not user:
                user = cls.MYSQL_USER if current_is_hml else "pctrim_hml"
            if not password and current_is_hml:
                password = cls.MYSQL_PASSWORD
            label = "Homologação"
        else:
            database = (os.environ.get("MYSQL_DATABASE_PROD") or "pctrim_commerce").strip()
            user = (os.environ.get("MYSQL_USER_PROD") or "").strip()
            password = os.environ.get("MYSQL_PASSWORD_PROD") or ""
            if not user:
                user = cls.MYSQL_USER if not current_is_hml else "root"
            if not password and not current_is_hml:
                password = cls.MYSQL_PASSWORD
            label = "Produção"

        return {
            "target": target,
            "label": label,
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
        }

    @classmethod
    def interno_db_profile(cls) -> dict:
        """Credenciais MySQL da base interna (cadastro de clientes PcTrim)."""
        host = (os.environ.get("MYSQL_HOST_INTERNO") or cls.MYSQL_HOST).strip()
        port = int(os.environ.get("MYSQL_PORT_INTERNO") or cls.MYSQL_PORT)
        user = (os.environ.get("MYSQL_USER_INTERNO") or cls.MYSQL_USER).strip()
        password = os.environ.get("MYSQL_PASSWORD_INTERNO")
        if password is None or password == "":
            password = cls.MYSQL_PASSWORD
        return {
            "label": "Interno",
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": cls.MYSQL_DATABASE_INTERNO,
            "connect_timeout": cls.MYSQL_INTERN_CONNECT_TIMEOUT,
        }

    @classmethod
    def interno_db_configured(cls) -> bool:
        profile = cls.interno_db_profile()
        return bool(profile.get("password") and profile.get("user") and profile.get("database"))

    @classmethod
    def admin_db_configured(cls, target: str) -> bool:
        """True se credenciais do banco admin (prod ou HML) estão disponíveis."""
        try:
            profile = cls.admin_db_profile(target)
        except ValueError:
            return False
        return bool(profile.get("password") and profile.get("user") and profile.get("database"))

    @classmethod
    def validate_database_environment(cls) -> None:
        """Valida combinação banco+usuário+ambiente (só usuários dedicados pctrim_*)."""
        db = (cls.MYSQL_DATABASE or "").strip()
        user = (cls.MYSQL_USER or "").strip()
        if user == "pctrim_prod":
            if db != "pctrim_commerce":
                raise RuntimeError("pctrim_prod exige MYSQL_DATABASE=pctrim_commerce")
            if not cls.is_production():
                raise RuntimeError("pctrim_prod exige ENVIRONMENT=production")
        elif user == "pctrim_hml":
            if db != "pctrim_commerce_hml":
                raise RuntimeError("pctrim_hml exige MYSQL_DATABASE=pctrim_commerce_hml")
            if not cls.is_homologation():
                raise RuntimeError("pctrim_hml exige ENVIRONMENT=homologation")

    @classmethod
    def require_non_production(cls, reason: str) -> None:
        if cls.is_production():
            raise RuntimeError(f"Bloqueado em produção: {reason}")

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
        cls.validate_database_environment()
