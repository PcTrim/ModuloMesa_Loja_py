"""Tile Custos & Margens no painel + guarda restaurant_only do menu engineering."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-menu-engineering-tile")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import app  # noqa: E402

_TEMPLATES = Path(_ROOT) / "templates"
_PAINEL = _TEMPLATES / "painel_menu.html"


class MenuEngineeringTileTemplateTests(unittest.TestCase):
    def test_painel_contem_tile_custos_margens(self):
        html = _PAINEL.read_text(encoding="utf-8")
        self.assertIn("Custos &amp; Margens", html)
        self.assertIn('href="{{ url_prefix }}/menu-engineering"', html)
        self.assertIn("tile-badge--new", html)
        self.assertIn("Novidade", html)
        self.assertIn("tile-badge--beta", html)
        self.assertIn("Beta", html)
        self.assertIn("{% if not IS_RETAIL %}", html)
        self.assertIn('data-lucide="chef-hat"', html)


class MenuEngineeringRestaurantGuardTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("decorators.is_retail", return_value=True)
    def test_menu_engineering_bloqueia_varejo(self, _mock_retail):
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "test"
            sess["id_cliente"] = 2001
        resp = self.client.get("/menu-engineering")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/casa", resp.location or "")

    @patch("decorators.is_retail", return_value=True)
    def test_menu_engineering_api_bloqueia_varejo(self, _mock_retail):
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "test"
            sess["id_cliente"] = 2001
        resp = self.client.get("/menu-engineering/ingredients")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/casa", resp.location or "")

    @patch("blueprints.menu_engineering._ensure_me_schema")
    @patch("decorators.is_retail", return_value=False)
    @patch("blueprints.menu_engineering.conectar")
    def test_menu_engineering_permitido_restaurante(self, mock_conectar, _mock_retail, _mock_schema):
        from tests.unit.test_terminal_impressoras_api import _FakeConn, _FakeCursor

        mock_conectar.return_value = _FakeConn(fetchall_seq=[[]])
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "test"
            sess["id_cliente"] = 2001
        with patch("blueprints.menu_engineering.obter_dados_loja", return_value={"nome": "Loja Teste"}):
            page = self.client.get("/menu-engineering")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"menu-engineering.bundle.js", page.data)
        api = self.client.get("/menu-engineering/ingredients")
        self.assertEqual(api.status_code, 200)


class MenuEngineeringSchemaTests(unittest.TestCase):
    def setUp(self):
        import blueprints.menu_engineering as me

        me._me_schema_ready_targets.clear()

    @patch("blueprints.menu_engineering.conectar")
    @patch("blueprints.menu_engineering._tenant_schema_key")
    def test_ensure_schema_por_tenant(self, mock_key, mock_conectar):
        import blueprints.menu_engineering as me

        mock_conn = unittest.mock.MagicMock()
        mock_cursor = unittest.mock.MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conectar.return_value = mock_conn

        mock_key.side_effect = ["production", "homologation", "homologation"]
        me._ensure_me_schema()
        me._ensure_me_schema()
        me._ensure_me_schema()

        self.assertEqual(mock_conectar.call_count, 2)
        self.assertEqual(me._me_schema_ready_targets, {"production", "homologation"})


if __name__ == "__main__":
    unittest.main()
