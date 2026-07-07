"""Testes de promoção HML → produção."""
import unittest
from unittest.mock import MagicMock, patch

from services.tenant_provision import TenantProvisionError
from services.tenant_promote import (
    _copy_retail_catalog,
    _count_produtos,
    promote_tenant_hml_to_production,
)


class TestPromoteBlockCatalog(unittest.TestCase):
    @patch("services.tenant_promote.conectar_admin")
    @patch("services.tenant_promote.hml_admin_disponivel", return_value=True)
    @patch("services.tenant_promote.Config.admin_db_configured", return_value=True)
    def test_block_when_prod_has_products(self, _cfg, _hml, mock_connect):
        hml_conn = MagicMock()
        prod_conn = MagicMock()
        hml_cur = MagicMock()
        prod_cur = MagicMock()
        mock_connect.side_effect = [hml_conn, prod_conn]
        hml_conn.cursor.return_value = hml_cur
        prod_conn.cursor.return_value = prod_cur

        hml_cur.fetchone.side_effect = [
            {"tipo_negocio": "varejo"},
            None,
        ]
        prod_cur.fetchone.side_effect = [
            {"n": 5},
        ]

        def loja_exists(sql, params):
            return {"1": 1}

        hml_cur.fetchone.side_effect = None
        prod_cur.fetchone.side_effect = None

        call_idx = {"hml": 0, "prod": 0}

        def hml_fetchone():
            call_idx["hml"] += 1
            if call_idx["hml"] == 1:
                return {"1": 1}
            if call_idx["hml"] == 2:
                return {"tipo_negocio": "varejo"}
            if call_idx["hml"] == 3:
                return {"n": 10}
            return None

        def prod_fetchone():
            call_idx["prod"] += 1
            if call_idx["prod"] == 1:
                return {"1": 1}
            if call_idx["prod"] == 2:
                return {"n": 3}
            return None

        hml_cur.fetchone.side_effect = hml_fetchone
        prod_cur.fetchone.side_effect = prod_fetchone

        with self.assertRaises(TenantProvisionError) as ctx:
            promote_tenant_hml_to_production(2027, substituir=False)
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("já tem", ctx.exception.message.lower())


class TestCopyRetailCatalog(unittest.TestCase):
    def test_maps_ids(self):
        hml_cur = MagicMock()
        prod_cur = MagicMock()

        hml_cur.fetchall.side_effect = [
            [{"id": 1, "id_cliente": 9, "nome": "Cat", "ordem_exibicao": 0, "ativo": 1}],
            [{"id": 10, "id_cliente": 9, "categoria_id": 1, "nome": "Sub", "ordem_exibicao": 0, "ativo": 1}],
            [{
                "chave": 100,
                "id_cliente": 9,
                "produto": "P1",
                "preco": 10,
                "classe": "X",
                "porkilo": "Nao",
                "impressora": 1,
                "cfop": "5102",
                "ncm": "",
                "display": 1,
                "vendaliberada": "Sim",
                "descricao": "",
                "barcode": "123",
                "category_id": 1,
                "subcategory_id": 10,
            }],
            [{
                "id": 1,
                "id_cliente": 9,
                "product_id": 100,
                "preco_varejo": 10,
                "estoque": 1,
                "ativo": 1,
                "ordem_exibicao": 0,
                "permite_venda_sem_estoque": 0,
                "destaque": 0,
            }],
        ]

        id_seq = iter([11, 21, 200, 301])

        def table_columns(cur, table):
            base = {"id_cliente"}
            if table == "categoria":
                return base | {"id", "nome", "ordem_exibicao", "ativo"}
            if table == "subcategoria":
                return base | {"id", "categoria_id", "nome", "ordem_exibicao", "ativo"}
            if table == "produtos":
                return base | {
                    "chave", "produto", "preco", "classe", "porkilo", "impressora",
                    "cfop", "ncm", "display", "vendaliberada", "descricao", "barcode",
                    "category_id", "subcategory_id",
                }
            if table == "produto_retail":
                return base | {
                    "id", "product_id", "preco_varejo", "estoque", "ativo",
                    "ordem_exibicao", "permite_venda_sem_estoque", "destaque",
                }
            return base

        with patch("services.tenant_promote._table_columns", side_effect=table_columns):
            prod_cur.lastrowid = 0
            prod_cur.execute = MagicMock()

            def set_lastrowid(*args, **kwargs):
                prod_cur.lastrowid = next(id_seq)

            prod_cur.execute.side_effect = lambda *a, **k: set_lastrowid()

            stats = _copy_retail_catalog(hml_cur, prod_cur, 9)

        self.assertEqual(stats["categoria"], 1)
        self.assertEqual(stats["produtos"], 1)
        self.assertEqual(stats["produto_retail"], 1)
        self.assertGreaterEqual(prod_cur.execute.call_count, 4)


if __name__ == "__main__":
    unittest.main()
