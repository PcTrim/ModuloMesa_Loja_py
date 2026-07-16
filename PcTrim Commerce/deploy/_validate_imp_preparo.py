#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from database import conectar_admin  # noqa: E402
import app  # noqa: E402


def validate_db(target: str) -> None:
    conn = conectar_admin(target)
    cur = conn.cursor()
    try:
        cur.execute("SELECT DATABASE()")
        print("DB", cur.fetchone()[0])
        for tbl in ("pedido_diarios", "pedido_periodos"):
            cur.execute(f"SHOW TABLES LIKE '{tbl}'")
            if not cur.fetchone():
                print(f"  skip {tbl}")
                continue
            cur.execute(f"SHOW COLUMNS FROM `{tbl}` LIKE 'imp_preparo%%'")
            cols = [r[0] for r in cur.fetchall()]
            assert cols == ["imp_preparo", "imp_preparo_em"], cols
            cur.execute(
                f"SELECT COALESCE(imp_preparo, 'N') AS f, COUNT(*) "
                f"FROM `{tbl}` GROUP BY COALESCE(imp_preparo, 'N')"
            )
            print(f"  {tbl} cols={cols} flags={list(cur.fetchall())}")
        print(f"  {target} OK")
    finally:
        cur.close()
        conn.close()


def main() -> int:
    validate_db("production")
    validate_db("homologation")
    app._ensure_pedido_diarios_preparo_columns()
    print("ensure (via conectar/production) OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
