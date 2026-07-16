"""Testes de acesso /admin/lojas (platform admin)."""
import os
import unittest

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-for-platform-admin")
os.environ.setdefault("PLATFORM_ADMIN_USERS", "marcio,suporte")

from app import app


@unittest.skip("Dependência de ambiente externo (MySQL/E2E)")
class PlatformAdminRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._ctx = app.app_context()
        self._ctx.push()

    def tearDown(self):
        self._ctx.pop()

    def test_admin_lojas_allows_marcio(self):
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "marcio"
            sess["id_cliente"] = 2001
            sess["funcao"] = "gerente"
        r = self.client.get("/admin/lojas")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Administra", r.data)

    def test_admin_lojas_denies_unknown_user_with_flash(self):
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "usuario_comum"
            sess["id_cliente"] = 2001
        r = self.client.get("/admin/lojas", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Acesso restrito", r.data)


if __name__ == "__main__":
    unittest.main()
