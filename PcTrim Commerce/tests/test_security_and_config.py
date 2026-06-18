import os
import unittest

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

from config import Config
from services.passwords import hash_password, verify_password


class PasswordServiceTests(unittest.TestCase):
    def test_verify_password_with_plaintext_legacy(self):
        self.assertTrue(verify_password("123456", "123456"))
        self.assertFalse(verify_password("123456", "654321"))

    def test_verify_password_with_bcrypt_hash(self):
        hashed = hash_password("senha-forte")
        self.assertTrue(verify_password(hashed, "senha-forte"))
        self.assertFalse(verify_password(hashed, "senha-incorreta"))


class ConfigValidationTests(unittest.TestCase):
    def test_validate_required_allows_development_with_secret(self):
        old_env = Config.ENVIRONMENT
        old_secret = Config.SECRET_KEY
        try:
            Config.ENVIRONMENT = "development"
            Config.SECRET_KEY = "dev-secret"
            Config.validate_required()
        finally:
            Config.ENVIRONMENT = old_env
            Config.SECRET_KEY = old_secret

    def test_validate_required_requires_secret_in_production(self):
        old_env = Config.ENVIRONMENT
        old_secret = Config.SECRET_KEY
        try:
            Config.ENVIRONMENT = "production"
            Config.SECRET_KEY = None
            with self.assertRaises(RuntimeError):
                Config.validate_required()
        finally:
            Config.ENVIRONMENT = old_env
            Config.SECRET_KEY = old_secret


if __name__ == "__main__":
    unittest.main()
