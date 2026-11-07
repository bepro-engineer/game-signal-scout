"""取得の記録（source_fetch）と、取得元ごとの状態（source_state: 最後の試行・成功・失敗）。"""
from __future__ import annotations

from datetime import datetime


def save_log(conn, rows: list[dict]) -> int:
    """Fetcher.log の行を保存する（呼ぶ側は保存の後に log を空にする）。"""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO source_fetch (ts, source, host, endpoint, status, ok, ms, bytes, error) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(r["ts"], r["source"], r["host"], r["endpoint"], r.get("status"), r["ok"], r.get("ms"), r.get("bytes"), r.get("error"))
                         for r in rows])
    return len(rows)


def get_state(conn, source: str) -> dict:
    r = conn.execute("SELECT last_attempt_at, last_ok_at, last_error_type, last_error_message FROM source_state WHERE source=%s", (source,)).fetchone()
    return dict(zip(("last_attempt_at", "last_ok_at", "last_error_type", "last_error_message"), r)) if r else {}


def mark_attempt(conn, source: str, at: datetime) -> None:
    conn.execute("INSERT INTO source_state (source, last_attempt_at) VALUES (%s,%s) "
                 "ON CONFLICT (source) DO UPDATE SET last_attempt_at=EXCLUDED.last_attempt_at", (source, at))


def mark_result(conn, source: str, at: datetime, error_type: str | None = None, error_message: str | None = None) -> None:
    """成功なら last_ok_at を進めて誤りを消す。失敗なら誤りだけを記録する（last_ok_at は前の成功のまま）。"""
    if error_type is None:
        conn.execute("UPDATE source_state SET last_ok_at=%s, last_error_type=NULL, last_error_message=NULL WHERE source=%s", (at, source))
    else:
        conn.execute("UPDATE source_state SET last_error_type=%s, last_error_message=%s WHERE source=%s", (error_type, (error_message or "")[:500], source))


def states(conn) -> dict:
    return {s: {"last_attempt_at": a, "last_ok_at": o, "last_error_type": t} for s, a, o, t in
            conn.execute("SELECT source, last_attempt_at, last_ok_at, last_error_type FROM source_state ORDER BY source")}


def recent_failures(conn, source: str, since: datetime) -> int:
    return conn.execute("SELECT count(*) FROM source_fetch WHERE source=%s AND ts >= %s AND NOT ok", (source, since)).fetchone()[0]
