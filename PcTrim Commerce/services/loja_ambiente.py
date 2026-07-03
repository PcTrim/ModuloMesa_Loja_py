"""Ambiente por loja (produção vs homologação)."""
from __future__ import annotations

import mysql.connector

AMBIENTE_PRODUCTION = "production"
AMBIENTE_HOMOLOGATION = "homologation"


def normalize_ambiente(value, default: str = AMBIENTE_PRODUCTION) -> str:
    raw = str(value or default).strip().lower()
    if raw in ("homologation", "homolog", "hml", "staging", "teste", "test"):
        return AMBIENTE_HOMOLOGATION
    return AMBIENTE_PRODUCTION


def ambiente_label(value) -> str:
    return "Homologação" if normalize_ambiente(value) == AMBIENTE_HOMOLOGATION else "Produção"


def loja_eh_homologacao(dados: dict | None) -> bool:
    if not dados:
        return False
    return normalize_ambiente(dados.get("ambiente")) == AMBIENTE_HOMOLOGATION


def banner_for_loja(dados: dict | None) -> tuple[str | None, str | None]:
    """Badge exibido para o cliente logado conforme cadastro da loja."""
    if loja_eh_homologacao(dados):
        return ("Homologação", "hml")
    return None, None


def banner_for_app() -> tuple[str | None, str | None]:
    """Sem banner global — ambiente é por loja (ver banner_for_loja)."""
    return None, None


def fetch_loja_ambiente_for_cliente(id_cliente) -> str:
    """Fonte da verdade: dadosloja.ambiente (via conectar_admin, sem usar conectar())."""
    from database import conectar_admin_optional

    try:
        id_cliente = int(id_cliente)
    except (TypeError, ValueError):
        return AMBIENTE_PRODUCTION
    if id_cliente <= 0:
        return AMBIENTE_PRODUCTION

    for target in (AMBIENTE_PRODUCTION, AMBIENTE_HOMOLOGATION):
        conn = conectar_admin_optional(target)
        if conn is None:
            continue
        cur = None
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT ambiente FROM dadosloja WHERE id_cliente = %s LIMIT 1",
                (id_cliente,),
            )
            row = cur.fetchone()
            if row:
                return normalize_ambiente(row.get("ambiente"))
        except mysql.connector.Error as e:
            if getattr(e, "errno", None) == 1054:
                return AMBIENTE_PRODUCTION
            raise
        finally:
            if cur:
                cur.close()
            conn.close()

    return AMBIENTE_PRODUCTION
