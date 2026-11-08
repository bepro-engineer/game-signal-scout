"""接続の排他（Anime の repositories/session から移植）。セッションの advisory lock なので、接続が切れれば自動で外れる。

名前には Scout の接頭辞を付ける（advisory lock は DB ごとなので、ほかの Scout とは衝突しない。機械全体で 1 つにしたい LLM の排他は、
DB のロックではなく共有の LLM 枠 llm_gate を使う）。
"""
from __future__ import annotations

PREFIX = "game_signal_scout:"


def try_advisory_lock(conn, name: str) -> bool:
    return bool(conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (PREFIX + name,)).fetchone()[0])


def advisory_unlock(conn, name: str) -> None:
    conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (PREFIX + name,))



def set_read_only(conn) -> None:
    conn.execute("SET TRANSACTION READ ONLY")
