import os
import unittest
from unittest.mock import patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-suite-secret")

from app import app


class _Cursor:
    def __init__(self, fetchone_seq=None):
        self.executed = []
        self._fetchone_seq = list(fetchone_seq or [])

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self._fetchone_seq:
            return self._fetchone_seq.pop(0)
        return None

    def close(self):
        return None


class _Conn:
    def __init__(self, fetchone_seq=None):
        self.cursor_obj = _Cursor(fetchone_seq=fetchone_seq)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        return None


class ConfirmacaoImpressaoTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "suite-impressao"
            sess["id_cliente"] = 77

    def test_confirmar_impressao_casa_atualiza_aguarde_para_aberto(self):
        fake_conn = _Conn(fetchone_seq=[{"origem": "BALCAO"}])
        with patch("app.conectar", return_value=fake_conn), patch(
            "app._assert_casa_editavel",
            return_value=None,
        ):
            resp = self.client.post(
                "/api/casa/confirmar-impressao",
                json={"origem": "casa", "nropedido": 9001, "printer": "bridge-1", "copias": 2},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertTrue(data.get("sucesso"))
        self.assertEqual(data.get("printer"), "bridge-1")
        self.assertEqual(data.get("copias"), 2)
        self.assertTrue(fake_conn.committed)
        self.assertEqual(len(fake_conn.cursor_obj.executed), 2)
        sql_select, params_select = fake_conn.cursor_obj.executed[0]
        sql_update, params_update = fake_conn.cursor_obj.executed[1]
        self.assertIn("SELECT UPPER(COALESCE(MAX(origem)", sql_select)
        self.assertEqual(params_select, (9001, 77))
        self.assertIn("UPDATE pedido_diarios", sql_update)
        self.assertEqual(params_update, (9001, 77))

    def test_confirmar_impressao_fechamento_nao_toca_banco(self):
        with patch("app.conectar") as mock_connect:
            resp = self.client.post(
                "/api/casa/confirmar-impressao",
                json={"origem": "fechamento", "printer": "bridge-2", "copias": 1},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertTrue(data.get("sucesso"))
        self.assertEqual(data.get("printer"), "bridge-2")
        mock_connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
