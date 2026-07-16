"""Testes do login OTP via WhatsApp."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-otp")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from auth_validation import collect_empty_login_fields, parse_login_json
from services.login_otp import (
    OTP_MSG_GENERIC,
    _hash_codigo,
    _check_rate_limit,
    mascara_whatsapp,
    validar_codigo_whatsapp,
)


class LoginValidationTests(unittest.TestCase):
    def test_parse_whatsapp_mode(self):
        p = parse_login_json({"usuario": "caixa1", "metodo": "whatsapp", "codigo": "123456"})
        self.assertEqual(p.metodo, "whatsapp")
        self.assertEqual(p.codigo, "123456")

    def test_collect_empty_whatsapp_requires_codigo(self):
        missing = collect_empty_login_fields("u", "", metodo="whatsapp", codigo="")
        self.assertIn("codigo", missing)
        self.assertNotIn("senha", missing)


class MascaraWhatsappTests(unittest.TestCase):
    def test_mascara_celular_11_digitos(self):
        self.assertEqual(mascara_whatsapp("11971447534"), "(11) 9••••-7534")

    def test_mascara_com_ddi(self):
        self.assertEqual(mascara_whatsapp("5511971447534"), "(11) 9••••-7534")


class OtpHashTests(unittest.TestCase):
    def test_hash_deterministic(self):
        a = _hash_codigo("user", "123456")
        b = _hash_codigo("user", "123456")
        self.assertEqual(a, b)
        self.assertNotEqual(a, _hash_codigo("user", "654321"))


class RateLimitTests(unittest.TestCase):
    def test_blocks_immediate_resend(self):
        store: dict = {}
        self.assertTrue(_check_rate_limit(store, "caixa1"))
        self.assertFalse(_check_rate_limit(store, "caixa1"))


class ValidarCodigoTests(unittest.TestCase):
    @patch("services.login_otp.locate_login_user", return_value=("production", {"usuario": "caixa1"}))
    @patch("services.login_otp.conectar_admin")
    def test_validar_codigo_ok(self, mock_conectar, _mock_locate):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conectar.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur

        codigo = "482931"
        usuario = "caixa1"
        codigo_hash = _hash_codigo(usuario, codigo)

        mock_cur.fetchone.return_value = {"id": 7}
        ok = validar_codigo_whatsapp(usuario, codigo)
        self.assertTrue(ok)
        mock_cur.execute.assert_any_call(
            unittest.mock.ANY,
            (usuario, codigo_hash),
        )


class SolicitarCodigoRouteTests(unittest.TestCase):
    def setUp(self):
        from app import app

        self.app = app
        self.client = app.test_client()

    def test_solicitar_codigo_sem_usuario_400(self):
        with self.client.session_transaction() as sess:
            sess["login_csrf"] = "tok"
        r = self.client.post(
            "/login/solicitar-codigo",
            json={"usuario": "", "csrf_token": "tok"},
        )
        self.assertEqual(r.status_code, 400)

    @patch("auth_routes.solicitar_codigo_whatsapp")
    def test_solicitar_codigo_retorna_mascara(self, mock_sol):
        mock_sol.return_value = {"enviado": True, "whatsapp_mascara": "(11) 9••••-7534"}
        with self.client.session_transaction() as sess:
            sess["login_csrf"] = "tok"
        r = self.client.post(
            "/login/solicitar-codigo",
            json={"usuario": "caixa1", "csrf_token": "tok"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data.get("sucesso"))
        self.assertEqual(data.get("whatsapp_mascara"), "(11) 9••••-7534")
        self.assertIn("instantes", data.get("mensagem", ""))


if __name__ == "__main__":
    unittest.main()
