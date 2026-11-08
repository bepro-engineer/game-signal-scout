"""正規化したプレイヤーの発言（player_post）。"""
from __future__ import annotations

import json

COLS = ("source", "item_id", "at", "author", "lang", "appid", "title", "matched_by", "flags", "text", "stance", "playtime_minutes", "url", "id_version")


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
    """作品の辞書の材料: (appid, 題名)。作品の情報（game_profile）の題名と各言語の表示名だけ（観測の取得元の表は読まない。どの取得元がなくても同じ辞書）。"""
    return conn.execute("SELECT appid, title FROM game_profile WHERE title IS NOT NULL UNION SELECT appid, n.value FROM game_profile, jsonb_each_text(names) n "
                        "WHERE names IS NOT NULL").fetchall()


EXCLUDE = ["affiliate", "promo", "stream", "autopost", "adult", "link_only", "many_hashtags", "piracy", "news", "terms_excluded"]   # news: ニュース・告知はプレイヤーの声として数えない（Anime と同じ。2026-11-08 Issue #3）。terms_excluded: 利用条件で禁止が明記されたサイトの発言（#3 G2）


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


def people_by_appid(conn, appids: list[str], start, end) -> dict[str, int]:
    """期間に、その作品について書いた人（取得元ごとに数え、いちばん多い取得元の人数。取得元をまたいで足さない）。宣伝などの印のある発言は除く。"""
    rows = conn.execute("SELECT appid, max(n) FROM (SELECT appid, source, count(DISTINCT author) n FROM player_post WHERE appid = ANY(%s) AND at >= %s AND at < %s "
                        "AND NOT (flags ?| %s) GROUP BY appid, source) t GROUP BY appid", (list(appids), start, end, EXCLUDE)).fetchall()
    return {a: int(n) for a, n in rows}


def day_rows(conn, source: str, start, end, same_text_min: int):
    """観測の集計の材料: 取得元の 1 日の発言 (ID, 投稿者, 言語, 見出し, 時刻, app ID, 同じ文の印, 宣伝などの印があるか)。"""
    return conn.execute("SELECT item_id, author, lang, left(text, 30), at, appid, CASE WHEN length(text) >= %s THEN md5(text) END, flags ?| %s "
                        "FROM player_post WHERE source = %s AND at >= %s AND at < %s", (same_text_min, EXCLUDE, source, start, end)).fetchall()


def urls_of(conn, keys: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """(取得元, 発言の ID) → 公開の URL（https のものだけ）。"""
    if not keys:
        return {}
    rows = conn.execute("SELECT source, item_id, url FROM player_post WHERE (source, item_id) IN (SELECT * FROM unnest(%s::text[], %s::text[])) "
                        "AND url LIKE 'https://%%'", ([k[0] for k in keys], [k[1] for k in keys])).fetchall()
    return {(s, i): u for s, i, u in rows}


def forget_stale_identification(conn, source: str, version: str) -> int:
    """正規化の版が違う発言の行を消す（次の正規化で今の版で作り直す。印・言語・同定のどれが変わっても）。"""
    return conn.execute("DELETE FROM player_post WHERE source = %s AND id_version IS DISTINCT FROM %s", (source, version)).rowcount


def mark_terms_excluded(conn, source: str, hosts: list[str]) -> int:
    """利用条件で禁止が明記されたサイトの発言に印 terms_excluded を付け、それ以外からは外す（何度流しても同じ。消さない）。"""
    pats = [f"%//{h}%" for h in hosts]
    hit = "(item_id LIKE ANY(%s) OR coalesce(url, '') LIKE ANY(%s))"
    n = 0
    with conn.cursor() as cur:
        if pats:
            cur.execute(f"UPDATE player_post SET flags = flags || '[\"terms_excluded\"]'::jsonb WHERE source=%s AND {hit} AND NOT flags ? 'terms_excluded'",
                        (source, pats, pats))
            n = cur.rowcount
            cur.execute(f"UPDATE player_post SET flags = flags - 'terms_excluded' WHERE source=%s AND flags ? 'terms_excluded' AND NOT {hit}", (source, pats, pats))
        else:
            cur.execute("UPDATE player_post SET flags = flags - 'terms_excluded' WHERE source=%s AND flags ? 'terms_excluded'", (source,))
    return n
