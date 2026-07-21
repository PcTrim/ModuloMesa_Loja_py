"""Validação impressão/distribuição — loja 2003 homolog (modo restaurante)."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch
from urllib.parse import quote

os.environ.setdefault("FLASK_SECRET_KEY", "test-impressao-2003-secret")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests.test_env import aplicar_env_teste, test_db_configured  # noqa: E402

aplicar_env_teste()

from app import (  # noqa: E402
    _preencher_impressoras_produto,
    app,
    resolver_impressora,
)
from config import Config  # noqa: E402
from database import TENANT_DB_SESSION_KEY, conectar_admin  # noqa: E402

ID_CLIENTE = 2003
PRODUTO_CHAVE = 148
CLASSE_TESTE = "TESTE"
RETAIL_CLASSES = ("BRINCOS", "COLARES")


def _hml_disponivel() -> bool:
    if not test_db_configured():
        return False
    if not Config.admin_db_configured("homologation"):
        return False
    try:
        conn = conectar_admin("homologation")
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
        finally:
            conn.close()
        return True
    except Exception:
        return False


def _session_2003():
    return {
        "usuario_logado": "test_impressao_2003",
        "id_cliente": ID_CLIENTE,
        "funcao": "gerente",
        TENANT_DB_SESSION_KEY: "homologation",
    }


class _Cursor:
    def __init__(self, fetchone_seq=None, fetchall_seq=None):
        self.executed = []
        self._fetchone_seq = list(fetchone_seq or [])
        self._fetchall_seq = list(fetchall_seq or [])

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

    @property
    def rowcount(self):
        return 1

    def close(self):
        return None


class _Conn:
    def __init__(self, fetchone_seq=None, fetchall_seq=None):
        self.cursor_obj = _Cursor(fetchone_seq=fetchone_seq, fetchall_seq=fetchall_seq)
        self.committed = False
        self.rolled_back = False

    def cursor(self, dictionary=False):
        return self.cursor_obj

    def start_transaction(self):
        return None

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        return None


@unittest.skipUnless(_hml_disponivel(), "Dependência de ambiente externo (MySQL HML/E2E)")
class ImpressaoDistribuicao2003Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        conn = conectar_admin("homologation")
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT chave FROM produtos WHERE id_cliente=%s AND chave=%s LIMIT 1",
                (ID_CLIENTE, PRODUTO_CHAVE),
            )
            cls.produto_existe = cur.fetchone() is not None
            cur.execute(
                "SELECT impressora FROM classificacao "
                "WHERE id_cliente=%s AND UPPER(TRIM(nomeclassificacao))=%s LIMIT 1",
                (ID_CLIENTE, CLASSE_TESTE),
            )
            row = cur.fetchone()
            cls.setor_classificacao = row.get("impressora") if row else None
        finally:
            cur.close()
            conn.close()

    def _with_session(self):
        return self.client.session_transaction()

    def test_produto_148_visivel_no_pdv(self):
        if not self.produto_existe:
            self.skipTest("Produto #148 ausente no HML")
        with self._with_session() as sess:
            for k, v in _session_2003().items():
                sess[k] = v
        url = f"/produtos_por_classificacao/{quote(CLASSE_TESTE)}"
        resp = self.client.get(url, headers={"Accept": "application/json"})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        produtos = resp.get_json() or []
        self.assertTrue(isinstance(produtos, list))
        chaves = {int(p["chave"]) for p in produtos}
        self.assertIn(PRODUTO_CHAVE, chaves)

    def test_retail_legacy_nao_aparece_no_pdv(self):
        with self._with_session() as sess:
            for k, v in _session_2003().items():
                sess[k] = v
        for classe in RETAIL_CLASSES:
            url = f"/produtos_por_classificacao/{quote(classe)}"
            resp = self.client.get(url, headers={"Accept": "application/json"})
            produtos = resp.get_json() if resp.status_code == 200 else []
            if resp.status_code == 404:
                # Sem classificação retail cadastrada — PDV não expõe a aba.
                continue
            self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
            self.assertEqual(produtos, [], f"Esperado vazio para classe retail {classe}")

    def test_resolver_impressora_produto_148(self):
        if not self.produto_existe:
            self.skipTest("Produto #148 ausente no HML")
        conn = conectar_admin("homologation")
        cur = conn.cursor(dictionary=True)
        try:
            setor = resolver_impressora(cur, ID_CLIENTE, str(PRODUTO_CHAVE))
        finally:
            cur.close()
            conn.close()
        self.assertIsNotNone(setor, "Produto/classificação deve ter setor de impressão")
        if self.setor_classificacao is not None:
            self.assertEqual(str(setor), str(int(self.setor_classificacao)))

    def test_preencher_impressoras_produto_simula_pedido(self):
        if not self.produto_existe:
            self.skipTest("Produto #148 ausente no HML")
        conn = conectar_admin("homologation")
        cur = conn.cursor(dictionary=True)
        rows = [{"codigoproduto": str(PRODUTO_CHAVE), "impressoras_produto": ""}]
        try:
            _preencher_impressoras_produto(cur, ID_CLIENTE, rows)
        finally:
            cur.close()
            conn.close()
        preenchido = str(rows[0].get("impressoras_produto") or "").strip()
        self.assertTrue(preenchido, "impressoras_produto deve ser preenchido via cascata produto/classificação")

    def test_casa_balcao_item_148_retorna_setor_para_distribuicao(self):
        """Simula pedido balcão e valida setor para distribuição de preparo."""
        if not self.produto_existe:
            self.skipTest("Produto #148 ausente no HML")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        with self._with_session() as sess:
            for k, v in _session_2003().items():
                sess[k] = v
        payload = {
            "modo": "BALCAO",
            "telefone": "BALCAO-TESTE-IMP2003",
            "item": {
                "nome": "TESTE PRODUTO",
                "codigoproduto": str(PRODUTO_CHAVE),
                "preco": 50.0,
                "qtd": 1,
                "classe": CLASSE_TESTE,
            },
        }
        resp_add = self.client.post("/api/casa/item", json=payload, headers=headers)
        self.assertEqual(resp_add.status_code, 200, resp_add.get_data(as_text=True))
        data_add = resp_add.get_json() or {}
        self.assertTrue(data_add.get("sucesso"), data_add)
        nropedido = int(data_add["nropedido"])
        item_id = int(data_add.get("id") or 0)

        resp_list = self.client.get(
            f"/api/casa/{nropedido}?modo=balcao",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(resp_list.status_code, 200, resp_list.get_data(as_text=True))
        body = resp_list.get_json() or {}
        registros = body.get("registros") or []
        alvo = next(
            (r for r in registros if str(r.get("codigoproduto")) == str(PRODUTO_CHAVE)),
            None,
        )
        self.assertIsNotNone(alvo, "Item #148 deve aparecer no pedido balcão")
        setor = str(alvo.get("impressoras_produto") if alvo.get("impressoras_produto") is not None else "").strip()
        self.assertTrue(setor or alvo.get("impressoras_produto") == 0, "impressoras_produto deve estar preenchido para distribuição")
        self.assertEqual(setor, str(int(self.setor_classificacao or 0)))

        # Limpeza: remove item de teste
        if item_id:
            conn = conectar_admin("homologation")
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM pedido_diarios WHERE id_cliente=%s AND chave=%s",
                    (ID_CLIENTE, item_id),
                )
                conn.commit()
            finally:
                cur.close()
                conn.close()


class ImprenroZeroJsContractTests(unittest.TestCase):
    """Documenta contrato: setor 0 não pode ser descartado como falsy (bug || vs ??)."""

    def _fmt_setor_frontend_buggy(self, v):
        return str(v or "")

    def _fmt_setor_frontend_fixed(self, v):
        return str(v if v is not None else "")

    def test_imprenro_zero_nao_vira_vazio_com_coalescencia_nula(self):
        self.assertEqual(self._fmt_setor_frontend_buggy(0), "")
        self.assertEqual(self._fmt_setor_frontend_fixed(0), "0")

    def test_imprenro_null_continua_vazio(self):
        self.assertEqual(self._fmt_setor_frontend_fixed(None), "")


class PreparoImpressaoMockTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            for k, v in _session_2003().items():
                sess[k] = v

    def test_api_preparo_marcar_mock(self):
        fake_conn = _Conn(
            fetchall_seq=[
                [(999001, "N")],
            ]
        )
        with patch("app.conectar", return_value=fake_conn), patch(
            "app._ensure_pedido_diarios_preparo_columns",
            return_value=None,
        ):
            resp = self.client.post(
                "/api/preparo/marcar",
                json={"ids": [999001]},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertTrue(data.get("sucesso"))
        self.assertTrue(fake_conn.committed)
        self.assertTrue(any("UPDATE pedido_diarios" in sql for sql, _ in fake_conn.cursor_obj.executed))

    @patch("app.conectar", return_value=_Conn())
    @patch("app.send_to_printer", return_value=(True, None))
    @patch("app.terminal_impressao_service.get_printer_path", return_value="USB")
    @patch("app.terminal_impressao_service.terminal_is_configured", return_value=True)
    def test_imprimir_preparo_com_terminal(
        self,
        _mock_terminal_config,
        _mock_get_printer_path,
        _mock_send_to_printer,
        _mock_conectar,
    ):
        resp = self.client.post(
            "/imprimir",
            json={
                "conteudo": "PREPARO TESTE",
                "copias": 1,
                "origem": "preparo",
                "terminal_id": "PC-USER",
                "impressora_id": 6,
            },
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertTrue(data.get("sucesso"))


if __name__ == "__main__":
    unittest.main()
