"""正規化したプレイヤーの発言（player_post）。"""
from __future__ import annotations

import json

COLS = ("source", "item_id", "at", "author", "lang", "appid", "title", "matched_by", "flags", "text", "stance", "playtime_minutes")


def unnormalized(conn, source: str, limit: int):
    return conn.execute("SELECT s.item_id, s.occurred_at, s.payload FROM source_item s LEFT JOIN player_post p ON p.source=s.source AND p.item_id=s.item_id "
                        "WHERE s.source=%s AND p.item_id IS NULL ORDER BY s.item_id LIMIT %s", (source, limit)).fetchall()


def insert(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(f"INSERT INTO player_post ({', '.join(COLS)}) VALUES ({', '.join(['%s'] * len(COLS))}) ON CONFLICT DO NOTHING",
                        [tuple(json.dumps(r[c]) if c == "flags" else r.get(c) for c in COLS) for r in rows])
        return cur.rowcount


def known_titles(conn) -> list[tuple[str, str]]:
    """作品の辞書の材料: (appid, 題名)。ProtonDB の報告にある作品の、最新の題名。"""
    return conn.execute("SELECT DISTINCT ON (appid) appid, title FROM player_report WHERE appid ~ '^[0-9]+$' AND title IS NOT NULL "
                        "ORDER BY appid, at DESC").fetchall()


EXCLUDE = ["affiliate", "promo", "stream", "autopost", "adult", "link_only", "many_hashtags", "piracy"]


def top_apps(conn, since, limit: int) -> list[dict]:
    """期間内に発言の多い作品（独立した投稿者の数の順。宣伝などの印の付いた発言は数えない）。"""
    rows = conn.execute("SELECT appid, max(title), count(DISTINCT author), count(*) FROM player_post "
                        "WHERE appid IS NOT NULL AND at >= %s AND NOT flags ?| %s GROUP BY appid ORDER BY 3 DESC, 4 DESC, appid LIMIT %s",
                        (since, EXCLUDE, limit)).fetchall()
    return [{"appid": a, "title": t, "authors": n, "posts": p} for a, t, n, p in rows]


def for_app(conn, appid: str, since, limit: int) -> list[dict]:
    rows = conn.execute("SELECT at, lang, matched_by, text FROM player_post WHERE appid=%s AND at >= %s AND NOT flags ?| %s "
                        "ORDER BY at DESC LIMIT %s", (appid, since, EXCLUDE, limit)).fetchall()
    return [{"at": a, "lang": lg, "matched_by": m, "text": t} for a, lg, m, t in rows]


def count_for_app(conn, appid: str, since) -> tuple[int, int]:
    return conn.execute("SELECT count(DISTINCT author), count(*) FROM player_post WHERE appid=%s AND at >= %s AND NOT flags ?| %s",
                        (appid, since, EXCLUDE)).fetchone()


def newest_at(conn):
    return conn.execute("SELECT max(at) FROM player_post").fetchone()[0]
