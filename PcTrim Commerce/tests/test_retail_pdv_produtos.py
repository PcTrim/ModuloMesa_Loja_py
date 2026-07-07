"""Testes do endpoint PDV retail (produtos por categoria/subcategoria)."""
from __future__ import annotations

import os
import sys
import unittest
import uuid

os.environ.setdefault("FLASK_SECRET_KEY", "test-retail-pdv-secret")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

from app import app  # noqa: E402
from database import conectar  # noqa: E402
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


def _find_restaurant_cliente() -> int | None:
    conn = conectar()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT id_cliente FROM dadosloja
            WHERE LOWER(TRIM(COALESCE(tipo_negocio, 'restaurante'))) != 'varejo'
            ORDER BY id_cliente
            LIMIT 1
            """
        )
        row = cur.fetchone()
        return int(row["id_cliente"]) if row else None
    finally:
        cur.close()
        conn.close()


class RetailPdvProdutosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_retail_catalog_schema()
        cls.retail_id = _find_retail_cliente()
        cls.rest_id = _find_restaurant_cliente()
        cls.client = app.test_client()
        cls.tag = f"TEST_PDV_{uuid.uuid4().hex[:8].upper()}"
        cls.cat_id: int | None = None
        cls.sub_id: int | None = None
        cls.prod_com_sub_id: int | None = None
        cls.prod_sem_sub_id: int | None = None

    def _json_headers(self):
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def _retail_session(self):
        if not self.retail_id:
            self.skipTest("Nenhuma loja varejo no banco")
        return self.client.session_transaction()

    @classmethod
    def _setup_catalog(cls):
        if not cls.retail_id or cls.cat_id:
            return
        with cls.client.session_transaction() as sess:
            sess["usuario_logado"] = "test_pdv_retail"
            sess["id_cliente"] = cls.retail_id
            sess["funcao"] = "gerente"

        resp = cls.client.post(
            "/api/retail/categorias",
            json={"nome": f"{cls.tag}_CAT", "ordem_exibicao": 1, "ativo": 1},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        cls.cat_id = int(resp.get_json()["id"])

        resp_sub = cls.client.post(
            "/api/retail/subcategorias",
            json={"categoria_id": cls.cat_id, "nome": f"{cls.tag}_SUB", "ordem_exibicao": 1, "ativo": 1},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        cls.sub_id = int(resp_sub.get_json()["id"])

        code_resp = cls.client.get("/api/proximo-codigo-produto", headers={"Accept": "application/json"})
        codigo1 = (code_resp.get_json() or {}).get("codigo_sugerido")
        cls.client.post(
            "/api/salvar-produto",
            json={
                "chave": codigo1,
                "produto": f"{cls.tag}_COM_SUB",
                "preco": 19.9,
                "classe": "TESTE",
                "porkilo": "Nao",
                "vendaliberada": "Sim",
                "category_id": cls.cat_id,
                "subcategory_id": cls.sub_id,
                "retail": {"estoque": 1, "ativo": 1, "preco_varejo": 19.9},
            },
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )

        code_resp2 = cls.client.get("/api/proximo-codigo-produto", headers={"Accept": "application/json"})
        codigo2 = (code_resp2.get_json() or {}).get("codigo_sugerido")
        cls.client.post(
            "/api/salvar-produto",
            json={
                "chave": codigo2,
                "produto": f"{cls.tag}_SEM_SUB",
                "preco": 9.9,
                "classe": "TESTE",
                "porkilo": "Nao",
                "vendaliberada": "Sim",
                "category_id": cls.cat_id,
                "retail": {"estoque": 1, "ativo": 1, "preco_varejo": 9.9},
            },
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )

        conn = conectar()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT chave FROM produtos WHERE id_cliente = %s AND produto = %s LIMIT 1",
                (cls.retail_id, f"{cls.tag}_COM_SUB"),
            )
            row = cur.fetchone()
            cls.prod_com_sub_id = int(row["chave"]) if row else None
            cur.execute(
                "SELECT chave FROM produtos WHERE id_cliente = %s AND produto = %s LIMIT 1",
                (cls.retail_id, f"{cls.tag}_SEM_SUB"),
            )
            row2 = cur.fetchone()
            cls.prod_sem_sub_id = int(row2["chave"]) if row2 else None
        finally:
            cur.close()
            conn.close()

    def setUp(self):
        self.__class__._setup_catalog()

    def test_categoria_obrigatoria_retorna_400(self):
        with self._retail_session() as sess:
            sess["usuario_logado"] = "test_pdv"
            sess["id_cliente"] = self.retail_id
            sess["funcao"] = "gerente"
        resp = self.client.get("/api/retail/pdv/produtos", headers=self._json_headers())
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data.get("sucesso"))

    def test_restaurante_nao_acessa_endpoint(self):
        if not self.rest_id:
            self.skipTest("Nenhuma loja restaurante no banco")
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "test_rest"
            sess["id_cliente"] = self.rest_id
            sess["funcao"] = "gerente"
        resp = self.client.get("/api/retail/pdv/produtos?categoria_id=1", headers=self._json_headers())
        self.assertEqual(resp.status_code, 403)

    def test_todos_inclui_produto_sem_subcategoria(self):
        if not self.cat_id:
            self.skipTest("Catálogo de teste não criado")
        with self._retail_session() as sess:
            sess["usuario_logado"] = "test_pdv"
            sess["id_cliente"] = self.retail_id
            sess["funcao"] = "gerente"
        resp = self.client.get(
            f"/api/retail/pdv/produtos?categoria_id={self.cat_id}",
            headers=self._json_headers(),
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        produtos = resp.get_json().get("produtos") or []
        chaves = {int(p["chave"]) for p in produtos}
        self.assertIn(self.prod_com_sub_id, chaves)
        self.assertIn(self.prod_sem_sub_id, chaves)
        self.assertLessEqual(len(produtos), 200)

    def test_subcategoria_filtra_corretamente(self):
        if not self.cat_id or not self.sub_id:
            self.skipTest("Catálogo de teste não criado")
        with self._retail_session() as sess:
            sess["usuario_logado"] = "test_pdv"
            sess["id_cliente"] = self.retail_id
            sess["funcao"] = "gerente"
        resp = self.client.get(
            f"/api/retail/pdv/produtos?categoria_id={self.cat_id}&subcategoria_id={self.sub_id}",
            headers=self._json_headers(),
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        produtos = resp.get_json().get("produtos") or []
        chaves = {int(p["chave"]) for p in produtos}
        self.assertIn(self.prod_com_sub_id, chaves)
        self.assertNotIn(self.prod_sem_sub_id, chaves)


if __name__ == "__main__":
    unittest.main()
