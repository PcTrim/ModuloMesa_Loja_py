"""
Modelos e contratos relacionados a usuários / autenticação.

A tabela `usuarios` no MySQL (loja2001) expõe tipicamente:
- chave (PK)
- usuario (login, único por instalação ou combinado com id_cliente)
- senha (legado em texto plano; pode evoluir para hash bcrypt)
- id_cliente (tenant)
- ativo, data_criacao
- funcao (opcional: gerente | atendente)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Mensagem única para falha de credenciais (evita enumeração de usuários).
AUTH_CREDENTIALS_INVALID_MSG = "Credenciais inválidas. Verifique os dados e tente novamente."


def normalize_funcao(raw: Any) -> str:
    """Normaliza papel do usuário para RBAC visual."""
    val = str(raw or "gerente").strip().lower()
    return val if val in ("gerente", "atendente") else "gerente"


@dataclass(frozen=True)
class UsuarioAuthRow:
    """Subconjunto de colunas usadas após SELECT na autenticação."""

    usuario: str
    senha: str
    id_cliente: int | None
    funcao: str = "gerente"

    @classmethod
    def from_db_row(cls, row: dict[str, Any] | None) -> UsuarioAuthRow | None:
        if not row:
            return None
        return cls(
            usuario=str(row.get("usuario") or ""),
            senha=str(row.get("senha") or ""),
            id_cliente=row.get("id_cliente"),
            funcao=normalize_funcao(row.get("funcao")),
        )
