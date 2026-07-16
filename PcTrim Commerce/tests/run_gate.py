#!/usr/bin/env python3
"""Gate de produção: APENAS tests/unit + tests/api + tests/integration.

Regras:
  - sem discover global de tests/
  - sem MySQL real, e2e ou rede obrigatória
  - executa as 3 camadas SEMPRE (continue-all), mesmo se uma falhar
  - exit != 0 se qualquer camada tiver failure/error

Uso:
    python -m tests.run_gate
    python tests/run_gate.py

Override (só deploy consciente): SKIP_TEST_GATE=1
Verbose unittest por teste: VERBOSE=1
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Fail mode: continue-all — roda UNIT, API e INTEGRATION mesmo após falha;
# o exit code final reflete qualquer failure/error em qualquer camada.
GATE_LAYERS = (
    ("UNIT", ROOT / "tests" / "unit"),
    ("API", ROOT / "tests" / "api"),
    ("INTEGRATION", ROOT / "tests" / "integration"),
)


def run_gate() -> int:
    if os.environ.get("SKIP_TEST_GATE", "").strip().lower() in ("1", "true", "yes"):
        print("SKIP_TEST_GATE=1 — gate ignorado")
        return 0

    # Isolamento: gate não exige .env / TEST_DB / rede.
    os.environ["PC_TRIM_TEST_GATE"] = "1"
    os.environ.setdefault("FLASK_SECRET_KEY", "test-suite-secret")

    verbose = os.environ.get("VERBOSE", "").strip() in ("1", "true", "yes")
    runner_verbosity = 1 if verbose else 0

    print("==> Gate de produção (isolado, continue-all)")
    t0_all = time.perf_counter()
    loader = unittest.TestLoader()

    total_run = 0
    total_fail = 0
    total_err = 0
    total_skip = 0
    any_fail = False
    failed_cases: list[tuple[str, str]] = []

    for label, path in GATE_LAYERS:
        if not path.is_dir():
            print(f"ERRO: pasta de gate ausente: {path}")
            return 2

        suite = loader.discover(str(path), pattern="test_*.py", top_level_dir=str(ROOT))
        stream = StringIO() if not verbose else sys.stderr
        runner = unittest.TextTestRunner(stream=stream, verbosity=runner_verbosity)
        t0 = time.perf_counter()
        result = runner.run(suite)
        elapsed = time.perf_counter() - t0

        n = result.testsRun
        fails = len(result.failures)
        errors = len(result.errors)
        skipped = len(result.skipped)
        ok = result.wasSuccessful()

        total_run += n
        total_fail += fails
        total_err += errors
        total_skip += skipped
        if not ok:
            any_fail = True
            for test, _tb in result.failures + result.errors:
                failed_cases.append((label, str(test)))

        status = "OK" if ok else "FAIL"
        line = f"[{label}] {n} testes -> {status} ({elapsed:.2f}s)"
        if not ok:
            line += f"  failures={fails} errors={errors}"
        if skipped:
            line += f"  skipped={skipped}"
        print(line)

    total_elapsed = time.perf_counter() - t0_all
    print("")
    total_status = "OK" if not any_fail else "FAIL"
    print(f"TOTAL: {total_run} testes -> {total_status} ({total_elapsed:.2f}s)")
    if total_skip:
        print(f"  skipped={total_skip}")
    if failed_cases:
        print("  falhas:")
        for label, name in failed_cases:
            print(f"    [{label}] {name}")
    return 0 if not any_fail else 1


def main() -> int:
    return run_gate()


if __name__ == "__main__":
    raise SystemExit(main())
