#!/usr/bin/env python3
"""Idempotent: add imp_preparo / imp_preparo_em to pedido_diarios (+ pedido_periodos)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from database import conectar_admin  # noqa: E402

DDL = [
    ("imp_preparo", "ADD COLUMN imp_preparo CHAR(1) NOT NULL DEFAULT 'N'"),
    ("imp_preparo_em", "ADD COLUMN imp_preparo_em DATETIME NULL"),
]


def migrate(target: str) -> bool:
    conn = conectar_admin(target)
    cur = conn.cursor()
    try:
        cur.execute("SELECT DATABASE()")
        db = cur.fetchone()[0]
        print(f"=== {target} -> {db} ===")
        tables = ["pedido_diarios"]
        cur.execute("SHOW TABLES LIKE 'pedido_periodos'")
        if cur.fetchone():
            tables.append("pedido_periodos")
        else:
            print("  (pedido_periodos ausente — pulando espelho)")
        for tbl in tables:
            for col, ddl in DDL:
                cur.execute(f"SHOW COLUMNS FROM `{tbl}` LIKE %s", (col,))
                if cur.fetchone() is None:
                    cur.execute(f"ALTER TABLE `{tbl}` {ddl}")
                    print(f"  ADD {tbl}.{col}")
                else:
                    print(f"  OK  {tbl}.{col} (ja existia)")
        conn.commit()
        for tbl in tables:
            cur.execute(f"SHOW COLUMNS FROM `{tbl}` LIKE 'imp_preparo%%'")
            cols = [r[0] for r in cur.fetchall()]
            print(f"  SHOW {tbl}: {cols}")
        return True
    except Exception as e:
        conn.rollback()
        print(f"  ERRO: {e}")
        return False
    finally:
        cur.close()
        conn.close()


def main() -> int:
    ok1 = migrate("production")
    ok2 = migrate("homologation")
    print("RESULT", "OK" if (ok1 and ok2) else "FAIL")
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
