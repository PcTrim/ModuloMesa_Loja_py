import os
import unittest
from unittest.mock import patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

from app import app


class _FakeCursor:
    def __init__(self, row=None):
        self._row = row

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return self._row

    def close(self):
        return None


class _FakeConn:
    def __init__(self, row=None):
        self._row = row

    def cursor(self, dictionary=False):
        row = self._row if dictionary else None
        return _FakeCursor(row=row)

    def close(self):
        return None


class ImprimirEndpointTerminalTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "tester"
            sess["id_cliente"] = 123

    def _payload(self):
        return {
            "conteudo": "TESTE",
            "copias": 1,
            "origem": "casa",
            "terminal_id": "caixa 01",
            "impressora_id": 7,
        }

    def _post(self):
        return self.client.post(
            "/imprimir",
            json=self._payload(),
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
        )

    @patch("app.conectar", return_value=_FakeConn(row=None))
    @patch("app.send_to_printer", return_value=(True, None))
    @patch("app.terminal_impressao_service.get_printer_path", return_value="USB")
    @patch("app.terminal_impressao_service.terminal_is_configured", return_value=True)
    def test_imprimir_com_terminal_id_sucesso(
        self,
        mock_terminal_config,
        mock_get_printer_path,
        mock_send_to_printer,
        _mock_conectar,
    ):
        resp = self._post()

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["sucesso"])
        self.assertEqual(data["printer"], "USB")
        self.assertEqual(data["copias"], 1)
        mock_terminal_config.assert_called_once_with(123, "CAIXA01")
        mock_get_printer_path.assert_called_once_with(123, "CAIXA01", 7)
        mock_send_to_printer.assert_called_once()
        conteudo_enviado = mock_send_to_printer.call_args[0][0]
        self.assertEqual(conteudo_enviado, "TESTE\n")
        self.assertEqual(mock_send_to_printer.call_args[0][1], "USB")

    @patch("app.terminal_impressao_service.get_printer_path")
    @patch("app.terminal_impressao_service.terminal_is_configured", return_value=False)
    def test_imprimir_com_terminal_sem_config_retorna_403(
        self,
        mock_terminal_config,
        mock_get_printer_path,
    ):
        resp = self._post()

        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertFalse(data["sucesso"])
        self.assertIn("não está configurado", data["erro"].lower())
        mock_terminal_config.assert_called_once_with(123, "CAIXA01")
        mock_get_printer_path.assert_not_called()

    @patch("app.conectar", return_value=_FakeConn(row=None))
    @patch("app.send_to_printer", return_value=(False, "Impressora offline"))
    @patch("app.terminal_impressao_service.get_printer_path", return_value="USB")
    @patch("app.terminal_impressao_service.terminal_is_configured", return_value=True)
    def test_imprimir_com_terminal_id_e_erro_da_impressora(
        self,
        _mock_terminal_config,
        _mock_get_printer_path,
        mock_send_to_printer,
        _mock_conectar,
    ):
        resp = self._post()

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertFalse(data["sucesso"])
        self.assertEqual(data["printer"], "USB")
        self.assertIn("Impressora offline", data["erro"])
        mock_send_to_printer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
