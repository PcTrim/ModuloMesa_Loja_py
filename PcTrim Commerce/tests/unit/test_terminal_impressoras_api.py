"""API e serviço de impressão por terminal + contrato da página de configuração."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-terminal-impressoras")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import app  # noqa: E402
from services import terminal_impressao as ti  # noqa: E402

_TEMPLATES = Path(_ROOT) / "templates"


class _FakeCursor:
    def __init__(self, fetchall_seq=None, fetchone_seq=None):
        self._fetchall_seq = list(fetchall_seq or [])
        self._fetchone_seq = list(fetchone_seq or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self._fetchone_seq:
            return self._fetchone_seq.pop(0)
        return None

    def fetchall(self):
        if self._fetchall_seq:
            return self._fetchall_seq.pop(0)
        return []

    def close(self):
        return None


class _FakeConn:
    def __init__(self, fetchall_seq=None, fetchone_seq=None):
        self._fetchall_seq = fetchall_seq
        self._fetchone_seq = fetchone_seq

    def cursor(self, dictionary=False):
        return _FakeCursor(
            fetchall_seq=self._fetchall_seq,
            fetchone_seq=self._fetchone_seq,
        )

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


class TerminalImpressaoServiceTests(unittest.TestCase):
    def test_normalize_terminal_id(self):
        self.assertEqual(ti.normalize_terminal_id(" caixa-01 "), "CAIXA-01")
        self.assertEqual(ti.normalize_terminal_id(""), "")

    @patch("services.terminal_impressao.conectar")
    def test_save_exige_comanda(self, mock_conectar):
        cur = _FakeCursor(
            fetchone_seq=[("id_cliente",)],
            fetchall_seq=[
                [
                    (1, "Principal", "S", "S", 0),
                    (2, "Cozinha", "N", "N", 1),
                ],
            ],
        )
        conn = MagicMock()
        conn.cursor.return_value = cur
        mock_conectar.return_value = conn

        ok, err = ti.save_terminal_config(2001, "HOST-USER", [])
        self.assertFalse(ok)
        self.assertIn("Principal", err or "")
        self.assertIn("Faltando", err or "")

    @patch("services.terminal_impressao.conectar")
    def test_save_ok_só_comanda_setor_opcional(self, mock_conectar):
        cur = _FakeCursor(
            fetchone_seq=[("id_cliente",)],
            fetchall_seq=[
                [
                    (1, "Principal", "S", "S", 0),
                    (2, "Cozinha", "N", "N", 1),
                ],
                [(1,)],
            ],
        )
        conn = MagicMock()
        conn.cursor.return_value = cur
        mock_conectar.return_value = conn

        ok, err = ti.save_terminal_config(
            2001,
            "HOST-USER",
            [{"impressora_id": 1, "caminho_local": r"\\PC\Comanda"}],
        )
        self.assertTrue(ok, err)
        self.assertIsNone(err)
        conn.commit.assert_called_once()

    @patch("services.terminal_impressao.conectar")
    def test_save_ignora_orfa_sem_caminho(self, mock_conectar):
        cur = _FakeCursor(
            fetchone_seq=[("id_cliente",)],
            fetchall_seq=[
                [
                    (1, "Principal", "S", "N", 0),
                    (3, "Microsoft Print to PDF", "N", "N", 1),
                ],
                [(1,)],
            ],
        )
        conn = MagicMock()
        conn.cursor.return_value = cur
        mock_conectar.return_value = conn

        ok, err = ti.save_terminal_config(
            2001,
            "HOST-USER",
            [
                {"impressora_id": 1, "caminho_local": r"\\PC\Comanda"},
                {"impressora_id": 3, "caminho_local": ""},
            ],
        )
        self.assertTrue(ok, err)
        self.assertIsNone(err)
        conn.commit.assert_called_once()

    @patch("services.terminal_impressao.conectar")
    def test_save_ok_quando_obrigatorias_preenchidas(self, mock_conectar):
        cur = _FakeCursor(
            fetchone_seq=[("id_cliente",)],
            fetchall_seq=[
                [
                    (1, "Principal", "S", "N", 0),
                    (2, "Cozinha", "N", "N", 1),
                ],
                [(1,), (2,)],
            ],
        )
        conn = MagicMock()
        conn.cursor.return_value = cur
        mock_conectar.return_value = conn

        ok, err = ti.save_terminal_config(
            2001,
            "host-user",
            [
                {"impressora_id": 1, "caminho_local": r"\\PC\Comanda"},
                {"impressora_id": 2, "caminho_local": r"\\PC\Cozinha"},
            ],
        )
        self.assertTrue(ok, err)
        self.assertIsNone(err)
        conn.commit.assert_called_once()


class TerminalImpressorasApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["usuario_logado"] = "tester"
            sess["id_cliente"] = 2001

    @patch("app._ensure_impressoras_table")
    @patch("app._ensure_terminal_impressora_table")
    @patch("app.terminal_impressao_service.terminal_is_configured", return_value=True)
    @patch("app.terminal_impressao_service.load_terminal_config")
    @patch("app.conectar")
    def test_get_retorna_caminho_persistido(
        self,
        mock_conectar,
        mock_load,
        mock_configured,
        _ensure_term,
        _ensure_imp,
    ):
        mock_load.return_value = [
            {"impressora_id": 1, "caminho_local": r"\\CAIXA\Comanda"},
        ]
        cur = _FakeCursor(
            fetchone_seq=[("id_cliente",)],
            fetchall_seq=[
                [
                    {
                        "id": 1,
                        "nomedaimpressora": "Comanda",
                        "conta_mesa": "S",
                        "comanda_delivery": "S",
                    },
                    {
                        "id": 2,
                        "nomedaimpressora": "Cozinha",
                        "conta_mesa": "N",
                        "comanda_delivery": "N",
                    },
                ],
            ],
        )
        conn = MagicMock()
        conn.cursor.return_value = cur
        mock_conectar.return_value = conn

        resp = self.client.get(
            "/api/terminal-impressoras?terminal_id=HOST-USER",
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["sucesso"])
        self.assertEqual(data["terminal_id"], "HOST-USER")
        self.assertTrue(data["configurado"])
        by_id = {r["impressora_id"]: r["caminho_local"] for r in data["impressoras"]}
        self.assertEqual(by_id[1], r"\\CAIXA\Comanda")
        self.assertEqual(by_id[2], "")
        mock_load.assert_called_once_with(2001, "HOST-USER")

    @patch("app._ensure_impressoras_table")
    @patch("app._ensure_terminal_impressora_table")
    @patch("app.terminal_impressao_service.save_terminal_config", return_value=(False, "Faltando: Cozinha"))
    def test_post_propaga_erro_save(self, mock_save, _ensure_term, _ensure_imp):
        resp = self.client.post(
            "/api/terminal-impressoras",
            json={
                "terminal_id": "HOST-USER",
                "itens": [{"impressora_id": 1, "caminho_local": r"\\PC\Comanda"}],
            },
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["sucesso"])
        self.assertIn("Cozinha", data["erro"])
        mock_save.assert_called_once()

    @patch("app._ensure_impressoras_table")
    @patch("app._ensure_terminal_impressora_table")
    @patch("app.terminal_impressao_service.terminal_is_configured", return_value=True)
    @patch("app.terminal_impressao_service.save_terminal_config", return_value=(True, None))
    def test_post_sucesso(self, mock_save, mock_configured, _ensure_term, _ensure_imp):
        resp = self.client.post(
            "/api/terminal-impressoras",
            json={
                "terminal_id": "host-user",
                "itens": [
                    {"impressora_id": 1, "caminho_local": r"\\PC\Comanda"},
                    {"impressora_id": 2, "caminho_local": r"\\PC\Cozinha"},
                ],
            },
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["sucesso"])
        self.assertEqual(data["terminal_id"], "HOST-USER")
        mock_save.assert_called_once_with(
            2001,
            "HOST-USER",
            [
                {"impressora_id": 1, "caminho_local": r"\\PC\Comanda"},
                {"impressora_id": 2, "caminho_local": r"\\PC\Cozinha"},
            ],
        )


class ConfiguracoesDadosHtmlContractTests(unittest.TestCase):
    def test_pagina_desacopla_api_do_bridge(self):
        html = (_TEMPLATES / "configuracoes_dados.html").read_text(encoding="utf-8")
        self.assertIn("loja_terminal_id", html)
        self.assertIn("localStorage", html)
        self.assertIn("carregarTerminalImpressorasApi", html)
        self.assertIn("readStoredTerminalId", html)
        self.assertIn("lojaGetBridgeHealthOrPair", html)
        self.assertIn("lojaPreOpenPrintAgentSync", html)
        self.assertIn("imprimir-bridge.js", html)
        self.assertIn("terminalImpObrigatoria", html)

    def test_pdv_mostra_erro_detalhe_na_comanda(self):
        html = (_TEMPLATES / "index.html").read_text(encoding="utf-8")
        self.assertIn("errDetalhe", html)
        self.assertIn("uiFeedback.error(msgComanda+(errDetalhe", html)


if __name__ == "__main__":
    unittest.main()
