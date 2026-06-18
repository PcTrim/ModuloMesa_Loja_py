"""MySQL connection helper."""
import os
from contextlib import contextmanager

import mysql.connector


def conectar():
    host = os.getenv("MYSQL_HOST")
    user = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PASSWORD")
    port = int(os.getenv("MYSQL_PORT") or 3308)
    database = os.getenv("MYSQL_DATABASE")
    if not all([host, user, password, port, database]):
        raise Exception("Missing MySQL environment variables")
    print("DB DEBUG:", host, port, user, database)
    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        port=port,
        database=database,
        autocommit=False,
    )


@contextmanager
def transaction():
    conn = conectar()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
