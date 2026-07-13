"""Testes de estoque no PDV restaurante e acesso à tela Estoque."""
from __future__ import annotations

import os
import sys
import unittest
import uuid
from urllib.parse import quote

os.environ.setdefault("FLASK_SECRET_KEY", "test-rest-estoque-secret")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

from app import app  # noqa: E402
from database import conectar  # noqa: E402
from services.estoque import ensure_estoque_schema, registrar_movimento  # noqa: E402
from services.retail_catalog_schema import ensure_retail_catalog_schema  # noqa: E402


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


class RestaurantEstoquePdvTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_retail_catalog_schema()
        ensure_estoque_schema()
        cls.rest_id = _find_restaurant_cliente()
        cls.client = app.test_client()
        cls.tag = f"TEST_REST_EST_{uuid.uuid4().hex[:8].upper()}"
        cls.classificacao = f"{cls.tag}_PIZZA"
        cls.prod_ctrl_id: int | None = None
        cls.prod_sem_ctrl_id: int | None = None

    def _json_headers(self):
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def _rest_session(self):
        return self.client.session_transaction()

    @classmethod
    def _ensure_classificacao(cls):
        conn = conectar()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO classificacao (nomeclassificacao, quantidadepartes, nrofoto, id_cliente)
                SELECT %s, 1, 1, %s
                FROM DUAL
                WHERE NOT EXISTS (
                    SELECT 1 FROM classificacao
                    WHERE nomeclassificacao = %s AND id_cliente = %s
                )
                """,
                (cls.classificacao, cls.rest_id, cls.classificacao, cls.rest_id),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()

    @classmethod
    def _setup_produtos(cls):
        if not cls.rest_id:
            return
        cls._ensure_classificacao()
        with cls.client.session_transaction() as sess:
            sess["usuario_logado"] = "test_rest_est"
            sess["id_cliente"] = cls.rest_id
            sess["funcao"] = "gerente"

        for nome, controla in ((f"{cls.tag}_CTRL", 1), (f"{cls.tag}_SEM", 0)):
            codigo_resp = cls.client.get(
                "/api/proximo-codigo-produto",
                headers={"Accept": "application/json"},
            )
            codigo = (codigo_resp.get_json() or {}).get("codigo_sugerido")
            cls.client.post(
                "/api/salvar-produto",
                json={
                    "chave": codigo,
                    "produto": nome,
                    "preco": 12.5,
                    "porkilo": "Nao",
                    "vendaliberada": "Sim",
                    "classe": cls.classificacao,
                    "controla_estoque": controla,
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )

        conn = conectar()
        cur = conn.cursor(dictionary=True)
        try:
            for nome, attr in ((f"{cls.tag}_CTRL", "prod_ctrl_id"), (f"{cls.tag}_SEM", "prod_sem_ctrl_id")):
                cur.execute(
                    "SELECT chave FROM produtos WHERE id_cliente = %s AND produto = %s LIMIT 1",
                    (cls.rest_id, nome),
                )
                row = cur.fetchone()
                setattr(cls, attr, int(row["chave"]) if row else None)
            if cls.prod_ctrl_id:
                registrar_movimento(
                    cls.rest_id,
                    cls.prod_ctrl_id,
                    tipo="entrada",
                    quantidade=5,
                    origem="manual",
                )
        finally:
            cur.close()
            conn.close()

    def setUp(self):
        if not self.rest_id:
            self.skipTest("Nenhuma loja restaurante no banco")
        self.__class__._setup_produtos()

    def test_produtos_por_classificacao_retorna_estoque(self):
        if not self.prod_ctrl_id:
            self.skipTest("Produtos de teste não criados")
        with self._rest_session() as sess:
            sess["usuario_logado"] = "test_rest_est"
            sess["id_cliente"] = self.rest_id
            sess["funcao"] = "gerente"
        url = f"/produtos_por_classificacao/{quote(self.classificacao)}"
        resp = self.client.get(url, headers={"Accept": "application/json"})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        produtos = resp.get_json() or []
        self.assertTrue(isinstance(produtos, list))
        com_ctrl = next((p for p in produtos if int(p["chave"]) == self.prod_ctrl_id), None)
        sem_ctrl = next((p for p in produtos if int(p["chave"]) == self.prod_sem_ctrl_id), None)
        self.assertIsNotNone(com_ctrl)
        self.assertIsNotNone(sem_ctrl)
        self.assertEqual(int(com_ctrl["controla_estoque"]), 1)
        self.assertEqual(float(com_ctrl["estoque_atual"]), 5.0)
        self.assertEqual(int(sem_ctrl["controla_estoque"]), 0)
        self.assertEqual(float(sem_ctrl["estoque_atual"]), 0.0)

    def test_restaurante_acessa_tela_estoque(self):
        with self._rest_session() as sess:
            sess["usuario_logado"] = "test_rest_est"
            sess["id_cliente"] = self.rest_id
            sess["funcao"] = "gerente"
        resp = self.client.get("/estoque")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
