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
    def test_is_platform_admin_marcio(self):
        old = os.environ.get("PLATFORM_ADMIN_USERS")
        try:
            os.environ["PLATFORM_ADMIN_USERS"] = "joaquim,marcio,suporte"
            self.assertTrue(Config.is_platform_admin("marcio"))
            self.assertTrue(Config.is_platform_admin("Marcio"))
            self.assertFalse(Config.is_platform_admin("outro"))
        finally:
            if old is None:
                os.environ.pop("PLATFORM_ADMIN_USERS", None)
            else:
                os.environ["PLATFORM_ADMIN_USERS"] = old

    def test_validate_required_allows_development_with_secret(self):
        old_env = Config.ENVIRONMENT
        old_secret = Config.SECRET_KEY
        old_user = Config.MYSQL_USER
        old_db = Config.MYSQL_DATABASE
        try:
            Config.ENVIRONMENT = "development"
            Config.SECRET_KEY = "dev-secret"
            Config.MYSQL_USER = "root"
            Config.MYSQL_DATABASE = "loja2001"
            Config.validate_required()
        finally:
            Config.ENVIRONMENT = old_env
            Config.SECRET_KEY = old_secret
            Config.MYSQL_USER = old_user
            Config.MYSQL_DATABASE = old_db

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

    def test_admin_db_target_default_from_database_name(self):
        old_db = Config.MYSQL_DATABASE
        try:
            Config.MYSQL_DATABASE = "pctrim_commerce_hml"
            self.assertEqual(Config.admin_db_target_default(), "homologation")
            Config.MYSQL_DATABASE = "pctrim_commerce"
            self.assertEqual(Config.admin_db_target_default(), "production")
        finally:
            Config.MYSQL_DATABASE = old_db

    def test_runtime_is_homologation_from_database(self):
        old_env = Config.ENVIRONMENT
        old_db = Config.MYSQL_DATABASE
        try:
            Config.ENVIRONMENT = "development"
            Config.MYSQL_DATABASE = "pctrim_commerce_hml"
            self.assertTrue(Config.runtime_is_homologation())
            Config.MYSQL_DATABASE = "pctrim_commerce"
            self.assertFalse(Config.runtime_is_homologation())
            Config.ENVIRONMENT = "homologation"
            Config.MYSQL_DATABASE = "pctrim_commerce"
            self.assertTrue(Config.runtime_is_homologation())
        finally:
            Config.ENVIRONMENT = old_env
            Config.MYSQL_DATABASE = old_db

    def test_environment_banner_only_on_homologation(self):
        old_env = Config.ENVIRONMENT
        old_db = Config.MYSQL_DATABASE
        try:
            Config.ENVIRONMENT = "development"
            Config.MYSQL_DATABASE = "pctrim_commerce"
            text, kind = Config.environment_banner()
            self.assertIsNone(text)
            Config.MYSQL_DATABASE = "pctrim_commerce_hml"
            text, kind = Config.environment_banner()
            self.assertIn("HOMOLOGA", text or "")
            self.assertEqual(kind, "hml")
        finally:
            Config.ENVIRONMENT = old_env
            Config.MYSQL_DATABASE = old_db

    def test_admin_db_profile_uses_explicit_env_vars(self):
        keys = (
            "MYSQL_DATABASE_PROD",
            "MYSQL_USER_PROD",
            "MYSQL_PASSWORD_PROD",
            "MYSQL_DATABASE_HML",
            "MYSQL_USER_HML",
            "MYSQL_PASSWORD_HML",
        )
        old = {k: os.environ.get(k) for k in keys}
        try:
            os.environ["MYSQL_DATABASE_PROD"] = "db_prod"
            os.environ["MYSQL_USER_PROD"] = "user_prod"
            os.environ["MYSQL_PASSWORD_PROD"] = "pass_prod"
            os.environ["MYSQL_DATABASE_HML"] = "db_hml"
            os.environ["MYSQL_USER_HML"] = "user_hml"
            os.environ["MYSQL_PASSWORD_HML"] = "pass_hml"
            prod = Config.admin_db_profile("production")
            hml = Config.admin_db_profile("homologation")
            self.assertEqual(prod["database"], "db_prod")
            self.assertEqual(prod["user"], "user_prod")
            self.assertEqual(hml["database"], "db_hml")
            self.assertEqual(hml["user"], "user_hml")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_admin_db_configured_requires_password(self):
        keys = ("MYSQL_PASSWORD", "MYSQL_PASSWORD_HML", "MYSQL_USER_HML")
        old = {k: os.environ.get(k) for k in keys}
        old_db = Config.MYSQL_DATABASE
        try:
            Config.MYSQL_DATABASE = "pctrim_commerce"
            os.environ.pop("MYSQL_PASSWORD_HML", None)
            self.assertTrue(Config.admin_db_configured("production"))
            self.assertFalse(Config.admin_db_configured("homologation"))
            os.environ["MYSQL_PASSWORD_HML"] = "secret"
            self.assertTrue(Config.admin_db_configured("homologation"))
        finally:
            Config.MYSQL_DATABASE = old_db
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
