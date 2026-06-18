"""
Validação de entrada do login (campos obrigatórios, CSRF).
Mantém regras fora das rotas para facilitar testes e leitura.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LoginPayload:
    usuario: str
    senha: str
    csrf_token: str | None


def parse_login_json(data: dict[str, Any] | None) -> LoginPayload:
    if not data:
        return LoginPayload(usuario="", senha="", csrf_token=None)
    return LoginPayload(
        usuario=str(data.get("usuario") or "").strip(),
        senha=str(data.get("senha") or "").strip(),
        csrf_token=(data.get("csrf_token") or data.get("csrf") or None),
    )


def collect_empty_login_fields(usuario: str, senha: str) -> list[str]:
    """Retorna nomes de campos vazios (para resposta JSON + UX no cliente)."""
    missing: list[str] = []
    if not usuario:
        missing.append("usuario")
    if not senha:
        missing.append("senha")
    return missing


def validate_login_csrf(session_token: str | None, provided: str | None) -> bool:
    if not session_token or not provided:
        return False
    from secrets import compare_digest

    return compare_digest(session_token, provided)
