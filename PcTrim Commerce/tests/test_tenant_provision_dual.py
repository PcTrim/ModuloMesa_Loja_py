"""Testes de provisionamento dual (prod + homologação)."""
import unittest
from unittest.mock import MagicMock, patch

from services.loja_ambiente import AMBIENTE_HOMOLOGATION, AMBIENTE_PRODUCTION
from services.tenant_provision import TenantProvisionError, provision_tenant


class TestProvisionTenantDual(unittest.TestCase):
    def _base_kwargs(self):
        return {
            "nome": "Loja Teste",
            "usuario": "loja_teste",
            "senha": "1234",
            "id_cliente": 9001,
            "ddd": "11",
            "telefone": "999999999",
            "cidade": "Teste",
            "tipo_negocio": "varejo",
            "ambiente": AMBIENTE_HOMOLOGATION,
        }

    @patch("services.tenant_provision._rollback_tenant_in_target")
    @patch("services.tenant_provision._provision_tenant_in_target")
    @patch("services.tenant_provision.hash_password", return_value="hash")
    @patch("services.tenant_provision._resolve_id_cliente_global", return_value=9001)
    @patch("services.tenant_provision._usuario_login_exists_any_target", return_value=False)
    @patch("services.tenant_provision.hml_admin_disponivel", return_value=True)
    @patch("services.tenant_provision.Config.admin_db_configured", return_value=True)
    def test_dual_create_success(
        self,
        _cfg,
        _hml,
        _login,
        _resolve,
        _hash,
        mock_provision,
        mock_rollback,
    ):
        result = provision_tenant(**self._base_kwargs(), criar_ambos_bancos=True)

        self.assertTrue(result["sucesso"])
        self.assertEqual(result["id_cliente"], 9001)
        self.assertEqual(
            result["bancos_criados"],
            [AMBIENTE_PRODUCTION, AMBIENTE_HOMOLOGATION],
        )
        self.assertEqual(mock_provision.call_count, 2)
        mock_rollback.assert_not_called()

    @patch("services.tenant_provision._rollback_tenant_in_target")
    @patch("services.tenant_provision._provision_tenant_in_target")
    @patch("services.tenant_provision.hash_password", return_value="hash")
    @patch("services.tenant_provision._resolve_id_cliente_global", return_value=9001)
    @patch("services.tenant_provision._usuario_login_exists_any_target", return_value=False)
    @patch("services.tenant_provision.hml_admin_disponivel", return_value=True)
    @patch("services.tenant_provision.Config.admin_db_configured", return_value=True)
    def test_dual_create_rollback_on_hml_failure(
        self,
        _cfg,
        _hml,
        _login,
        _resolve,
        _hash,
        mock_provision,
        mock_rollback,
    ):
        mock_provision.side_effect = [None, TenantProvisionError("falha hml", status=500)]

        with self.assertRaises(TenantProvisionError):
            provision_tenant(**self._base_kwargs(), criar_ambos_bancos=True)

        mock_rollback.assert_called_once_with(AMBIENTE_PRODUCTION, 9001)

    @patch("services.tenant_provision._provision_tenant_in_target")
    @patch("services.tenant_provision.hash_password", return_value="hash")
    @patch("services.tenant_provision._resolve_id_cliente_global", return_value=9001)
    @patch("services.tenant_provision._usuario_login_exists_any_target", return_value=False)
    @patch("services.tenant_provision.hml_admin_disponivel", return_value=True)
    @patch("services.tenant_provision.Config.admin_db_configured", return_value=True)
    def test_single_db_regression(
        self,
        _cfg,
        _hml,
        _login,
        _resolve,
        _hash,
        mock_provision,
    ):
        kwargs = self._base_kwargs()
        kwargs["criar_ambos_bancos"] = False
        kwargs["ambiente"] = AMBIENTE_PRODUCTION
        result = provision_tenant(**kwargs)

        self.assertTrue(result["sucesso"])
        self.assertEqual(result["bancos_criados"], [AMBIENTE_PRODUCTION])
        mock_provision.assert_called_once()

    @patch("services.tenant_provision.hml_admin_disponivel", return_value=False)
    @patch("services.tenant_provision.Config.admin_db_configured", return_value=True)
    def test_dual_requires_hml(self, _cfg, _hml):
        with self.assertRaises(TenantProvisionError) as ctx:
            provision_tenant(**self._base_kwargs(), criar_ambos_bancos=True)
        self.assertIn("Homologação não configurada", ctx.exception.message)


class TestListTenantsDualBadge(unittest.TestCase):
    @patch("services.tenant_provision._list_from_target")
    def test_em_ambos_bancos_flag(self, mock_list):
        from services.tenant_provision import list_tenants

        row = {
            "id_cliente": 2027,
            "nome": "Loja",
            "cidade": "",
            "telefone": "",
            "ddd": "11",
            "tipo_negocio": "varejo",
            "ambiente": "homologation",
            "usuario_gerente": "2027",
            "ativo": 1,
        }

        def side_effect(target):
            return [row] if target in (AMBIENTE_PRODUCTION, AMBIENTE_HOMOLOGATION) else []

        mock_list.side_effect = side_effect

        lojas = list_tenants()
        self.assertEqual(len(lojas), 1)
        self.assertTrue(lojas[0]["em_ambos_bancos"])
        self.assertEqual(
            lojas[0]["bancos_cadastrados"],
            [AMBIENTE_PRODUCTION, AMBIENTE_HOMOLOGATION],
        )


if __name__ == "__main__":
    unittest.main()
