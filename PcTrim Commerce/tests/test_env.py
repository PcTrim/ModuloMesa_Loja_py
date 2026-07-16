"""Ambiente unificado para testes que precisam de MySQL.

Variáveis (preferidas):
  TEST_DB_HOST, TEST_DB_PORT, TEST_DB_NAME, TEST_DB_USER, TEST_DB_PASS

Fallback: MYSQL_HOST / MYSQL_PORT / MYSQL_DATABASE / MYSQL_USER / MYSQL_PASSWORD
(e depois load_dotenv do .env do app, se ainda faltar).

REQUIRE_TEST_DB=1 → exige TEST_DB_* explícito (não usa produção silenciosamente).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1]
_APPLIED = False


def _truthy(v: Optional[str]) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "s", "sim")


def aplicar_env_teste(*, load_dotenv_fallback: bool = True) -> dict[str, str]:
    """Aplica TEST_DB_* (ou fallback MYSQL_*) no ambiente. Idempotente."""
    global _APPLIED
    if load_dotenv_fallback:
        try:
            from dotenv import load_dotenv

            load_dotenv(_ROOT / ".env")
        except Exception:
            pass

    require = _truthy(os.environ.get("REQUIRE_TEST_DB"))
    mapping = {
        "TEST_DB_HOST": ("MYSQL_HOST", "127.0.0.1"),
        "TEST_DB_PORT": ("MYSQL_PORT", "3308"),
        "TEST_DB_NAME": ("MYSQL_DATABASE", ""),
        "TEST_DB_USER": ("MYSQL_USER", ""),
        "TEST_DB_PASS": ("MYSQL_PASSWORD", ""),
    }
    resolved: dict[str, str] = {}
    for test_key, (mysql_key, default) in mapping.items():
        val = (os.environ.get(test_key) or "").strip()
        if not val:
            if require and test_key in ("TEST_DB_HOST", "TEST_DB_NAME", "TEST_DB_USER"):
                raise RuntimeError(
                    f"{test_key} obrigatório com REQUIRE_TEST_DB=1 "
                    "(não use produção silenciosamente)."
                )
            val = (os.environ.get(mysql_key) or default or "").strip()
        resolved[test_key] = val
        if test_key == "TEST_DB_HOST" and val:
            os.environ["MYSQL_HOST"] = val
        elif test_key == "TEST_DB_PORT" and val:
            os.environ["MYSQL_PORT"] = val
        elif test_key == "TEST_DB_NAME" and val:
            os.environ["MYSQL_DATABASE"] = val
            # Preferência explícita de teste também em perfil PROD do Config
            os.environ.setdefault("MYSQL_DATABASE_PROD", val)
        elif test_key == "TEST_DB_USER" and val:
            os.environ["MYSQL_USER"] = val
        elif test_key == "TEST_DB_PASS":
            os.environ["MYSQL_PASSWORD"] = val
            if val:
                os.environ.setdefault("MYSQL_PASSWORD_PROD", val)

    os.environ.setdefault("FLASK_SECRET_KEY", "test-suite-secret")
    _APPLIED = True
    return resolved


def test_db_configured() -> bool:
    """True se há host+nome+user mínimos para tentar conectar."""
    aplicar_env_teste()
    return bool(
        os.environ.get("MYSQL_HOST")
        and os.environ.get("MYSQL_DATABASE")
        and os.environ.get("MYSQL_USER")
    )


def conectar_teste():
    """Abre conexão via database.conectar() após aplicar_env_teste."""
    aplicar_env_teste()
    from database import conectar

    return conectar()


def skip_unless_test_db(unittest_module: Any = None):
    """Decorator/module helper: skip se MySQL de teste indisponível."""
    import unittest

    reason = "Dependência de ambiente externo (MySQL/E2E)"

    def _check() -> bool:
        if not test_db_configured():
            return False
        try:
            conn = conectar_teste()
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.close()
            finally:
                conn.close()
            return True
        except Exception:
            return False

    return unittest.skipUnless(_check(), reason)
