"""Clientes elegíveis da base Interno para cadastro de loja."""
from __future__ import annotations

import logging
import time

import mysql.connector

logger = logging.getLogger(__name__)

from database import conectar_admin_optional
from repositories.clientes_internos_repo import fetch_cliente_ativo_by_id, fetch_clientes_ativos
from services.loja_ambiente import AMBIENTE_HOMOLOGATION, AMBIENTE_PRODUCTION

MSG_LOAD_ERROR = "Não foi possível carregar os clientes no momento"
MSG_JA_EM_USO = "Cliente já está em uso por outra loja"
MSG_NAO_ELEGIVEL = "Cliente não está disponível para cadastro"

_CACHE_TTL_SEC = 60
_cache: dict = {"ts": 0.0, "clientes": None}


class ClientesInternosError(Exception):
    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.message = message
        self.status = status


def invalidate_clientes_internos_cache() -> None:
    _cache["ts"] = 0.0
    _cache["clientes"] = None


def _admin_targets_for_sync() -> list[str]:
    from config import Config

    targets = [AMBIENTE_PRODUCTION]
    if Config.admin_db_configured(AMBIENTE_HOMOLOGATION):
        targets.append(AMBIENTE_HOMOLOGATION)
    return targets


def collect_id_clientes_em_uso() -> set[int]:
    """IDs já provisionados em dadosloja (prod + HML)."""
    used: set[int] = set()
    for target in _admin_targets_for_sync():
        conn = conectar_admin_optional(target)
        if conn is None:
            continue
        cur = None
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT id_cliente FROM dadosloja WHERE id_cliente IS NOT NULL"
            )
            for row in cur.fetchall() or []:
                if row and row[0] is not None:
                    used.add(int(row[0]))
        finally:
            if cur:
                cur.close()
            conn.close()
    return used


def _format_label(row: dict) -> str:
    cliente = (row.get("cliente") or "").strip()
    fantasia = (row.get("fantasia") or "").strip()
    key = row.get("id")
    return f"{cliente} - {fantasia} - {key}"


def _normalize_row(row: dict) -> dict:
    doc = (row.get("documento") or "").strip()
    out = {
        "id": int(row["id"]),
        "cliente": (row.get("cliente") or "").strip(),
        "fantasia": (row.get("fantasia") or "").strip(),
        "documento": doc,
        "label": "",
    }
    out["label"] = _format_label(out)
    return out


def _filter_disponiveis(rows: list[dict], em_uso: set[int]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        cid = int(row["id"])
        if cid in em_uso:
            continue
        out.append(_normalize_row(row))
    return out


def list_clientes_internos_disponiveis(*, use_cache: bool = True) -> list[dict]:
    now = time.time()
    if use_cache and _cache["clientes"] is not None and (now - _cache["ts"]) < _CACHE_TTL_SEC:
        em_uso = collect_id_clientes_em_uso()
        return [c for c in _cache["clientes"] if c["id"] not in em_uso]

    try:
        raw = fetch_clientes_ativos()
    except mysql.connector.Error as e:
        logger.warning("clientes_internos: falha MySQL ao listar ativos: %s", e)
        raise ClientesInternosError(MSG_LOAD_ERROR, status=503) from e
    except Exception as e:
        logger.warning("clientes_internos: erro inesperado ao listar ativos: %s", e)
        raise ClientesInternosError(MSG_LOAD_ERROR, status=503) from e

    normalized = [_normalize_row(r) for r in raw]
    _cache["clientes"] = normalized
    _cache["ts"] = now
    em_uso = collect_id_clientes_em_uso()
    return _filter_disponiveis(raw, em_uso)


def cliente_interno_disponivel(key_chave: int) -> bool:
    try:
        key_chave = int(key_chave)
    except (TypeError, ValueError):
        return False
    if key_chave <= 0:
        return False
    if key_chave in collect_id_clientes_em_uso():
        return False
    try:
        row = fetch_cliente_ativo_by_id(key_chave)
    except mysql.connector.Error:
        return False
    return row is not None


def ensure_cliente_disponivel_para_loja(key_chave: int) -> dict:
    """Validação final antes do provisionamento (anti-concorrência)."""
    try:
        key_chave = int(key_chave)
    except (TypeError, ValueError):
        raise ClientesInternosError("Selecione um cliente válido.", status=400)
    if key_chave <= 0:
        raise ClientesInternosError("Selecione um cliente válido.", status=400)

    if key_chave in collect_id_clientes_em_uso():
        raise ClientesInternosError(MSG_JA_EM_USO, status=409)

    try:
        row = fetch_cliente_ativo_by_id(key_chave)
    except mysql.connector.Error as e:
        raise ClientesInternosError(MSG_LOAD_ERROR, status=503) from e

    if not row:
        raise ClientesInternosError(MSG_NAO_ELEGIVEL, status=409)

    return _normalize_row(row)
