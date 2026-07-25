"""Testes da cascata produto → classificação → vazio para impressora de preparo."""
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

from app import _resolver_setor_impressora, resolver_impressora


class ResolverSetorImpressoraTests(unittest.TestCase):
    def test_override_produto(self):
        self.assertEqual(_resolver_setor_impressora(2, 1), "2")

    def test_herda_classificacao_quando_produto_null(self):
        self.assertEqual(_resolver_setor_impressora(None, 3), "3")

    def test_vazio_quando_ambos_null(self):
        self.assertIsNone(_resolver_setor_impressora(None, None))

    def test_produto_zero_herda_classificacao_positiva(self):
        self.assertEqual(_resolver_setor_impressora(0, 5), "5")

    def test_produto_zero_estacao_valida_sem_classe_positiva(self):
        self.assertEqual(_resolver_setor_impressora(0, 0), "0")
        self.assertEqual(_resolver_setor_impressora(0, None), "0")

    def test_produto_null_herda_classificacao_zero(self):
        self.assertEqual(_resolver_setor_impressora(None, 0), "0")


class ResolverImpressoraDbTests(unittest.TestCase):
    def setUp(self):
        self.cur = MagicMock()
        self.patcher = patch(
            "app._produto_setor_col_names",
            return_value=("impressora", {"impressora"}, ["chave"]),
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_retorna_override_do_produto(self):
        self.cur.fetchone.return_value = {"imp_prod": 2, "imp_classe": 1}
        self.assertEqual(resolver_impressora(self.cur, 1, "100"), "2")

    def test_herda_classificacao(self):
        self.cur.fetchone.return_value = {"imp_prod": None, "imp_classe": 4}
        self.assertEqual(resolver_impressora(self.cur, 1, "100"), "4")

    def test_fallback_vazio(self):
        self.cur.fetchone.return_value = {"imp_prod": None, "imp_classe": None}
        self.assertIsNone(resolver_impressora(self.cur, 1, "100"))

    def test_sem_codigo_retorna_none(self):
        self.assertIsNone(resolver_impressora(self.cur, 1, ""))
        self.cur.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
