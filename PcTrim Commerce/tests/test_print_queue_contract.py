"""Contrato v265-61: fila serial no Print Bridge e ordem comanda→preparo em salvarEImprimir."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "static" / "imprimir-bridge.js"
INDEX = ROOT / "templates" / "index.html"


class PrintQueueContractTests(unittest.TestCase):
    def test_bridge_tem_fila_serial(self):
        src = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("enqueuePrint", src, "imprimir-bridge.js deve expor enqueuePrint")
        self.assertIn("PRINT_GAP_MS", src, "imprimir-bridge.js deve definir PRINT_GAP_MS")
        self.assertRegex(
            src,
            r"window\.lojaImprimir\s*=\s*function\s*\([^)]*\)\s*\{[\s\S]*enqueuePrint",
            "lojaImprimir deve delegar para enqueuePrint",
        )

    def test_salvar_e_imprimir_comanda_antes_preparo(self):
        src = INDEX.read_text(encoding="utf-8")
        start = src.find("async function salvarEImprimir")
        self.assertGreater(start, -1, "salvarEImprimir não encontrada em index.html")
        end = src.find("function isTypingContext", start)
        self.assertGreater(end, start, "fim de salvarEImprimir não encontrado")
        body = src[start:end]
        idx_comanda = body.find("_imprimirComRetry")
        idx_preparo = body.find("distribuirPreparoCasa")
        self.assertGreater(idx_comanda, -1, "salvarEImprimir deve chamar _imprimirComRetry (comanda)")
        self.assertGreater(idx_preparo, -1, "salvarEImprimir deve chamar distribuirPreparoCasa (preparo)")
        self.assertLess(
            idx_comanda,
            idx_preparo,
            "comanda (_imprimirComRetry) deve vir antes de distribuirPreparoCasa",
        )

    def test_preparo_meta_atualizada_apos_marcar(self):
        src = INDEX.read_text(encoding="utf-8")
        self.assertIn(
            'state.preparoMetaById[k].imp_preparo="S"',
            src,
            "distribuirPreparoCasa deve sincronizar imp_preparo em preparoMetaById após marcar",
        )


if __name__ == "__main__":
    unittest.main()
