"""Versão visível da aplicação (topbar). Incrementar a cada release."""

import os
import re

APP_VERSION = "265-4"

_VERSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.py")
_VERSION_RE = re.compile(r"""^APP_VERSION\s*=\s*["']([^"']+)["']""", re.M)


def get_app_version() -> str:
    """Lê APP_VERSION do arquivo (evita valor preso em import long-lived)."""
    try:
        with open(_VERSION_FILE, encoding="utf-8") as f:
            match = _VERSION_RE.search(f.read())
            if match:
                return match.group(1)
    except OSError:
        pass
    return APP_VERSION
