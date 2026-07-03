"""Testes — inadimplência e bloqueio de vendas."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")
os.environ.setdefault("PLATFORM_ADMIN_USERS", "marcio,suporte")

from app import app
from services.financeiro_inadimplencia import (
    FinanceiroBloqueioError,
    MSG_BLOQUEIO_VENDA,
    _STATUS_LIMPO,
    _cache,
    _cache_ts,
    assert_nova_venda_permitida,
    get_status_financeiro,
)


def _clear_cache():
    _cache.clear()
    _cache_ts.clear()


class FinanceiroStatusTests(unittest.TestCase):
    def setUp(self):
        _clear_cache()

    @patch("services.financeiro_inadimplencia.fetch_resumo_duplicatas_cliente")
    @patch("services.financeiro_inadimplencia.Config.interno_db_configured", return_value=True)
    def test_a_vencer_sem_bloqueio(self, _cfg, mock_fetch):
        mock_fetch.return_value = {
            "tem_a_vencer": 1,
            "tem_vencidas": 0,
            "dias_atraso_max": 0,
            "bloqueado_venda": 0,
        }
        st = get_status_financeiro(2001, use_cache=False)
        self.assertTrue(st["temAVencer"])
        self.assertFalse(st["temVencidas"])
        self.assertFalse(st["bloqueadoVenda"])

    @patch("services.financeiro_inadimplencia.fetch_resumo_duplicatas_cliente")
    @patch("services.financeiro_inadimplencia.Config.interno_db_configured", return_value=True)
    def test_vencida_1_dia_sem_bloqueio(self, _cfg, mock_fetch):
        mock_fetch.return_value = {
            "tem_a_vencer": 0,
            "tem_vencidas": 1,
            "dias_atraso_max": 1,
            "bloqueado_venda": 0,
        }
        st = get_status_financeiro(2001, use_cache=False)
        self.assertTrue(st["temVencidas"])
        self.assertEqual(st["diasAtrasoMax"], 1)
        self.assertFalse(st["bloqueadoVenda"])

    @patch("services.financeiro_inadimplencia.fetch_resumo_duplicatas_cliente")
    @patch("services.financeiro_inadimplencia.Config.interno_db_configured", return_value=True)
    def test_vencida_4_dias_bloqueia(self, _cfg, mock_fetch):
        mock_fetch.return_value = {
            "tem_a_vencer": 0,
            "tem_vencidas": 1,
            "dias_atraso_max": 4,
            "bloqueado_venda": 1,
        }
        st = get_status_financeiro(2001, use_cache=False)
        self.assertTrue(st["bloqueadoVenda"])
        with self.assertRaises(FinanceiroBloqueioError) as ctx:
            assert_nova_venda_permitida(2001)
        self.assertEqual(ctx.exception.message, MSG_BLOQUEIO_VENDA)

    @patch("services.financeiro_inadimplencia.fetch_resumo_duplicatas_cliente", return_value=None)
    @patch("services.financeiro_inadimplencia.Config.interno_db_configured", return_value=True)
    def test_interno_indisponivel_fail_open(self, _cfg, _mock_fetch):
        st = get_status_financeiro(2001, use_cache=False)
        self.assertEqual(st, _STATUS_LIMPO)
        assert_nova_venda_permitida(2001)


class FinanceiroApiGuardTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._ctx = app.app_context()
        self._ctx.push()
        _clear_cache()

    def tearDown(self):
        self._ctx.pop()
        _clear_cache()

    @patch("app.assert_nova_venda_permitida")
    def test_casa_item_nova_venda_bloqueada(self, mock_assert):
        mock_assert.side_effect = FinanceiroBloqueioError()
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "gerente1"
            sess["id_cliente"] = 2001
            sess["funcao"] = "gerente"
        r = self.client.post(
            "/api/casa/item",
            json={
                "modo": "BALCAO",
                "telefone": "BALCAO0001",
                "item": {"nome": "Produto", "preco": 10, "qtd": 1},
            },
        )
        self.assertEqual(r.status_code, 403)
        data = r.get_json()
        self.assertIn("inadimplência", data.get("erro", ""))

    @patch("blueprints.financeiro.get_status_financeiro")
    def test_financeiro_status_endpoint(self, mock_status):
        mock_status.return_value = {
            "temAVencer": True,
            "temVencidas": False,
            "diasAtrasoMax": 0,
            "bloqueadoVenda": False,
        }
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "gerente1"
            sess["id_cliente"] = 2001
            sess["funcao"] = "gerente"
        r = self.client.get("/financeiro/status")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["temAVencer"])
        mock_status.assert_called_once_with(2001)


if __name__ == "__main__":
    unittest.main()
