"""Envio de aviso de pagamento (comprovante) para equipe PcTrim."""
from __future__ import annotations

import base64
import time
from datetime import datetime

from config import Config
from services import uazapi
from services.dados_loja import obter_dados_loja

MSG_SUCESSO = (
    "Comprovante recebido. Será analisado pela equipe PcTrim. "
    "O acesso permanece bloqueado até a confirmação do pagamento."
)
MSG_SEM_DESTINO = "Canal de aviso não configurado. Entre em contato com o suporte PcTrim."
MSG_WHATSAPP_FALHA = "Não foi possível enviar o comprovante agora. Tente novamente ou acesse pctrim.site."
MSG_ARQUIVO_INVALIDO = "Envie uma imagem (JPG, PNG ou WEBP) ou PDF de até 5 MB."
MSG_RATE_LIMIT = "Aguarde alguns minutos antes de enviar outro comprovante."

_MAX_BYTES = 5 * 1024 * 1024
_ALLOWED_MIMES = frozenset({
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "application/pdf",
})
_RATE_LIMIT_SEC = 300
_last_aviso_ts: dict[int, float] = {}


class AvisoPagamentoError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _check_rate_limit(id_cliente: int) -> None:
    now = time.time()
    last = _last_aviso_ts.get(id_cliente, 0)
    if now - last < _RATE_LIMIT_SEC:
        raise AvisoPagamentoError(MSG_RATE_LIMIT, status=429)


def _validate_file(file_storage) -> tuple[bytes, str, str]:
    if not file_storage or not getattr(file_storage, "filename", None):
        raise AvisoPagamentoError("Selecione o comprovante para enviar.")
    raw = file_storage.read()
    if not raw:
        raise AvisoPagamentoError("Arquivo vazio.")
    if len(raw) > _MAX_BYTES:
        raise AvisoPagamentoError("Arquivo muito grande. Máximo 5 MB.")
    mimetype = (file_storage.mimetype or "").split(";")[0].strip().lower()
    if mimetype not in _ALLOWED_MIMES:
        raise AvisoPagamentoError(MSG_ARQUIVO_INVALIDO)
    filename = (file_storage.filename or "comprovante").strip()[:120]
    return raw, mimetype, filename


def _build_caption(id_cliente: int, observacao: str) -> str:
    dados = obter_dados_loja(id_cliente) or {}
    nome = (dados.get("nome") or "").strip() or f"Loja #{id_cliente}"
    obs = (observacao or "").strip()[:500]
    when = datetime.now().strftime("%d/%m/%Y %H:%M")
    lines = [
        "Aviso de pagamento — PcTrim Commerce",
        f"Loja: {nome} (#{id_cliente})",
        f"Enviado em: {when}",
    ]
    if obs:
        lines.append(f"Observação: {obs}")
    lines.append("Comprovante em anexo.")
    return "\n".join(lines)


def enviar_aviso_pagamento(id_cliente: int, file_storage, observacao: str = "") -> dict:
    """Valida comprovante e envia via WhatsApp plataforma para FINANCEIRO_AVISO_WHATSAPP."""
    try:
        cid = int(id_cliente)
    except (TypeError, ValueError):
        raise AvisoPagamentoError("Sessão inválida.", status=401)
    if cid <= 0:
        raise AvisoPagamentoError("Sessão inválida.", status=401)

    destinos = Config.FINANCEIRO_AVISO_WHATSAPP
    if not destinos:
        raise AvisoPagamentoError(MSG_SEM_DESTINO, status=503)

    _check_rate_limit(cid)
    raw, mimetype, filename = _validate_file(file_storage)
    b64 = base64.b64encode(raw).decode("ascii")
    caption = _build_caption(cid, observacao)

    ok_count = 0
    last_err = MSG_WHATSAPP_FALHA
    for tel in destinos:
        res = uazapi.enviar_midia_plataforma(
            tel,
            file_base64=b64,
            mimetype=mimetype,
            filename=filename,
            caption=caption,
            evento="financeiro_comprovante",
            id_cliente_log=cid,
        )
        if res.get("ok"):
            ok_count += 1
        else:
            last_err = str(res.get("erro") or MSG_WHATSAPP_FALHA)

    if ok_count == 0:
        raise AvisoPagamentoError(last_err, status=503)

    _last_aviso_ts[cid] = time.time()
    return {"sucesso": True, "mensagem": MSG_SUCESSO}
