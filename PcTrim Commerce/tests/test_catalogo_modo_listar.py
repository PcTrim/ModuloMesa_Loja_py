"""Testes de filtro catálogo restaurante vs varejo (listar-produtos)."""
import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

from services.catalogo_modo import (
    contar_produtos_varejo_ocultos,
    produto_tem_coluna_category_id,
    sql_filtro_produto_restaurante,
)


class CatalogoModoHelperTests(unittest.TestCase):
    def test_sql_filtro_produto_restaurante_inclui_category_id_e_categoria(self):
        sql = sql_filtro_produto_restaurante("p")
        self.assertIn("p.category_id IS NULL", sql)
        self.assertIn("FROM categoria WHERE id_cliente = %s", sql)

    def test_produto_tem_coluna_category_id_true(self):
        cur = MagicMock()
        cur.fetchone.return_value = {"Field": "category_id"}
        self.assertTrue(produto_tem_coluna_category_id(cur))

    def test_produto_tem_coluna_category_id_false(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        self.assertFalse(produto_tem_coluna_category_id(cur))

    def test_contar_produtos_varejo_ocultos(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [{"Field": "category_id"}, {"n": 66}]
        self.assertEqual(contar_produtos_varejo_ocultos(cur, 2003), 66)

    def test_contar_produtos_varejo_ocultos_sem_coluna(self):
        cur = MagicMock()
        cur.fetchone.return_value = None
        self.assertEqual(contar_produtos_varejo_ocultos(cur, 2003), 0)


class ListarProdutosRestauranteTests(unittest.TestCase):
    def _simular_listagem_restaurante(self, produtos_rows, ocultos=0):
        """Replica a lógica de filtro do GET /api/listar-produtos em modo restaurante."""
        cur = MagicMock()
        cur.fetchone.side_effect = [{"Field": "category_id"}, {"n": ocultos}]
        cur.fetchall.return_value = produtos_rows
        filtro = sql_filtro_produto_restaurante("p")
        ocultos_count = contar_produtos_varejo_ocultos(cur, 2003)
        produtos = cur.fetchall()
        return {
            "sucesso": True,
            "produtos": produtos,
            "produtos_varejo_ocultos": ocultos_count,
            "catalogo_mismatch": ocultos_count > 0 and len(produtos) == 0,
            "filtro_sql": filtro,
        }

    def test_produtos_com_category_id_nao_entram_na_listagem(self):
        payload = self._simular_listagem_restaurante([], ocultos=13)
        self.assertEqual(payload["produtos"], [])
        self.assertEqual(payload["produtos_varejo_ocultos"], 13)

    def test_produto_pizza_sem_category_id_entra_na_listagem(self):
        pizza = {"chave": 1, "produto": "MARGHERITA", "classe": "PIZZA", "category_id": None}
        payload = self._simular_listagem_restaurante([pizza], ocultos=0)
        self.assertEqual(len(payload["produtos"]), 1)
        self.assertEqual(payload["produtos"][0]["classe"], "PIZZA")
        self.assertEqual(payload["produtos_varejo_ocultos"], 0)

    def test_loja_2003_like_ocultos_66_lista_vazia(self):
        payload = self._simular_listagem_restaurante([], ocultos=66)
        self.assertEqual(payload["produtos_varejo_ocultos"], 66)
        self.assertEqual(payload["produtos"], [])
        self.assertTrue(payload["catalogo_mismatch"])


if __name__ == "__main__":
    unittest.main()
