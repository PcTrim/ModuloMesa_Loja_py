"""Testes — clientes Interno para cadastro de loja."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")
os.environ.setdefault("PLATFORM_ADMIN_USERS", "marcio,suporte")

from app import app
from services.clientes_internos import (
    ClientesInternosError,
    MSG_JA_EM_USO,
    ensure_cliente_disponivel_para_loja,
    invalidate_clientes_internos_cache,
    list_clientes_internos_disponiveis,
)


class ClientesInternosServiceTests(unittest.TestCase):
    def setUp(self):
        invalidate_clientes_internos_cache()

    @patch.dict(
        "os.environ",
        {
            "MYSQL_HOST": "127.0.0.1",
            "MYSQL_PORT": "3308",
            "MYSQL_USER": "app",
            "MYSQL_PASSWORD": "app_pw",
            "MYSQL_HOST_INTERNO": "92.113.33.100",
            "MYSQL_PORT_INTERNO": "3308",
            "MYSQL_USER_INTERNO": "root",
            "MYSQL_PASSWORD_INTERNO": "root_pw",
            "MYSQL_DATABASE_INTERNO": "interno",
        },
        clear=False,
    )
    def test_interno_db_profile_uses_overrides(self):
        from importlib import reload

        import config as config_mod

        reload(config_mod)
        profile = config_mod.Config.interno_db_profile()
        self.assertEqual(profile["host"], "92.113.33.100")
        self.assertEqual(profile["port"], 3308)
        self.assertEqual(profile["user"], "root")
        self.assertEqual(profile["password"], "root_pw")
        self.assertEqual(profile["database"], "interno")

    @patch("services.clientes_internos.collect_id_clientes_em_uso", return_value={2003})
    @patch("services.clientes_internos.fetch_clientes_ativos")
    def test_excludes_registered_and_inactive(self, mock_fetch, _mock_used):
        mock_fetch.return_value = [
            {"id": 1001, "cliente": "A", "fantasia": "FA", "documento": "1"},
            {"id": 2003, "cliente": "B", "fantasia": "FB", "documento": "2"},
        ]
        rows = list_clientes_internos_disponiveis(use_cache=False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 1001)
        self.assertIn("A - FA - 1001", rows[0]["label"])

    @patch("services.clientes_internos.fetch_cliente_ativo_by_id")
    @patch("services.clientes_internos.collect_id_clientes_em_uso", return_value={2005})
    def test_ensure_blocks_duplicate(self, _mock_used, mock_one):
        mock_one.return_value = {"id": 2005, "cliente": "X", "fantasia": "Y", "documento": ""}
        with self.assertRaises(Exception) as ctx:
            ensure_cliente_disponivel_para_loja(2005)
        self.assertEqual(ctx.exception.message, MSG_JA_EM_USO)

    @patch("services.clientes_internos.collect_id_clientes_em_uso", return_value=set())
    @patch("services.clientes_internos.fetch_cliente_ativo_by_id")
    def test_ensure_allows_active_available(self, mock_one, _mock_used):
        mock_one.return_value = {"id": 2005, "cliente": "X", "fantasia": "Y", "documento": ""}
        row = ensure_cliente_disponivel_para_loja(2005)
        self.assertEqual(row["id"], 2005)


class ClientesInternosApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._ctx = app.app_context()
        self._ctx.push()

    def tearDown(self):
        self._ctx.pop()
        invalidate_clientes_internos_cache()

    @patch("blueprints.platform_admin.list_clientes_internos_disponiveis")
    def test_api_list_requires_admin(self, mock_list):
        mock_list.return_value = []
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "marcio"
            sess["id_cliente"] = 2001
            sess["funcao"] = "gerente"
        r = self.client.get("/api/clientes-internos-disponiveis")
        self.assertEqual(r.status_code, 200)
        mock_list.assert_called_once()

    @patch("blueprints.platform_admin.ensure_cliente_disponivel_para_loja")
    @patch("blueprints.platform_admin.provision_tenant")
    def test_create_duplicate_returns_409(self, mock_prov, mock_ensure):
        mock_ensure.side_effect = ClientesInternosError(MSG_JA_EM_USO, status=409)
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "marcio"
            sess["id_cliente"] = 2001
            sess["funcao"] = "gerente"
        r = self.client.post(
            "/api/admin/lojas",
            json={
                "nome": "L",
                "usuario": "u",
                "senha": "1234",
                "senha_confirmacao": "1234",
                "id_cliente": 2005,
            },
        )
        self.assertEqual(r.status_code, 409)
        data = r.get_json()
        self.assertIn("já está em uso", data.get("erro", ""))
        mock_prov.assert_not_called()

    @patch("blueprints.platform_admin.ensure_cliente_disponivel_para_loja")
    @patch("blueprints.platform_admin.provision_tenant")
    def test_create_requires_id_cliente(self, mock_prov, mock_ensure):
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "marcio"
            sess["id_cliente"] = 2001
            sess["funcao"] = "gerente"
        r = self.client.post(
            "/api/admin/lojas",
            json={"nome": "L", "usuario": "u", "senha": "1234", "senha_confirmacao": "1234"},
        )
        self.assertEqual(r.status_code, 400)
        mock_prov.assert_not_called()
        mock_ensure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
