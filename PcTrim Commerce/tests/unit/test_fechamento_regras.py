import os
import unittest

os.environ.setdefault("FLASK_SECRET_KEY", "test-suite-secret")

from services import fechamento_periodo


class FechamentoPeriodoRulesTests(unittest.TestCase):
    def test_intervalo_datetimes_aceita_mesmo_dia(self):
        d0, d1 = fechamento_periodo.intervalo_datetimes("2026-07-01", "2026-07-01")
        self.assertLess(d0, d1)
        self.assertEqual((d1 - d0).days, 1)

    def test_intervalo_datetimes_rejeita_intervalo_invertido(self):
        with self.assertRaises(ValueError):
            fechamento_periodo.intervalo_datetimes("2026-07-02", "2026-07-01")

    def test_normalizar_forma_pagamento_agrupa_rotulos_livres(self):
        self.assertEqual(fechamento_periodo._normalizar_forma_pagamento("pix qrcode"), "PIX")
        self.assertEqual(fechamento_periodo._normalizar_forma_pagamento("cartao credito"), "Cartão crédito")
        self.assertEqual(fechamento_periodo._normalizar_forma_pagamento("vale refeicao"), "Vale/refeição")
        self.assertEqual(fechamento_periodo._normalizar_forma_pagamento(""), "Outros")

    def test_parse_baixa_pagamentos_json_retorna_none_quando_payload_e_invalido(self):
        self.assertIsNone(fechamento_periodo._parse_baixa_pagamentos_json(""))
        self.assertIsNone(fechamento_periodo._parse_baixa_pagamentos_json("{malformado"))
        self.assertIsNone(fechamento_periodo._parse_baixa_pagamentos_json('{"pagamentos":"pix"}'))

    def test_parse_baixa_pagamentos_json_filtra_itens_invalidos(self):
        raw = (
            '{"pagamentos": ['
            '{"forma":"PIX","valor":10},'
            '{"forma":"","valor":5},'
            '"texto solto",'
            '{"forma":"Dinheiro","valor":"3.5"}'
            ']}'
        )
        pagamentos = fechamento_periodo._parse_baixa_pagamentos_json(raw)
        self.assertEqual(
            pagamentos,
            [
                {"forma": "PIX", "valor": 10.0},
                {"forma": "Dinheiro", "valor": 3.5},
            ],
        )


class FechamentoArquivamentoWhereTests(unittest.TestCase):
    def test_where_fechamento_nao_inclui_cancelada(self):
        d0, d1 = fechamento_periodo.intervalo_datetimes("2026-07-01", "2026-07-01")
        sql, _params = fechamento_periodo._where_fechamento(2001, d0, d1)
        self.assertNotIn("status_comanda", sql.upper())

    def test_where_fechamento_arquivamento_inclui_cancelada(self):
        d0, d1 = fechamento_periodo.intervalo_datetimes("2026-07-01", "2026-07-01")
        sql, params = fechamento_periodo._where_fechamento_arquivamento(2001, d0, d1)
        self.assertIn("CANCELADA", sql.upper())
        self.assertEqual(params[0], 2001)

    def test_sql_grupo_status_arquivamento_prioriza_cancelada(self):
        grp = fechamento_periodo._sql_grupo_status_arquivamento().upper()
        self.assertIn("CANCELADA", grp)
        self.assertLess(grp.index("CANCELADA"), grp.index("ITEM_REMOVIDO"))


if __name__ == "__main__":
    unittest.main()
