import os
import unittest

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

from app import app


class AppSmokeTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_ping(self):
        resp = self.client.get("/ping")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.decode("utf-8"), "pong")

    def test_rota_teste(self):
        resp = self.client.get("/rota_teste")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Rota de teste OK", resp.data.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
