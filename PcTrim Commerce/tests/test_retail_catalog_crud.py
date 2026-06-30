"""Testes do CRUD do catálogo retail."""
from __future__ import annotations

import os
import sys
import unittest
import uuid

os.environ.setdefault("FLASK_SECRET_KEY", "test-retail-catalog-secret")

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


class RetailCatalogCrudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_retail_catalog_schema()
        cls.retail_id = _find_retail_cliente()
        cls.rest_id = _find_restaurant_cliente()
        cls.client = app.test_client()
        cls.tag = f"TEST_RETAIL_{uuid.uuid4().hex[:8].upper()}"
        cls.created_categoria_id: int | None = None
        cls.created_subcategoria_id: int | None = None
        cls.created_produto_id: int | None = None

    def _json_headers(self):
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def test_retail_only_blocks_restaurant(self):
        if not self.rest_id:
            self.skipTest("Nenhuma loja restaurante no banco")
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "test_rest"
            sess["id_cliente"] = self.rest_id
            sess["funcao"] = "gerente"
        resp = self.client.get("/api/retail/categorias", headers=self._json_headers())
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertFalse(data.get("sucesso"))

    def test_categoria_subcategoria_produto_retail_flow(self):
        if not self.retail_id:
            self.skipTest("Nenhuma loja varejo no banco")
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "test_retail"
            sess["id_cliente"] = self.retail_id
            sess["funcao"] = "gerente"

        nome_cat = f"{self.tag}_CAT"
        resp = self.client.post(
            "/api/retail/categorias",
            json={"nome": nome_cat, "ordem_exibicao": 1, "ativo": 1},
            headers=self._json_headers(),
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        data = resp.get_json()
        self.assertTrue(data.get("sucesso"))
        cat_id = int(data["id"])
        self.__class__.created_categoria_id = cat_id

        dup = self.client.post(
            "/api/retail/categorias",
            json={"nome": nome_cat, "ordem_exibicao": 2, "ativo": 1},
            headers=self._json_headers(),
        )
        self.assertIn(dup.status_code, (409, 500))

        nome_sub = f"{self.tag}_SUB"
        resp_sub = self.client.post(
            "/api/retail/subcategorias",
            json={"categoria_id": cat_id, "nome": nome_sub, "ordem_exibicao": 1, "ativo": 1},
            headers=self._json_headers(),
        )
        self.assertEqual(resp_sub.status_code, 200, resp_sub.get_data(as_text=True))
        sub_data = resp_sub.get_json()
        self.assertTrue(sub_data.get("sucesso"))
        sub_id = int(sub_data["id"])
        self.__class__.created_subcategoria_id = sub_id

        list_resp = self.client.get(
            f"/api/retail/subcategorias?categoria_id={cat_id}",
            headers=self._json_headers(),
        )
        self.assertEqual(list_resp.status_code, 200)
        listed = list_resp.get_json().get("subcategorias") or []
        self.assertTrue(any(int(r["id"]) == sub_id for r in listed))

        code_resp = self.client.get("/api/proximo-codigo-produto", headers=self._json_headers())
        codigo = (code_resp.get_json() or {}).get("codigo_sugerido")
        prod_nome = f"{self.tag}_PROD"
        prod_resp = self.client.post(
            "/api/salvar-produto",
            json={
                "chave": codigo,
                "produto": prod_nome,
                "preco": 9.99,
                "classe": "TESTE",
                "porkilo": "Nao",
                "vendaliberada": "Sim",
                "category_id": cat_id,
                "subcategory_id": sub_id,
                "retail": {
                    "nome_vitrine": f"{prod_nome} Vitrine",
                    "estoque": 5,
                    "destaque": 1,
                    "ativo": 1,
                },
            },
            headers=self._json_headers(),
        )
        self.assertEqual(prod_resp.status_code, 200, prod_resp.get_data(as_text=True))
        prod_data = prod_resp.get_json()
        self.assertTrue(prod_data.get("sucesso"))

        conn = conectar()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                """
                SELECT p.chave, p.category_id, p.subcategory_id, pr.estoque, pr.nome_vitrine
                FROM produtos p
                LEFT JOIN produto_retail pr ON pr.product_id = p.chave AND pr.id_cliente = p.id_cliente
                WHERE p.id_cliente = %s AND p.produto = %s
                LIMIT 1
                """,
                (self.retail_id, prod_nome),
            )
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.__class__.created_produto_id = int(row["chave"])
            self.assertEqual(int(row["category_id"]), cat_id)
            self.assertEqual(int(row["subcategory_id"]), sub_id)
            self.assertEqual(float(row["estoque"]), 5.0)
        finally:
            cur.close()
            conn.close()

        upd = self.client.put(
            f"/api/editar-produto/{self.created_produto_id}",
            json={
                "produto": prod_nome,
                "preco": 10.5,
                "classe": "TESTE",
                "porkilo": "Nao",
                "vendaliberada": "Sim",
                "category_id": cat_id,
                "subcategory_id": sub_id,
                "retail": {"estoque": 7, "ativo": 1},
            },
            headers=self._json_headers(),
        )
        self.assertEqual(upd.status_code, 200, upd.get_data(as_text=True))

        conn = conectar()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT estoque FROM produto_retail WHERE product_id = %s AND id_cliente = %s",
                (self.created_produto_id, self.retail_id),
            )
            pr = cur.fetchone()
            self.assertEqual(float(pr["estoque"]), 7.0)

            cur.execute(
                "SELECT COUNT(*) AS n FROM produto_retail WHERE product_id = %s AND id_cliente = %s",
                (self.created_produto_id, self.retail_id),
            )
            cnt = cur.fetchone()
            self.assertEqual(int(cnt["n"]), 1)
        finally:
            cur.close()
            conn.close()

    @classmethod
    def tearDownClass(cls):
        if not cls.retail_id:
            return
        conn = conectar()
        cur = conn.cursor()
        try:
            if cls.created_produto_id:
                cur.execute(
                    "DELETE FROM produtos WHERE chave = %s AND id_cliente = %s",
                    (cls.created_produto_id, cls.retail_id),
                )
            cur.execute(
                "DELETE FROM subcategoria WHERE id_cliente = %s AND nome LIKE %s",
                (cls.retail_id, f"{cls.tag}%"),
            )
            cur.execute(
                "DELETE FROM categoria WHERE id_cliente = %s AND nome LIKE %s",
                (cls.retail_id, f"{cls.tag}%"),
            )
            cur.execute(
                "DELETE FROM produtos WHERE id_cliente = %s AND produto LIKE %s",
                (cls.retail_id, f"{cls.tag}%"),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()


if __name__ == "__main__":
    unittest.main()
