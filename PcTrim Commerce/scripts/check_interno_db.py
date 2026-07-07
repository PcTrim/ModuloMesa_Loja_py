#!/usr/bin/env python3
"""Testa conexão read-only com a base Interno (clientes para nova loja)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Config  # noqa: E402
from database import conectar_interno  # noqa: E402


def main() -> int:
    profile = Config.interno_db_profile()
    print(
        "Interno: {user}@{host}:{port}/{database}".format(
            user=profile.get("user"),
            host=profile.get("host"),
            port=profile.get("port"),
            database=profile.get("database"),
        )
    )
    if not Config.interno_db_configured():
        print("ERRO: credenciais Interno incompletas no .env")
        return 1
    conn = None
    cur = None
    try:
        conn = conectar_interno()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM clientes WHERE COALESCE(ValorMensal, 0) >= 1"
        )
        row = cur.fetchone()
        total = int(row[0]) if row else 0
        print(f"OK: {total} cliente(s) elegível(is) na base Interno")
        return 0
    except Exception as e:
        print(f"ERRO: {e}")
        return 1
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
