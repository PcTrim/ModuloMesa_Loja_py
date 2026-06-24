"""Modo de negócio por tenant (restaurante vs varejo)."""
from flask import g, has_request_context, session

from services.dados_loja import obter_dados_loja


def is_retail(id_cliente=None):
    try:
        if id_cliente is None and has_request_context():
            if hasattr(g, "_is_retail"):
                return g._is_retail
            id_cliente = session.get("id_cliente")

        dados = obter_dados_loja(id_cliente)
        tipo = (dados or {}).get("tipo_negocio", "restaurante")
        result = str(tipo).strip().lower() == "varejo"

        if has_request_context():
            g._is_retail = result

        return result
    except Exception as e:
        print(f"[IS_RETAIL ERRO] id_cliente={id_cliente} erro={e}", flush=True)
        return False
