"""Regressão: parse de impressora no cadastro/edição de produto (modo restaurante)."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-catalog-impressora-produto")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import app  # noqa: E402
from blueprints.catalog import _parse_impressora_produto  # noqa: E402


class ParseImpressoraProdutoTests(unittest.TestCase):
    def test_restaurante_imprenro_positivo(self):
        self.assertEqual(_parse_impressora_produto({"impressora": 2}, restaurante=True), 2)
        self.assertEqual(_parse_impressora_produto({"impressora": "3"}, restaurante=True), 3)

    def test_restaurante_herdar_explicito(self):
        self.assertIsNone(
            _parse_impressora_produto(
                {"impressora": None, "impressora_herdar": True},
                restaurante=True,
            )
        )

    def test_restaurante_null_sem_flag_herda(self):
        self.assertIsNone(_parse_impressora_produto({"impressora": None}, restaurante=True))

    def test_restaurante_imprenro_zero_persiste(self):
        self.assertEqual(_parse_impressora_produto({"impressora": 0}, restaurante=True), 0)

    def test_retail_default_quando_ausente(self):
        self.assertEqual(_parse_impressora_produto({}, restaurante=False), 1)

    def test_retail_imprenro_zero(self):
        self.assertEqual(_parse_impressora_produto({"impressora": 0}, restaurante=False), 0)


class EditarProdutoImpressoraResponseTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "test_impressora_produto"
            sess["id_cliente"] = 2001
            sess["funcao"] = "gerente"

    @patch("blueprints.catalog.is_retail", return_value=False)
    @patch("blueprints.catalog.conectar")
    def test_put_retorna_impressora_imprenro_2(self, mock_conectar, _mock_retail):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conectar.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"chave": 100, "controla_estoque": 0}

        resp = self.client.put(
            "/api/editar-produto/100",
            json={
                "produto": "TESTE IMPRESSORA",
                "preco": 10,
                "classe": "PIZZAS",
                "porkilo": "Nao",
                "vendaliberada": "Sim",
                "impressora": 2,
            },
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertTrue(data.get("sucesso"))
        self.assertEqual(data.get("impressora"), 2)
        mock_conn.commit.assert_called_once()

    @patch("blueprints.catalog.is_retail", return_value=False)
    @patch("blueprints.catalog.conectar")
    def test_put_herdar_retorna_impressora_null(self, mock_conectar, _mock_retail):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conectar.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"chave": 100, "controla_estoque": 0}

        resp = self.client.put(
            "/api/editar-produto/100",
            json={
                "produto": "TESTE HERDAR",
                "preco": 10,
                "classe": "PIZZAS",
                "porkilo": "Nao",
                "vendaliberada": "Sim",
                "impressora": None,
                "impressora_herdar": True,
            },
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertTrue(data.get("sucesso"))
        self.assertIsNone(data.get("impressora"))


if __name__ == "__main__":
    unittest.main()
