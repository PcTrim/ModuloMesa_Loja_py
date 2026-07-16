import os
import unittest
from unittest.mock import patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-suite-secret")

from app import app


class _FakeCursor:
    def __init__(self, fetchone_seq=None):
        self._fetchone_seq = list(fetchone_seq or [])
        self.rowcount = 0
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        upper_sql = " ".join(str(sql).upper().split())
        if upper_sql.startswith("UPDATE PEDIDO_DIARIOS SET STATUS_COMANDA"):
            self.rowcount = 2

    def fetchone(self):
        if self._fetchone_seq:
            return self._fetchone_seq.pop(0)
        return None

    def fetchall(self):
        return []

    def close(self):
        return None


class _FakeConn:
    def __init__(self, fetchone_seq=None):
        self.cursor_obj = _FakeCursor(fetchone_seq=fetchone_seq)
        self.started = False
        self.committed = False
        self.rolled_back = False

    def cursor(self, dictionary=False):
        return self.cursor_obj

    def start_transaction(self):
        self.started = True

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        return None


class OperacoesCriticasApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "suite-api"
            sess["usuario"] = "suite-api"
            sess["id_cliente"] = 321
            sess["funcao"] = "gerente"

    def test_fechamento_preview_sem_login_bloqueia_acesso(self):
        resp = self.client.post("/api/fechamento/preview", json={"data_inicio": "2026-01-01", "data_fim": "2026-01-01"})
        self.assertIn(resp.status_code, (302, 401))

    def test_cancelar_comanda_exige_confirmacao(self):
        self._login()
        resp = self.client.post(
            "/api/pedido/cancelar-comanda",
            json={"origem": "BALCAO", "nropedido": 10, "confirmacao": "NAO"},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json() or {}
        self.assertFalse(data.get("sucesso"))
        self.assertIn("Confirma", data.get("erro", ""))

    def test_cancelar_comanda_retorna_409_quando_regra_bloqueia(self):
        self._login()
        with patch("app.conectar", return_value=_FakeConn()), patch(
            "app._comanda_pode_cancelar",
            return_value=(False, "Pedido já RECEBIDO não pode ser cancelado."),
        ):
            resp = self.client.post(
                "/api/pedido/cancelar-comanda",
                json={"origem": "BALCAO", "nropedido": 15, "confirmacao": "CANCELAR"},
            )
        self.assertEqual(resp.status_code, 409)
        data = resp.get_json() or {}
        self.assertFalse(data.get("sucesso"))
        self.assertIn("RECEBIDO", data.get("erro", ""))

    def test_cancelar_comanda_ok_retorna_linhas_afetadas(self):
        self._login()
        fake_conn = _FakeConn()
        with patch("app.conectar", return_value=fake_conn), patch(
            "app._comanda_pode_cancelar",
            return_value=(True, ""),
        ):
            resp = self.client.post(
                "/api/pedido/cancelar-comanda",
                json={"origem": "BALCAO", "nropedido": 18, "confirmacao": "CANCELAR"},
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertTrue(data.get("sucesso"))
        self.assertEqual(data.get("linhas_afetadas"), 2)
        self.assertTrue(fake_conn.committed)

    def test_baixa_receber_exige_pagamentos_validos(self):
        self._login()
        resp = self.client.post(
            "/api/baixa/receber",
            json={"origem": "BALCAO", "nropedido": 22, "pagamentos": []},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json() or {}
        self.assertIn("forma de pagamento", data.get("erro", "").lower())

    def test_baixa_receber_bloqueia_pedido_em_aguarde(self):
        self._login()
        fake_conn = _FakeConn(
            fetchone_seq=[
                None,
                {"total": 35.0, "aberto_count": 1, "rota_count": 0, "aguarde_count": 1},
            ]
        )
        with patch("app.conectar", return_value=fake_conn):
            resp = self.client.post(
                "/api/baixa/receber",
                json={
                    "origem": "BALCAO",
                    "nropedido": 22,
                    "pagamentos": [{"forma": "PIX", "valor": 35}],
                },
            )
        self.assertEqual(resp.status_code, 409)
        data = resp.get_json() or {}
        self.assertFalse(data.get("sucesso"))
        self.assertIn("AGUARDE", data.get("erro", ""))
        self.assertTrue(fake_conn.rolled_back)

    def test_fechamento_preview_propaga_erro_de_validacao(self):
        self._login()
        with patch("app.preview_fechamento", side_effect=ValueError("Data obrigatória")):
            resp = self.client.post("/api/fechamento/preview", json={})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json() or {}
        self.assertEqual(data.get("erro"), "Data obrigatória")

    def test_fechamento_executar_retorna_400_quando_servico_falha(self):
        self._login()
        with patch("app.executar_fechamento", return_value={"sucesso": False, "erro": "Sem linhas elegíveis."}):
            resp = self.client.post(
                "/api/fechamento/executar",
                json={"data_inicio": "2026-01-01", "data_fim": "2026-01-01"},
            )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json() or {}
        self.assertFalse(data.get("sucesso"))
        self.assertIn("Sem linhas", data.get("erro", ""))

    def test_fechamento_print_blocos_retorna_erro_claro(self):
        self._login()
        with patch(
            "app.save_fechamento_print_blocos",
            return_value=(False, "Payload inválido.", {"resumo": True}),
        ):
            resp = self.client.post("/api/fechamento/print-blocos", json={"resumo": "x"})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json() or {}
        self.assertFalse(data.get("sucesso"))
        self.assertEqual(data.get("print_blocos"), {"resumo": True})


if __name__ == "__main__":
    unittest.main()
