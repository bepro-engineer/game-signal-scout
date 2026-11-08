"""プレイヤーの声の読み取り（game_insight）と、その材料の発言（player_post。取得元に依らない）。"""
from __future__ import annotations

import json

from game_signal_scout.repositories.post import EXCLUDE


def statements(conn, appid: str, days: int) -> list[dict]:
    """作品の最近の発言（宣伝などの印のあるもの・短すぎるものは除く）。"""
    rows = conn.execute("SELECT source, item_id, at, lang, text, stance, playtime_minutes FROM player_post WHERE appid = %s "
                        "AND at > now() - make_interval(days => %s) AND NOT flags ?| %s AND length(text) >= 40 ORDER BY at DESC",
                        (appid, days, EXCLUDE)).fetchall()
    return [dict(zip(("source", "item_id", "at", "lang", "text", "stance", "playtime_minutes"), r)) for r in rows]


def candidates(conn, days: int, min_statements: int, limit: int) -> list[str]:
    """読み取りの対象: 最近の発言が min_statements 件以上ある作品（多い順）。"""
    return [r[0] for r in conn.execute("SELECT appid FROM player_post WHERE appid IS NOT NULL AND at > now() - make_interval(days => %s) "
                                       "AND NOT flags ?| %s AND length(text) >= 40 GROUP BY appid HAVING count(*) >= %s ORDER BY count(*) DESC LIMIT %s",
                                       (days, EXCLUDE, min_statements, limit))]


def get_hash(conn, appid: str) -> str | None:
    r = conn.execute("SELECT input_hash FROM game_insight WHERE appid = %s", (appid,)).fetchone()
    return r[0] if r else None


def upsert(conn, x: dict) -> None:
    conn.execute("INSERT INTO game_insight (appid, generated_at, model, input_hash, body) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (appid) DO UPDATE SET "
                 "generated_at = EXCLUDED.generated_at, model = EXCLUDED.model, input_hash = EXCLUDED.input_hash, body = EXCLUDED.body",
                 (x["appid"], x["generated_at"], x["model"], x["input_hash"], json.dumps(x["body"], ensure_ascii=False, default=str)))


def all_insights(conn) -> dict[str, dict]:
    return {a: {"generated_at": g, "model": m, **b} for a, g, m, b in conn.execute("SELECT appid, generated_at, model, body FROM game_insight")}


def newest_generated_at(conn):
    return conn.execute("SELECT max(generated_at) FROM game_insight").fetchone()[0]


def statements_by_author(conn, appid: str, days: int, per_window: int, since) -> list[dict]:
    """発見の材料: 作品の直近 days 日の発言を、投稿者ごとに 1 件（いちばん長いもの）。直近の窓（at >= since）と前の窓から、それぞれ多くて per_window 件。
    宣伝などの印のあるもの・短いものは除く。"""
    rows = conn.execute("SELECT DISTINCT ON (author, at >= %s) item_id, author, at, lang, text FROM player_post WHERE appid = %s "
                        "AND at > now() - make_interval(days => %s) AND NOT flags ?| %s AND length(text) BETWEEN 60 AND 4000 "
                        "ORDER BY author, at >= %s, length(text) DESC", (since, appid, days, EXCLUDE, since)).fetchall()
    out = [dict(zip(("item_id", "author", "at", "lang", "text"), x)) for x in rows]
    cur = sorted([x for x in out if x["at"] >= since], key=lambda x: x["item_id"])[:per_window]
    prev = sorted([x for x in out if x["at"] < since], key=lambda x: x["item_id"])[:per_window]
    return cur + prev


def get_body(conn, appid: str) -> dict | None:
    r = conn.execute("SELECT body FROM game_insight WHERE appid = %s", (appid,)).fetchone()
    return r[0] if r else None
