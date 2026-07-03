"""Status financeiro (duplicatas Interno) e bloqueio de novas vendas."""
from __future__ import annotations

import logging
import time

from config import Config
from repositories.duplicatas_repo import fetch_resumo_duplicatas_cliente

logger = logging.getLogger(__name__)

MSG_BLOQUEIO_VENDA = "Vendas bloqueadas por inadimplência"
MSG_ALERTA_A_VENCER = "Existem duplicatas com vencimento em até 2 dias"
MSG_ALERTA_VENCIDAS = "Existem duplicatas vencidas"

_CACHE_TTL_SEC = 60
_cache: dict[int, dict] = {}
_cache_ts: dict[int, float] = {}

_STATUS_LIMPO = {
    "temAVencer": False,
    "temVencidas": False,
    "diasAtrasoMax": 0,
    "bloqueadoVenda": False,
}


class FinanceiroBloqueioError(Exception):
    def __init__(self, message: str = MSG_BLOQUEIO_VENDA):
        super().__init__(message)
        self.message = message


def _normalize_status(raw: dict | None) -> dict:
    if not raw:
        return dict(_STATUS_LIMPO)
    return {
        "temAVencer": bool(raw.get("tem_a_vencer")),
        "temVencidas": bool(raw.get("tem_vencidas")),
        "diasAtrasoMax": int(raw.get("dias_atraso_max") or 0),
        "bloqueadoVenda": bool(raw.get("bloqueado_venda")),
    }


def get_status_financeiro(id_cliente: int, *, use_cache: bool = True) -> dict:
    """Fail-open: retorna status limpo se Interno indisponível."""
    try:
        cid = int(id_cliente)
    except (TypeError, ValueError):
        return dict(_STATUS_LIMPO)
    if cid <= 0:
        return dict(_STATUS_LIMPO)

    if not Config.interno_db_configured():
        logger.warning("financeiro: MYSQL_DATABASE_INTERNO não configurado (id_cliente=%s)", cid)
        return dict(_STATUS_LIMPO)

    now = time.time()
    if use_cache and cid in _cache and (now - _cache_ts.get(cid, 0)) < _CACHE_TTL_SEC:
        return dict(_cache[cid])

    raw = fetch_resumo_duplicatas_cliente(cid)
    if raw is None:
        logger.warning("financeiro: falha ao consultar Duplicatas (id_cliente=%s)", cid)
        return dict(_STATUS_LIMPO)

    status = _normalize_status(raw)
    _cache[cid] = status
    _cache_ts[cid] = now
    return dict(status)


def esta_bloqueado_venda(id_cliente: int) -> bool:
    return bool(get_status_financeiro(id_cliente).get("bloqueadoVenda"))


def assert_nova_venda_permitida(id_cliente: int) -> None:
    if esta_bloqueado_venda(id_cliente):
        raise FinanceiroBloqueioError()
