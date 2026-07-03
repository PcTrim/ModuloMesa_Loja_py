"""Testes de roteamento MySQL por ambiente da loja."""
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

from config import Config
from database import TENANT_DB_SESSION_KEY, resolve_tenant_db_target
from services.loja_ambiente import fetch_loja_ambiente_for_cliente, banner_for_loja, normalize_ambiente
from services.login_tenant_db import LoginAmbienteError, locate_login_user


class TenantDbTargetTests(unittest.TestCase):
    def test_resolve_from_session(self):
        sess = {TENANT_DB_SESSION_KEY: "homologation"}
        self.assertEqual(resolve_tenant_db_target(sess), "homologation")

    def test_resolve_none_without_session(self):
        self.assertIsNone(resolve_tenant_db_target({}))

    @patch("services.loja_ambiente.fetch_loja_ambiente_for_cliente")
    def test_resolve_live_from_dadosloja_when_logged_in(self, mock_fetch):
        mock_fetch.return_value = "homologation"
        sess = {TENANT_DB_SESSION_KEY: "production", "id_cliente": 2003}
        self.assertEqual(resolve_tenant_db_target(sess), "homologation")
        self.assertEqual(sess[TENANT_DB_SESSION_KEY], "homologation")
        mock_fetch.assert_called_once_with(2003)


class FetchLojaAmbienteTests(unittest.TestCase):
    @patch("database.conectar_admin_optional")
    def test_reads_ambiente_from_first_db_with_loja(self, mock_connect):
        prod_conn = MagicMock()
        prod_cur = MagicMock()
        prod_conn.cursor.return_value = prod_cur
        prod_cur.fetchone.return_value = {"ambiente": "homologation"}

        def side_effect(target=None, session=None):
            return prod_conn if target == "production" else None

        mock_connect.side_effect = side_effect

        self.assertEqual(fetch_loja_ambiente_for_cliente(2003), "homologation")

    @patch("database.conectar_admin_optional", return_value=None)
    def test_defaults_production_when_loja_not_found(self, _mock_connect):
        self.assertEqual(fetch_loja_ambiente_for_cliente(9999), "production")


class NormalizeAmbienteTests(unittest.TestCase):
    def test_homolog_variants(self):
        self.assertEqual(normalize_ambiente("hml"), "homologation")
        self.assertEqual(normalize_ambiente("production"), "production")


class BannerForLojaTests(unittest.TestCase):
    def test_homologation_badge_short_without_store_name(self):
        text, kind = banner_for_loja({"ambiente": "homologation", "nome": "MARCIO GONCALVES DIAS"})
        self.assertEqual(text, "Homologação")
        self.assertEqual(kind, "hml")
        self.assertNotIn("MARCIO", text or "")

    def test_production_no_banner(self):
        self.assertEqual(banner_for_loja({"ambiente": "production", "nome": "Loja"}), (None, None))


class LocateLoginUserTests(unittest.TestCase):
    @patch("services.login_tenant_db.fetch_loja_ambiente_for_cliente", return_value="production")
    @patch("services.login_tenant_db.Config.admin_db_configured", return_value=True)
    @patch("services.login_tenant_db.conectar_admin_optional")
    def test_match_production_user(self, mock_connect, _mock_cfg, _mock_fetch):
        prod_conn = MagicMock()
        prod_cur = MagicMock()
        prod_conn.cursor.return_value = prod_cur
        prod_cur.fetchone.return_value = {
            "usuario": "loja",
            "senha": "x",
            "id_cliente": 1,
            "funcao": "gerente",
            "ativo": 1,
        }

        def connect_side_effect(target=None, session=None):
            if target == "production":
                return prod_conn
            empty = MagicMock()
            empty.cursor.return_value.fetchone.return_value = None
            return empty

        mock_connect.side_effect = connect_side_effect

        target, row = locate_login_user("loja")
        self.assertEqual(target, "production")
        self.assertEqual(row["id_cliente"], 1)

    @patch("services.login_tenant_db.fetch_loja_ambiente_for_cliente", return_value="production")
    @patch(
        "services.login_tenant_db.Config.admin_db_configured",
        side_effect=lambda t: t == "production",
    )
    @patch("services.login_tenant_db.conectar_admin_optional")
    def test_skip_hml_when_unavailable(self, mock_connect, _mock_cfg, _mock_fetch):
        prod_conn = MagicMock()
        prod_cur = MagicMock()
        prod_conn.cursor.return_value = prod_cur
        prod_cur.fetchone.return_value = {
            "usuario": "loja",
            "senha": "x",
            "id_cliente": 1,
            "funcao": "gerente",
            "ativo": 1,
        }

        def connect_side_effect(target=None, session=None):
            if target == "production":
                return prod_conn
            raise Exception("Senha ausente para HML")

        mock_connect.side_effect = connect_side_effect

        target, row = locate_login_user("loja")
        self.assertEqual(target, "production")
        self.assertEqual(row["id_cliente"], 1)

    @patch("services.login_tenant_db.fetch_loja_ambiente_for_cliente", return_value="homologation")
    @patch("services.login_tenant_db.Config.admin_db_configured", return_value=True)
    @patch("services.login_tenant_db.conectar_admin_optional")
    def test_login_prod_user_routes_to_hml_by_cadastro(self, mock_connect, _mock_cfg, _mock_fetch):
        prod_conn = MagicMock()
        prod_cur = MagicMock()
        prod_conn.cursor.return_value = prod_cur
        prod_cur.fetchone.return_value = {
            "usuario": "loja",
            "senha": "x",
            "id_cliente": 1,
            "funcao": "gerente",
            "ativo": 1,
        }
        hml_conn = MagicMock()
        hml_cur = MagicMock()
        hml_conn.cursor.return_value = hml_cur
        hml_cur.fetchone.return_value = None

        def connect_side_effect(target=None, session=None):
            return prod_conn if target == "production" else hml_conn

        mock_connect.side_effect = connect_side_effect

        target, row = locate_login_user("loja")
        self.assertEqual(target, "homologation")
        self.assertEqual(row["id_cliente"], 1)

    @patch("services.login_tenant_db.fetch_loja_ambiente_for_cliente", return_value="homologation")
    @patch(
        "services.login_tenant_db.Config.admin_db_configured",
        side_effect=lambda t: t == "production",
    )
    @patch("services.login_tenant_db.conectar_admin_optional")
    def test_homologation_without_hml_credentials_friendly_error(self, mock_connect, _mock_cfg, _mock_fetch):
        prod_conn = MagicMock()
        prod_cur = MagicMock()
        prod_conn.cursor.return_value = prod_cur
        prod_cur.fetchone.return_value = {
            "usuario": "loja",
            "senha": "x",
            "id_cliente": 1,
            "funcao": "gerente",
            "ativo": 1,
        }

        def connect_side_effect(target=None, session=None):
            return prod_conn if target == "production" else None

        mock_connect.side_effect = connect_side_effect

        with self.assertRaises(LoginAmbienteError) as ctx:
            locate_login_user("loja")
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("banco de testes", ctx.exception.message.lower())
        self.assertNotIn("url", ctx.exception.message.lower())


if __name__ == "__main__":
    unittest.main()
