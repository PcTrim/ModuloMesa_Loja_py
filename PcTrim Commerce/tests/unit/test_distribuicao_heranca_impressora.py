"""Herança produto→classificação para distribuição de preparo (caso legado imprenro=0)."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-heranca-impressora")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import (  # noqa: E402
    _imp_prod_para_resolver,
    _preencher_impressoras_produto,
    _resolver_setor_impressora,
)


class ImpProdParaResolverTests(unittest.TestCase):
    def test_null_herda(self):
        self.assertIsNone(_imp_prod_para_resolver(None, 1))

    def test_zero_herda_quando_classe_positiva(self):
        self.assertIsNone(_imp_prod_para_resolver(0, 1))

    def test_zero_mantem_quando_classe_zero_ou_ausente(self):
        self.assertEqual(_imp_prod_para_resolver(0, 0), 0)
        self.assertEqual(_imp_prod_para_resolver(0, None), 0)

    def test_override_positivo_mantem(self):
        self.assertEqual(_imp_prod_para_resolver(2, 1), 2)


class ResolverSetorHeranca591Tests(unittest.TestCase):
    def test_caso_591_legado_zero_classe_cozinha(self):
        self.assertEqual(_resolver_setor_impressora(0, 1), "1")

    def test_regressao_2003_imprenro_zero(self):
        self.assertEqual(_resolver_setor_impressora(None, 0), "0")
        self.assertEqual(_resolver_setor_impressora(0, 0), "0")


class PreencherImpressorasProdutoTests(unittest.TestCase):
    @patch("app._produto_setor_col_names", return_value=("impressora", {"impressora"}, ["chave"]))
    def test_sobrescreve_join_errado_com_cascata(self, _mock_cols):
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"chave": 591, "imp_prod": 0, "imp_classe": 1},
        ]
        rows = [{"codigoproduto": "591", "impressoras_produto": 0}]
        _preencher_impressoras_produto(cur, 2001, rows)
        self.assertEqual(rows[0]["impressoras_produto"], "1")

    @patch("app._produto_setor_col_names", return_value=("impressora", {"impressora"}, ["chave"]))
    def test_preenche_vazio_via_cascata(self, _mock_cols):
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"chave": 591, "imp_prod": None, "imp_classe": 2},
        ]
        rows = [{"codigoproduto": "591", "impressoras_produto": None}]
        _preencher_impressoras_produto(cur, 2001, rows)
        self.assertEqual(rows[0]["impressoras_produto"], "2")


if __name__ == "__main__":
    unittest.main()
