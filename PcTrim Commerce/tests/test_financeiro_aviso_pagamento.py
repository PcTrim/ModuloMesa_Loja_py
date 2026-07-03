"""Testes — aviso de pagamento (comprovante)."""
import io
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")
os.environ.setdefault("PLATFORM_ADMIN_USERS", "marcio,suporte")

from app import app
from services.financeiro_aviso_pagamento import (
    AvisoPagamentoError,
    MSG_ARQUIVO_INVALIDO,
    MSG_RATE_LIMIT,
    MSG_SEM_DESTINO,
    _last_aviso_ts,
    enviar_aviso_pagamento,
)


def _fake_file(name="comp.jpg", data=b"fake-image", mimetype="image/jpeg"):
    f = MagicMock()
    f.filename = name
    f.read.return_value = data
    f.mimetype = mimetype
    return f


class AvisoPagamentoServiceTests(unittest.TestCase):
    def setUp(self):
        _last_aviso_ts.clear()

    @patch("services.financeiro_aviso_pagamento.Config.FINANCEIRO_AVISO_WHATSAPP", [])
    def test_sem_destino(self, *_):
        with self.assertRaises(AvisoPagamentoError) as ctx:
            enviar_aviso_pagamento(2001, _fake_file())
        self.assertEqual(ctx.exception.status, 503)

    @patch("services.financeiro_aviso_pagamento.uazapi.enviar_midia_plataforma", return_value={"ok": True})
    @patch("services.financeiro_aviso_pagamento.Config.FINANCEIRO_AVISO_WHATSAPP", ["5511999999999"])
    @patch("services.financeiro_aviso_pagamento.obter_dados_loja", return_value={"nome": "Loja Teste"})
    def test_envio_ok(self, *_mocks):
        result = enviar_aviso_pagamento(2001, _fake_file(), observacao="PIX")
        self.assertTrue(result["sucesso"])

    @patch("services.financeiro_aviso_pagamento.Config.FINANCEIRO_AVISO_WHATSAPP", ["5511999999999"])
    def test_arquivo_invalido(self, *_):
        with self.assertRaises(AvisoPagamentoError) as ctx:
            enviar_aviso_pagamento(2001, _fake_file(mimetype="text/plain"))
        self.assertIn("imagem", ctx.exception.message.lower())

    @patch("services.financeiro_aviso_pagamento.uazapi.enviar_midia_plataforma", return_value={"ok": True})
    @patch("services.financeiro_aviso_pagamento.Config.FINANCEIRO_AVISO_WHATSAPP", ["5511999999999"])
    @patch("services.financeiro_aviso_pagamento.obter_dados_loja", return_value={})
    def test_rate_limit(self, *_mocks):
        enviar_aviso_pagamento(2001, _fake_file())
        with self.assertRaises(AvisoPagamentoError) as ctx:
            enviar_aviso_pagamento(2001, _fake_file())
        self.assertEqual(ctx.exception.status, 429)


class AvisoPagamentoApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._ctx = app.app_context()
        self._ctx.push()
        _last_aviso_ts.clear()

    def tearDown(self):
        self._ctx.pop()
        _last_aviso_ts.clear()

    @patch("blueprints.financeiro.enviar_aviso_pagamento")
    def test_api_multipart(self, mock_enviar):
        mock_enviar.return_value = {"sucesso": True, "mensagem": "ok"}
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "gerente1"
            sess["id_cliente"] = 2001
            sess["funcao"] = "gerente"
        data = {
            "comprovante": (io.BytesIO(b"\xff\xd8\xff fake jpeg"), "comp.jpg"),
            "observacao": "teste",
        }
        r = self.client.post(
            "/financeiro/avisar-pagamento",
            data=data,
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 200)
        mock_enviar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
