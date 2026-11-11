"""正規化したプレイヤーの報告（player_report）と、検出した変化（shift_event）。"""
from __future__ import annotations

import json


def normalize_new(conn, source: str, rows) -> int:
    """正規化した行を入れる（同じ項目は入れない）。rows は (item_id, appid, title, at, failed, config_hash, proton, notes)。入れた数。"""
    rows = [(source, *r) for r in rows]
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO player_report (source, item_id, appid, title, at, failed, config_hash, proton, notes) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source, item_id) DO NOTHING", rows)
        return cur.rowcount


def unnormalized(conn, source: str, limit: int):
    """まだ正規化していない項目（source_item にあって player_report にないもの）。"""
    return conn.execute("SELECT s.item_id, s.payload FROM source_item s LEFT JOIN player_report p ON p.source=s.source AND p.item_id=s.item_id "
                        "WHERE s.source=%s AND p.item_id IS NULL ORDER BY s.item_id LIMIT %s", (source, limit)).fetchall()


def reports_for_analysis(conn, since, until):
    """分析の対象の報告（appid, 時刻の秒, 失敗か, 機材構成の hash, item_id）。"""
    return conn.execute("SELECT appid, extract(epoch FROM at)::bigint, failed, config_hash, item_id FROM player_report "
                        "WHERE at >= %s AND at < %s AND appid IS NOT NULL", (since, until)).fetchall()


def replace_events(conn, version: str, events: list[dict]) -> None:
    """その規則の版の検出結果を置き換える（同じ入力・同じ版なら何度流しても同じ）。"""
    conn.execute("DELETE FROM shift_event WHERE version=%s", (version,))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO shift_event (version, side, appid, window_start, n_key, n_window, share_prev, share_window, n_prev, item_ids) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(version, e["side"], e["appid"], e["window_start"], e["n_key"], e["n_window"], e["share_prev"], e["share_window"], e["n_prev"],
                          json.dumps(e["item_ids"])) for e in events])


def events(conn, version: str, side: str):
    return conn.execute("SELECT appid, window_start, n_key, n_window, share_prev, share_window FROM shift_event WHERE version=%s AND side=%s "
                        "ORDER BY n_key DESC, appid, window_start", (version, side)).fetchall()


# --- Viewer が読む（読むだけ） ---

_TITLE = "(SELECT title FROM player_report p WHERE p.appid = {} AND p.title IS NOT NULL ORDER BY p.at DESC LIMIT 1)"
EVENT_COLS = ("side", "appid", "title", "window_start", "n_key", "n_window", "share_prev", "share_window", "n_prev")


def event_counts(conn, version: str) -> dict:
    return dict(conn.execute("SELECT side, count(*) FROM shift_event WHERE version=%s GROUP BY side", (version,)).fetchall())
