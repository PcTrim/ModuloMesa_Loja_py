"""Taxa de entrega na baixa — linha TXENTREGA em pedido_diarios."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-baixa-taxa-secret")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests.test_env import aplicar_env_teste  # noqa: E402

aplicar_env_teste()

from app import (  # noqa: E402
    TXENTREGA_COD,
    _parse_taxa_entrega_payload,
    _resolver_taxa_entrega_confirmacao,
    _sync_taxa_entrega_linha,
    app,
)


class _DictCursor:
    def __init__(self, fetchone_seq=None, fetchall_seq=None):
        self.executed = []
        self._fetchone_seq = list(fetchone_seq or [])
        self._fetchall_seq = list(fetchall_seq or [])
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self._fetchone_seq:
            return self._fetchone_seq.pop(0)
        return None

    def fetchall(self):
        if self._fetchall_seq:
            return self._fetchall_seq.pop(0)
        return []


class TestParseTaxaEntregaPayload(unittest.TestCase):
    def test_payload_explicito(self):
        self.assertEqual(_parse_taxa_entrega_payload({"taxa_entrega": 8}), 8.0)
        self.assertEqual(_parse_taxa_entrega_payload({"taxa_entrega": "8,50"}), 8.5)
        self.assertEqual(_parse_taxa_entrega_payload({"taxa_entrega": 0}), 0.0)

    def test_ausente_retorna_none(self):
        self.assertIsNone(_parse_taxa_entrega_payload({}))
        self.assertIsNone(_parse_taxa_entrega_payload(None))


class TestSyncTaxaEntregaLinha(unittest.TestCase):
    def test_insere_linha_txentrega(self):
        cur = _DictCursor(
            fetchone_seq=[
                {
                    "telefone": "11999999999",
                    "cep": "01000",
                    "nome": "Cliente",
                    "endereco": "Rua A",
                    "nrocasa": "1",
                    "complemento": "",
                    "cliente": "Cliente",
                    "formapagamento": "PIX",
                    "entregador": "",
                    "origem": "DELIVERY",
                    "status_pedido": "AGUARDE",
                },
                {"max_lancamento": 2},
            ]
        )
        with patch("app._resolver_cod_usuario_logado", return_value=1), patch(
            "app._insert_pedido_diarios_from_casa"
        ) as mock_insert:
            ok = _sync_taxa_entrega_linha(cur, 1739, 64, 8.0)
        self.assertTrue(ok)
        self.assertTrue(any("DELETE" in sql for sql, _ in cur.executed))
        mock_insert.assert_called_once()
        kwargs = mock_insert.call_args.kwargs
        self.assertEqual(kwargs["codigoproduto"], TXENTREGA_COD)
        self.assertEqual(kwargs["produto"], "TAXA ENTREGA")
        self.assertEqual(kwargs["preco"], 8.0)
        self.assertEqual(kwargs["origem"], "DELIVERY")

    def test_taxa_zero_remove_sem_inserir(self):
        cur = _DictCursor(
            fetchone_seq=[
                {
                    "telefone": "11999999999",
                    "cep": "",
                    "nome": "Cliente",
                    "endereco": "",
                    "nrocasa": "",
                    "complemento": "",
                    "cliente": "Cliente",
                    "formapagamento": "",
                    "entregador": "",
                    "origem": "DELIVERY",
                    "status_pedido": "AGUARDE",
                }
            ]
        )
        with patch("app._insert_pedido_diarios_from_casa") as mock_insert:
            ok = _sync_taxa_entrega_linha(cur, 1739, 64, 0)
        self.assertTrue(ok)
        mock_insert.assert_not_called()

    def test_sem_pedido_delivery_retorna_false(self):
        cur = _DictCursor(fetchone_seq=[None])
        self.assertFalse(_sync_taxa_entrega_linha(cur, 1739, 64, 5))


class TestResolverTaxaEntregaConfirmacao(unittest.TestCase):
    def test_prioriza_payload(self):
        cur = _DictCursor()
        val = _resolver_taxa_entrega_confirmacao(cur, 1739, 64, {"taxa_entrega": 7.5})
        self.assertEqual(val, 7.5)
        self.assertEqual(len(cur.executed), 0)

    def test_fallback_cliente(self):
        cur = _DictCursor(
            fetchone_seq=[
                {"telefone": "11971447584"},
            ]
        )
        with patch("app._resolver_taxa_entrega_cliente", return_value=6.0) as mock_cli:
            val = _resolver_taxa_entrega_confirmacao(cur, 1739, 64, {})
        self.assertEqual(val, 6.0)
        mock_cli.assert_called_once_with(cur, 1739, "11971447584")


class TestConfirmarImpressaoDelivery(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "suite-taxa"
            sess["id_cliente"] = 1739

    def test_confirmar_delivery_chama_sync_taxa(self):
        with patch("app._confirmar_pedido_casa_pos_impressao", return_value=None) as mock_conf:
            resp = self.client.post(
                "/api/casa/confirmar-impressao",
                json={"origem": "casa", "nropedido": 64, "taxa_entrega": 8, "printer": "bridge"},
            )
        self.assertEqual(resp.status_code, 200)
        mock_conf.assert_called_once()
        args = mock_conf.call_args[0]
        self.assertEqual(args[1], 64)
        self.assertEqual(args[2].get("taxa_entrega"), 8)


if __name__ == "__main__":
    unittest.main()
