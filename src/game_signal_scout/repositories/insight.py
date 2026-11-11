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


def talk_counts(conn, appids: list[str], days: int = 7) -> dict[str, int]:
    """作品ごとの直近 days 日の発言の数（話題性。除外の印のある発言は数えない）。"""
    return {a: n for a, n in conn.execute("SELECT appid, count(*) FROM player_post WHERE appid = ANY(%s) AND at > now() - make_interval(days => %s) "
                                          "AND NOT flags ?| %s GROUP BY appid", (list(appids), days, EXCLUDE))}


def get_hash(conn, appid: str) -> str | None:
    r = conn.execute("SELECT input_hash FROM game_insight WHERE appid = %s", (appid,)).fetchone()
    return r[0] if r else None


def upsert(conn, x: dict) -> None:
    conn.execute("INSERT INTO game_insight (appid, generated_at, model, input_hash, body) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (appid) DO UPDATE SET "
                 "generated_at = EXCLUDED.generated_at, model = EXCLUDED.model, input_hash = EXCLUDED.input_hash, body = EXCLUDED.body",
                 (x["appid"], x["generated_at"], x["model"], x["input_hash"], json.dumps(x["body"], ensure_ascii=False, default=str)))


def set_en(conn, appid: str, en: dict) -> None:
    """読み取りの結果の英訳（body の en）だけを置き換える（読み直さない。#2）。"""
    conn.execute("UPDATE game_insight SET body = jsonb_set(body, '{en}', %s::jsonb) WHERE appid = %s", (json.dumps(en, ensure_ascii=False), appid))


def set_divided(conn, appid: str, divided: list, for_hash: str | None) -> None:
    """同じ論点で賛否が分かれた体験（body の divided）と、それを作った材料の版（divided_for）だけを置き換える（読み直さない。#2 2026-11-11）。"""
    conn.execute("UPDATE game_insight SET body = jsonb_set(jsonb_set(body, '{divided}', %s::jsonb), '{divided_for}', %s::jsonb) WHERE appid = %s",
                 (json.dumps(divided, ensure_ascii=False), json.dumps(for_hash), appid))


def all_insights(conn) -> dict[str, dict]:
    return {a: {"generated_at": g, "model": m, **b} for a, g, m, b in conn.execute("SELECT appid, generated_at, model, body FROM game_insight")}


def newest_generated_at(conn):
    """発見の表の版: 行の数・作品ごとの材料の hash と作った時刻の指紋。どの作品が足されても・作り直されても変わる
    （いちばん新しい時刻だけでは、読み始めの時刻で記録された作品が足されても変わらなかった。2026-11-09）。"""
    # 英訳だけを足したとき（body の en。#2）も変わるように、訳の数も入れる
    return conn.execute("SELECT count(*)::text || ':' || coalesce(md5(string_agg(appid || '|' || input_hash || '|' || generated_at::text || '|' || "
                        "coalesce((SELECT count(*) FROM jsonb_object_keys(coalesce(body->'en', '{}'::jsonb)))::text, '0'), ',' ORDER BY appid)), '') "
                        "FROM game_insight").fetchone()[0]


def statements_by_author(conn, appid: str, days: int, per_window: int, since, sources: list[str]) -> list[dict]:
    """発見の材料: 作品の直近 days 日の発言を、投稿者ごとに 1 件（いちばん長いもの）。直近の窓（at >= since）と前の窓から、それぞれ多くて per_window 件。
    どの取得元からも順番に取る（取得元ごとに長い順の順位を付け、順位の順に並べる。件数の多い取得元が材料を占めない。取得元はすべて同列）。
    sources: 集計に入れている取得元（有効で、利用条件で止まっていないもの）。宣伝などの印のあるもの・短いものは除く。"""
    rows = conn.execute(
        "WITH one AS (SELECT DISTINCT ON (author, cur) item_id, source, author, at, lang, text, cur FROM ("
        "  SELECT item_id, source, author, at, lang, text, at >= %s AS cur FROM player_post WHERE appid = %s AND source = ANY(%s) "
        "  AND at > now() - make_interval(days => %s) AND NOT flags ?| %s AND length(text) BETWEEN 60 AND 4000) t "
        "  ORDER BY author, cur, length(text) DESC), "
        "ranked AS (SELECT *, row_number() OVER (PARTITION BY cur, source ORDER BY length(text) DESC, item_id) AS rk FROM one) "
        "SELECT item_id, author, at, lang, text, cur FROM ranked ORDER BY cur DESC, rk, source", (since, appid, list(sources), days, EXCLUDE)).fetchall()
    out = [dict(zip(("item_id", "author", "at", "lang", "text"), x[:5])) for x in rows]
    cur = [x for x in out if x["at"] >= since][:per_window]
    prev = [x for x in out if x["at"] < since][:per_window]
    return cur + prev


def get_body(conn, appid: str) -> dict | None:
    r = conn.execute("SELECT body FROM game_insight WHERE appid = %s", (appid,)).fetchone()
    return r[0] if r else None
