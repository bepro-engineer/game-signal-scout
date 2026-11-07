"""PostgreSQL への接続。表の定義と変更は Alembic（migrations/）。

接続のたびに、相手が Game の DB であることを 2 つの印で確かめる: database の名前（config.check_dbname）と、
移行が入れる表 scout_identity の値（'game'）。表がまだない DB（移行の前）は名前だけで確かめる。
"""
from __future__ import annotations

import psycopg

from game_signal_scout import SCOUT
from game_signal_scout.config import WrongDatabaseError, check_dbname, db_dsn


def verify_identity(conn) -> None:
    check_dbname(conn.execute("SELECT current_database()").fetchone()[0])
    if conn.execute("SELECT to_regclass('scout_identity')").fetchone()[0] is None:
        return
    rows = [r[0] for r in conn.execute("SELECT scout FROM scout_identity")]
    if rows != [SCOUT]:
        raise WrongDatabaseError(f"scout_identity が {rows}（{SCOUT!r} でない）")


def connect(dsn: str | None = None, autocommit: bool = False) -> psycopg.Connection:
    conn = psycopg.connect(dsn or db_dsn(), autocommit=autocommit)
    try:
        verify_identity(conn)
        if not autocommit:
            conn.commit()
    except Exception:
        conn.close()
        raise
    return conn
