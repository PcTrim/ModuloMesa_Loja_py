"""Testes focados do controle de estoque."""
from __future__ import annotations

import os
import sys
import unittest
import uuid

os.environ.setdefault("FLASK_SECRET_KEY", "test-estoque-secret")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

from app import app  # noqa: E402
from database import conectar  # noqa: E402
from services.estoque import calcular_saldo, ensure_estoque_schema, listar_historico, registrar_movimento  # noqa: E402
from services.retail_catalog_schema import ensure_retail_catalog_schema  # noqa: E402


def _find_retail_cliente() -> int | None:
    conn = conectar()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT id_cliente FROM dadosloja
            WHERE LOWER(TRIM(COALESCE(tipo_negocio, 'restaurante'))) = 'varejo'
            ORDER BY id_cliente
            LIMIT 1
            """
        )
        row = cur.fetchone()
        return int(row["id_cliente"]) if row else None
    finally:
        cur.close()
        conn.close()


class EstoqueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_retail_catalog_schema()
        ensure_estoque_schema()
        cls.retail_id = _find_retail_cliente()
        cls.client = app.test_client()

    def _json_headers(self):
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def setUp(self):
        if not self.retail_id:
            self.skipTest("Nenhuma loja varejo no banco")
        self.tag = f"TEST_ESTOQUE_{uuid.uuid4().hex[:8].upper()}"
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "test_estoque"
            sess["id_cliente"] = self.retail_id
            sess["funcao"] = "gerente"

        cat_resp = self.client.post(
            "/api/retail/categorias",
            json={"nome": f"{self.tag}_CAT", "ordem_exibicao": 1, "ativo": 1},
            headers=self._json_headers(),
        )
        self.assertEqual(cat_resp.status_code, 200, cat_resp.get_data(as_text=True))
        self.cat_id = int((cat_resp.get_json() or {})["id"])

        codigo_resp = self.client.get("/api/proximo-codigo-produto", headers={"Accept": "application/json"})
        codigo = (codigo_resp.get_json() or {}).get("codigo_sugerido")
        resp = self.client.post(
            "/api/salvar-produto",
            json={
                "chave": codigo,
                "produto": self.tag,
                "preco": 10,
                "porkilo": "Nao",
                "vendaliberada": "Sim",
                "controla_estoque": 1,
                "category_id": self.cat_id,
                "retail": {"estoque_minimo": 1, "ativo": 1},
            },
            headers=self._json_headers(),
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))

        conn = conectar()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT chave FROM produtos WHERE id_cliente = %s AND produto = %s LIMIT 1",
                (self.retail_id, self.tag),
            )
            row = cur.fetchone()
            self.produto_id = int(row["chave"])
        finally:
            cur.close()
            conn.close()

    def tearDown(self):
        conn = conectar()
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM estoque_movimentos WHERE id_cliente = %s AND produto_id = %s",
                (self.retail_id, self.produto_id),
            )
            cur.execute(
                "DELETE FROM produto_retail WHERE id_cliente = %s AND product_id = %s",
                (self.retail_id, self.produto_id),
            )
            cur.execute(
                "DELETE FROM produtos WHERE id_cliente = %s AND chave = %s",
                (self.retail_id, self.produto_id),
            )
            cur.execute(
                "DELETE FROM categoria WHERE id = %s AND id_cliente = %s",
                (self.cat_id, self.retail_id),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def test_saldo_e_historico_por_movimentos(self):
        registrar_movimento(self.retail_id, self.produto_id, tipo="entrada", quantidade=5, origem="manual")
        registrar_movimento(self.retail_id, self.produto_id, tipo="ajuste", quantidade=1, origem="manual")

        self.assertEqual(calcular_saldo(self.retail_id, self.produto_id), 4.0)
        historico = listar_historico(self.retail_id, self.produto_id)
        self.assertTrue(historico)
        self.assertEqual(historico[0]["descricao"], "Ajuste -1")

    def test_venda_nao_duplica_movimento(self):
        primeiro = registrar_movimento(
            self.retail_id,
            self.produto_id,
            tipo="venda",
            quantidade=2,
            nropedido=999001,
            origem="venda",
        )
        segundo = registrar_movimento(
            self.retail_id,
            self.produto_id,
            tipo="venda",
            quantidade=2,
            nropedido=999001,
            origem="venda",
        )

        self.assertFalse(primeiro["duplicado"])
        self.assertTrue(segundo["duplicado"])

        conn = conectar()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                """
                SELECT COUNT(*) AS total
                FROM estoque_movimentos
                WHERE id_cliente = %s AND produto_id = %s AND nropedido = %s AND tipo = 'venda'
                """,
                (self.retail_id, self.produto_id, 999001),
            )
            row = cur.fetchone()
            self.assertEqual(int(row["total"]), 1)
        finally:
            cur.close()
            conn.close()

    def test_rotas_estoque_http(self):
        lista = self.client.get("/estoque")
        self.assertEqual(lista.status_code, 200)

        detalhe = self.client.get(f"/estoque/{self.produto_id}")
        self.assertEqual(detalhe.status_code, 200)

        entrada = self.client.post(
            "/estoque/entrada",
            json={"produto_id": self.produto_id, "quantidade": 3},
            headers=self._json_headers(),
        )
        self.assertEqual(entrada.status_code, 200, entrada.get_data(as_text=True))
        self.assertTrue((entrada.get_json() or {}).get("sucesso"))

        historico = self.client.get(
            f"/estoque/{self.produto_id}/historico",
            headers=self._json_headers(),
        )
        self.assertEqual(historico.status_code, 200)
        hist_data = historico.get_json() or {}
        self.assertTrue(hist_data.get("sucesso"))
        self.assertTrue(hist_data.get("historico"))

        ajuste = self.client.post(
            "/estoque/ajuste",
            json={"produto_id": self.produto_id, "quantidade": 1},
            headers=self._json_headers(),
        )
        self.assertEqual(ajuste.status_code, 200, ajuste.get_data(as_text=True))
        self.assertTrue((ajuste.get_json() or {}).get("sucesso"))
        self.assertEqual(calcular_saldo(self.retail_id, self.produto_id), 2.0)


if __name__ == "__main__":
    unittest.main()
