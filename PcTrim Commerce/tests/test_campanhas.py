"""Testes unitários do módulo campanhas."""
import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

from services.campanhas import (
    COD_AJUSTE_TECNICO,
    COD_CAMPANHA,
    CampanhaError,
    _batch_categorias_retail,
    _campanha_ativa_agora,
    _coerce_dt,
    _colunas_codigo_produtos,
    _filtrar_itens_validos,
    _limite_vigencia_fim,
    calcular_subtotal_elegivel,
    campanha_elegivel,
    listar_elegiveis_detalhado,
    resolver_categoria_item,
    validar_payload_campanha,
    _resolver_cod_classe_linha_pedido,
)


class ValidarPayloadTests(unittest.TestCase):
    def test_desconto_percentual_ok(self):
        data = validar_payload_campanha({
            "nome": "Promo",
            "tipo": "desconto_percentual",
            "valor_beneficio": 10,
            "aplica_em": "todos",
        })
        self.assertEqual(data["tipo"], "desconto_percentual")

    def test_percentual_invalido(self):
        with self.assertRaises(CampanhaError):
            validar_payload_campanha({
                "nome": "X",
                "tipo": "desconto_percentual",
                "valor_beneficio": 150,
                "aplica_em": "todos",
            })

    def test_produtos_exige_ids(self):
        with self.assertRaises(CampanhaError):
            validar_payload_campanha({
                "nome": "X",
                "tipo": "desconto_valor",
                "valor_beneficio": 5,
                "aplica_em": "produtos",
                "produtos_ids": [],
            })


class FiltrarItensTests(unittest.TestCase):
    def test_ignora_tecnicos(self):
        itens = [
            {"codigoproduto": "10", "preco": 10, "quantidade": 1},
            {"codigoproduto": COD_CAMPANHA, "preco": -1, "quantidade": 1},
            {"codigoproduto": COD_AJUSTE_TECNICO, "preco": 1, "quantidade": 1},
            {"codigoproduto": "11", "preco": 5, "quantidade": 1, "status_pedido": "ITEM_REMOVIDO"},
        ]
        out = _filtrar_itens_validos(itens)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["codigoproduto"], "10")


class SubtotalTests(unittest.TestCase):
    def test_soma_apenas_elegiveis(self):
        cur = MagicMock()
        campanha = {"aplica_em": "todos"}
        itens = [
            {"codigoproduto": "1", "preco": 10, "quantidade": 2},
            {"codigoproduto": COD_CAMPANHA, "preco": -5, "quantidade": 1},
        ]
        sub = calcular_subtotal_elegivel(cur, 1, itens, campanha, retail=False)
        self.assertEqual(sub, 20.0)


class CategoriaResolverTests(unittest.TestCase):
    def test_restaurant_cod_classe(self):
        cur = MagicMock()
        cat = resolver_categoria_item(cur, 1, {"cod_classe": 7}, retail=False)
        self.assertEqual(cat, 7)

    def test_retail_batch_cache(self):
        cur = MagicMock()
        cache = {"42": 3}
        cat = resolver_categoria_item(cur, 1, {"codigoproduto": "42"}, retail=True, cache_retail=cache)
        self.assertEqual(cat, 3)
        cur.execute.assert_not_called()

    def test_retail_sem_coluna_codigoproduto_resolve_por_chave(self):
        cur = MagicMock()
        cur.fetchall.side_effect = [
            [{"Field": "chave"}, {"Field": "category_id"}, {"Field": "produto"}],
            [{"chave": 42, "category_id": 5}],
        ]
        cur.fetchone.return_value = {"category_id": 5}
        cat = resolver_categoria_item(cur, 1, {"codigoproduto": "42"}, retail=True)
        self.assertEqual(cat, 5)
        sql = cur.execute.call_args_list[-1][0][0]
        self.assertNotIn("codigoproduto", sql.lower())
        self.assertIn("chave", sql.lower())

    def test_batch_retail_sem_codigoproduto(self):
        cur = MagicMock()
        cur.fetchall.side_effect = [
            [{"Field": "chave"}, {"Field": "category_id"}],
            [{"chave": 10, "category_id": 14}],
        ]
        out = _batch_categorias_retail(cur, 1, ["10"])
        self.assertEqual(out, {"10": 14})
        batch_sql = cur.execute.call_args_list[-1][0][0]
        self.assertNotIn("codigoproduto", batch_sql.lower())

    def test_colunas_codigo_ignora_inexistentes(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{"Field": "chave"}, {"Field": "codbarra"}]
        cols = _colunas_codigo_produtos(cur)
        self.assertEqual(cols, ["codbarra"])

    def test_subtotal_retail_sem_codigoproduto_em_produtos(self):
        cur = MagicMock()
        cur.fetchall.side_effect = [
            [{"Field": "chave"}, {"Field": "category_id"}],
            [{"chave": 1, "category_id": 14}],
        ]
        campanha = {"aplica_em": "todos"}
        itens = [{"codigoproduto": "1", "preco": 25, "quantidade": 2}]
        sub = calcular_subtotal_elegivel(cur, 1, itens, campanha, retail=True)
        self.assertEqual(sub, 50.0)
        for call in cur.execute.call_args_list:
            sql = str(call[0][0]).lower()
            self.assertNotIn("coalesce(codigoproduto", sql)


class FreteGratisRetailTests(unittest.TestCase):
    def test_bloqueado_no_varejo(self):
        cur = MagicMock()
        camp = {"ativo": 1, "tipo": "frete_gratis", "aplica_em": "todos"}
        itens = [{"codigoproduto": "1", "preco": 50, "quantidade": 1}]
        ok, msg = campanha_elegivel(cur, 1, camp, itens, origem="DELIVERY", retail=True)
        self.assertFalse(ok)
        self.assertIn("varejo", msg.lower())


class ElegibilidadeRegrasTests(unittest.TestCase):
    def test_subtotal_zero_rejeita_desconto(self):
        cur = MagicMock()
        camp = {
            "ativo": 1,
            "tipo": "desconto_percentual",
            "valor_beneficio": 10,
            "aplica_em": "categorias",
            "categorias_ids": [99],
        }
        itens = [{"codigoproduto": "1", "preco": 50, "quantidade": 1}]
        ok, msg = campanha_elegivel(cur, 1, camp, itens, origem="BALCAO", retail=True)
        self.assertFalse(ok)
        self.assertIn("Nenhum item", msg)

    def test_limite_vigencia_fim_estende_meia_noite(self):
        dt = datetime(2026, 7, 7, 0, 0, 0)
        limite = _limite_vigencia_fim(dt)
        self.assertEqual(limite.hour, 23)
        self.assertEqual(limite.minute, 59)

    def test_campanha_ativa_no_ultimo_dia_ate_fim_do_dia(self):
        df = _coerce_dt("2026-07-07")
        self.assertIsNotNone(df)
        agora_tarde = datetime(2026, 7, 7, 14, 0, 0)
        self.assertLess(df, agora_tarde)
        self.assertGreaterEqual(_limite_vigencia_fim(df), agora_tarde)


class ElegiveisDetalhadoTests(unittest.TestCase):
    @patch("services.campanhas.listar_campanhas")
    def test_indisponivel_quando_inativa(self, mock_listar):
        mock_listar.return_value = [
            {"id": 2, "nome": "Off", "ativo": 0, "tipo": "desconto_percentual", "aplica_em": "todos"},
        ]
        cur = MagicMock()
        out = listar_elegiveis_detalhado(cur, 1, [], origem="BALCAO", retail=True)
        self.assertEqual(out["campanhas"], [])
        self.assertEqual(len(out["indisponiveis"]), 1)
        self.assertEqual(out["indisponiveis"][0]["motivo"], "Campanha inativa.")

    @patch("services.campanhas.listar_campanhas")
    def test_indisponivel_com_motivo_subtotal(self, mock_listar):
        mock_listar.return_value = [
            {
                "id": 1,
                "nome": "Promo Cat",
                "ativo": 1,
                "tipo": "desconto_percentual",
                "valor_beneficio": 10,
                "aplica_em": "categorias",
                "categorias_ids": [99],
            },
        ]
        cur = MagicMock()
        cur.fetchall.side_effect = [
            [{"Field": "chave"}, {"Field": "category_id"}],
            [],
        ]
        itens = [{"codigoproduto": "1", "preco": 50, "quantidade": 1}]
        out = listar_elegiveis_detalhado(cur, 1, itens, origem="BALCAO", retail=True)
        self.assertEqual(out["campanhas"], [])
        self.assertEqual(len(out["indisponiveis"]), 1)
        self.assertIn("Nenhum item", out["indisponiveis"][0]["motivo"])

    @patch("services.campanhas.listar_campanhas")
    def test_elegivel_quando_aplica_todos(self, mock_listar):
        mock_listar.return_value = [
            {
                "id": 3,
                "nome": "Promo Geral",
                "ativo": 1,
                "tipo": "desconto_percentual",
                "valor_beneficio": 10,
                "aplica_em": "todos",
            },
        ]
        cur = MagicMock()
        itens = [{"codigoproduto": "1", "preco": 100, "quantidade": 1}]
        out = listar_elegiveis_detalhado(cur, 1, itens, origem="BALCAO", retail=False)
        self.assertEqual(len(out["campanhas"]), 1)
        self.assertEqual(out["campanhas"][0]["nome"], "Promo Geral")
        self.assertEqual(out["indisponiveis"], [])


class CodClassePedidoTests(unittest.TestCase):
    def test_usa_cod_classe_do_item(self):
        cur = MagicMock()
        base = {"cod_classe": None}
        itens = [{"codigoproduto": "10", "preco": 5, "quantidade": 1, "cod_classe": 3}]
        cc = _resolver_cod_classe_linha_pedido(cur, 1, base, itens, retail=False)
        self.assertEqual(cc, 3)

    def test_retail_permite_none_sem_classificacao(self):
        cur = MagicMock()
        cur.fetchall.return_value = [{"Field": "chave"}, {"Field": "category_id"}]
        cur.fetchone.return_value = {}
        base = {"cod_classe": None}
        itens = [{"codigoproduto": "99", "preco": 5, "quantidade": 1}]
        cc = _resolver_cod_classe_linha_pedido(cur, 1, base, itens, retail=True)
        self.assertIsNone(cc)

    def test_retail_usa_category_id_do_produto(self):
        cur = MagicMock()
        cur.fetchall.side_effect = [
            [{"Field": "chave"}, {"Field": "category_id"}],
            [{"chave": 10, "category_id": 14}],
        ]
        cur.fetchone.return_value = {"category_id": 14}
        base = {"cod_classe": None}
        itens = [{"codigoproduto": "10", "preco": 5, "quantidade": 1}]
        cc = _resolver_cod_classe_linha_pedido(cur, 1, base, itens, retail=True)
        self.assertEqual(cc, 14)

    def test_restaurante_sem_cod_classe_retorna_none(self):
        cur = MagicMock()
        base = {"cod_classe": None}
        itens = [{"codigoproduto": "10", "preco": 5, "quantidade": 1}]
        cc = _resolver_cod_classe_linha_pedido(cur, 1, base, itens, retail=False)
        self.assertIsNone(cc)


if __name__ == "__main__":
    unittest.main()
