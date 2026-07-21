"""Testes de sincronização classificacao ↔ produtos.classe."""
import os
import unittest
from unittest.mock import ANY, MagicMock

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

from app import (
    _analise_catalogo_classes_produto,
    _listar_classes_orfas_produto,
    _sincronizar_classificacoes_de_produtos,
)


def _mock_analise_cur(produtos_rows, classificacao_rows, categoria_rows, tem_category_id=True):
    """Monta cursor mock na ordem de execução de _analise_catalogo_classes_produto."""
    cur = MagicMock()
    cur.fetchone.side_effect = [{"Field": "category_id"}] if tem_category_id else [None]
    cur.fetchall.side_effect = [
        categoria_rows,
        classificacao_rows,
        produtos_rows,
    ]
    return cur


class ClassificacoesOrfasTests(unittest.TestCase):
    def test_brincos_com_category_id_nao_entra_em_orfas(self):
        cur = _mock_analise_cur(
            produtos_rows=[
                {"classe_key": "BRINCOS", "classe": "BRINCOS", "qtd": 13, "com_category_id": 13},
            ],
            classificacao_rows=[],
            categoria_rows=[{"nome": "BRINCOS"}],
        )
        analise = _analise_catalogo_classes_produto(cur, 2003)
        self.assertEqual(analise["orfas"], [])
        self.assertEqual(analise["total_produtos_orfaos"], 0)
        self.assertEqual(len(analise["retail_legacy"]), 1)
        self.assertEqual(analise["retail_legacy"][0]["classe"], "BRINCOS")
        self.assertEqual(analise["retail_legacy"][0]["qtd"], 13)
        self.assertTrue(analise["retail_legacy"][0]["categoria_existe"])
        self.assertEqual(analise["total_produtos_retail_legacy"], 13)

    def test_pizza_sem_category_id_entra_em_orfas(self):
        cur = _mock_analise_cur(
            produtos_rows=[
                {"classe_key": "PIZZA", "classe": "PIZZA", "qtd": 2, "com_category_id": 0},
            ],
            classificacao_rows=[],
            categoria_rows=[],
        )
        analise = _analise_catalogo_classes_produto(cur, 2003)
        self.assertEqual(len(analise["orfas"]), 1)
        self.assertEqual(analise["orfas"][0]["classe"], "PIZZA")
        self.assertEqual(analise["orfas"][0]["qtd"], 2)
        self.assertEqual(analise["retail_legacy"], [])

    def test_mix_2003_retail_legacy_sem_orfas(self):
        cur = _mock_analise_cur(
            produtos_rows=[
                {"classe_key": "BRINCOS", "classe": "BRINCOS", "qtd": 13, "com_category_id": 13},
                {"classe_key": "COLARES", "classe": "COLARES", "qtd": 35, "com_category_id": 35},
                {"classe_key": "TESTE", "classe": "TESTE", "qtd": 1, "com_category_id": 0},
            ],
            classificacao_rows=[{"nome": "TESTE"}],
            categoria_rows=[
                {"nome": "BRINCOS"},
                {"nome": "COLARES"},
            ],
        )
        analise = _analise_catalogo_classes_produto(cur, 2003)
        self.assertEqual(analise["orfas"], [])
        self.assertEqual(analise["total_produtos_retail_legacy"], 48)
        self.assertEqual(len(analise["retail_legacy"]), 2)

    def test_lista_classes_sem_cadastro_exclui_retail(self):
        cur = _mock_analise_cur(
            produtos_rows=[
                {"classe_key": "BRINCOS", "classe": "BRINCOS", "qtd": 5, "com_category_id": 5},
                {"classe_key": "PIZZA", "classe": "PIZZA", "qtd": 2, "com_category_id": 0},
            ],
            classificacao_rows=[{"nome": "PIZZA"}],
            categoria_rows=[{"nome": "BRINCOS"}],
        )
        orfas, total = _listar_classes_orfas_produto(cur, 2003)
        self.assertEqual(orfas, [])
        self.assertEqual(total, 0)

    def test_sincronizar_insere_apenas_orfas_restaurante(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [{"Field": "category_id"}, {"n": 1}]
        cur.fetchall.side_effect = [
            [],
            [],
            [{"classe_key": "PIZZA", "classe": "PIZZA", "qtd": 3, "com_category_id": 0}],
        ]
        criadas, ja_existiam = _sincronizar_classificacoes_de_produtos(cur, 2003)
        self.assertEqual(criadas, ["PIZZA"])
        self.assertEqual(ja_existiam, 0)
        cur.execute.assert_any_call(ANY, ("PIZZA", 2003))


if __name__ == "__main__":
    unittest.main()
