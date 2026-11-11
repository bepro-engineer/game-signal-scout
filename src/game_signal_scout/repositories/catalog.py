"""作品の情報（game_profile）と、作品の情報を揃える対象の作品（取得元に依らない: プレイヤーの報告・発言の多い作品）。"""
from __future__ import annotations

import json

COLS = ("work_id", "source", "item_id", "title", "summary", "image_url", "genres", "modes", "platforms", "ja_text", "ja_voice", "released", "store_url", "fetched_at", "about_ja", "about_en", "coming_soon", "names")
JSON_COLS = {"genres", "modes", "platforms", "names"}


def active_apps(conn, days: int, limit: int) -> list[tuple[str, int]]:
    """最近 days 日（報告は最新の報告の日から、発言は今から）に、プレイヤーの報告・発言（宣伝などの印のないもの）が多い作品と、最新の日に遊ばれている規模の上位の作品（app ID, 重み）。
    取得元の名前では選ばない（表の種類で選ぶ）。規模の上位は重み 1000 - 順位で、報告・発言の多い作品と並べる。"""
    from game_signal_scout.repositories.post import EXCLUDE
    return conn.execute(
        "SELECT work_id, sum(n)::int FROM ("
        " SELECT work_id, 1000 - min(rank) n FROM game_activity WHERE day = (SELECT max(day) FROM game_activity) AND rank IS NOT NULL GROUP BY work_id"

        " UNION ALL"
        " SELECT work_id, count(*) n FROM player_report WHERE work_id IS NOT NULL AND at > (SELECT max(at) FROM player_report) - make_interval(days => %s) GROUP BY work_id"
        " UNION ALL"
        " SELECT work_id, count(DISTINCT author) n FROM player_post WHERE work_id IS NOT NULL AND at > now() - make_interval(days => %s)"
        "   AND NOT (flags ?| %s) GROUP BY work_id) t GROUP BY work_id ORDER BY 2 DESC, work_id LIMIT %s",
        (days, days, EXCLUDE, limit)).fetchall()


def targets(conn, days: int, limit: int, refresh_days: int, source: str, keyspace: str) -> list[str]:
    """作品の情報を取りに行く作品: 対象の作品（と、これから発売の作品）のうち、その取得元の情報がない・refresh_days より古いもの。
    返すのは、その取得元の番号（名前空間 keyspace の鍵。鍵のない作品は、その取得元では取れないので飛ばす）。"""
    want = [a for a, _ in active_apps(conn, days, limit)]
    # これから発売の作品（最新の一覧）も作品の情報を揃える（発売日・画像。画面のまもなく発売）。レビューの対象にはしない
    want += [a for (a,) in conn.execute("SELECT work_id FROM game_upcoming WHERE day = (SELECT max(day) FROM game_upcoming) ORDER BY rank") if a not in want]
    if not want:
        return []
    fresh = {r[0] for r in conn.execute("SELECT work_id FROM game_profile WHERE work_id = ANY(%s) AND source = %s AND fetched_at > now() - make_interval(days => %s)",
                                        (want, source, refresh_days))}
    from game_signal_scout.repositories import work_key
    own = work_key.external(conn, keyspace, want)
    done = {r[0] for r in conn.execute("SELECT item_id FROM source_item WHERE source = %s AND item_id = ANY(%s) AND received_at > now() - make_interval(days => %s)",
                                       (source, list(own.values()), refresh_days))}
    return [own[a] for a in want if a in own and a not in fresh and own[a] not in done]


def unnormalized(conn, source: str, limit: int):
    return conn.execute("SELECT s.item_id, s.received_at, s.payload FROM source_item s LEFT JOIN game_profile g ON g.source = s.source AND g.item_id = s.item_id "
                        "WHERE s.source = %s AND (g.item_id IS NULL OR s.received_at > g.fetched_at) ORDER BY s.item_id LIMIT %s", (source, limit)).fetchall()


def upsert(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    sql = (f"INSERT INTO game_profile ({', '.join(COLS)}) VALUES ({', '.join(['%s'] * len(COLS))}) ON CONFLICT (work_id) DO UPDATE SET "
           + ", ".join(f"{c} = EXCLUDED.{c}" for c in COLS if c != "work_id"))
    with conn.cursor() as cur:
        cur.executemany(sql, [tuple((json.dumps(r[c]) if r.get(c) is not None else None) if c in JSON_COLS else r.get(c) for c in COLS) for r in rows])
    return len(rows)


def profiles(conn, work_ids: list[str]) -> dict[str, dict]:
    rows = conn.execute(f"SELECT {', '.join(COLS)} FROM game_profile WHERE work_id = ANY(%s)", (list(work_ids),)).fetchall()
    return {r[0]: dict(zip(COLS, r)) for r in rows}


def activity_rows(conn, source: str, limit: int):
    return conn.execute("SELECT s.item_id, s.payload FROM source_item s LEFT JOIN game_activity a ON a.source = s.source AND a.item_id = s.item_id "
                        "WHERE s.source = %s AND a.item_id IS NULL ORDER BY s.item_id LIMIT %s", (source, limit)).fetchall()


def upcoming_rows(conn, source: str, limit: int):
    return conn.execute("SELECT s.item_id, s.payload FROM source_item s LEFT JOIN game_upcoming u ON u.source = s.source AND u.item_id = s.item_id "
                        "WHERE s.source = %s AND u.item_id IS NULL ORDER BY s.item_id LIMIT %s", (source, limit)).fetchall()


def insert_upcoming(conn, rows: list[tuple]) -> int:
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO game_upcoming (work_id, day, source, item_id, rank) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (work_id, day, source) DO NOTHING", rows)
        return cur.rowcount


def upcoming(conn) -> list[dict]:
    """これから発売の作品（最新の日の一覧の順）: app ID・順位・作品の情報（題名・画像・発売日の文・発売前か・ストアの URL）。"""
    rows = conn.execute("SELECT u.work_id, u.rank, g.title, coalesce(a.capsule_url, g.image_url), g.released, g.coming_soon, g.store_url, g.genres, g.platforms FROM game_upcoming u "
                        "LEFT JOIN game_profile g ON g.work_id = u.work_id LEFT JOIN game_assets a ON a.work_id = u.work_id "
                        "WHERE u.day = (SELECT max(day) FROM game_upcoming) ORDER BY u.rank").fetchall()
    keys = ("work_id", "rank", "title", "image", "released", "coming_soon", "store_url", "genres", "platforms")
    return [dict(zip(keys, r)) for r in rows]


def insert_activity(conn, rows: list[tuple]) -> int:
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO game_activity (work_id, day, source, item_id, rank, prev_rank, peak_players) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (work_id, day, source) DO NOTHING", rows)
        return cur.rowcount


def latest_activity(conn, work_ids: list[str]) -> dict[str, dict]:
    """最新の日の順位・前の週の順位・同時に遊んだ人数の最大。"""
    rows = conn.execute("SELECT work_id, day, rank, prev_rank, peak_players FROM game_activity WHERE work_id = ANY(%s) AND day = (SELECT max(day) FROM game_activity)",
                        (list(work_ids),)).fetchall()
    return {r[0]: dict(zip(("work_id", "day", "rank", "prev_rank", "peak_players"), r)) for r in rows}


def recent_reports(conn, work_ids: list[str], days: int) -> dict[str, dict]:
    """作品ごとの、最近 days 日の動作の報告の数と「遊べない」の数（最新の報告の日から遡る）。"""
    rows = conn.execute("SELECT work_id, count(*), count(*) FILTER (WHERE failed) FROM player_report WHERE work_id = ANY(%s) "
                        "AND at > (SELECT max(at) FROM player_report) - make_interval(days => %s) GROUP BY work_id", (list(work_ids), days)).fetchall()
    return {a: {"n": n, "failed": f} for a, n, f in rows}


def voice_counts(conn, work_ids: list[str], days: int) -> dict[str, int]:
    """作品ごとの、最近 days 日のプレイヤーの発言の数（別々の投稿者。宣伝などの印のあるものは数えない）。"""
    from game_signal_scout.repositories.post import EXCLUDE
    rows = conn.execute("SELECT work_id, count(DISTINCT author) FROM player_post WHERE work_id = ANY(%s) AND at > now() - make_interval(days => %s) "
                        "AND NOT (flags ?| %s) GROUP BY work_id", (list(work_ids), days, EXCLUDE)).fetchall()
    return dict(rows)


# ---- 作品の情報を読む（Service・画面の文書が使う。SQL はここだけ）
def names_images(conn, work_ids: list[str]) -> dict[str, tuple[str, str | None, str | None]]:
    """app ID → (題名〔日本語のストアの表示〕, 英語の題名, 画像の URL〔ストアのヘッダー〕)。"""
    rows = conn.execute("SELECT work_id, title, names->>'en', image_url FROM game_profile WHERE work_id = ANY(%s)", (list(work_ids),)).fetchall()
    return {a: (t, en, img) for a, t, en, img in rows}


def covers(conn, work_ids: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """app ID → (縦長の表紙, 横長の帯)（game_assets。ない作品は含まない）。"""
    rows = conn.execute("SELECT work_id, capsule_url, hero_url FROM game_assets WHERE work_id = ANY(%s)", (list(work_ids),)).fetchall()
    return {a: (c, h) for a, c, h in rows}


def game_works(conn, work_ids: list[str], not_game: list[str]) -> set[str]:
    """作品として見せてよい app ID（作品の情報があり、ゲームでないソフトのジャンルを持たない）。"""
    return {a for (a,) in conn.execute("SELECT work_id FROM game_profile WHERE work_id = ANY(%s) AND NOT (genres ?| %s)", (list(work_ids), not_game))}


def profiled_works(conn) -> list[str]:
    """作品の情報のある作品の番号（このサイトの作品の番号）。"""
    return [a for (a,) in conn.execute("SELECT work_id FROM game_profile ORDER BY work_id")]


def profiled_own_ids(conn, keyspace: str) -> list[str]:
    """作品の情報のある作品の、その取得元の番号（名前空間 keyspace の鍵のある作品だけ）。"""
    return [a for (a,) in conn.execute("SELECT k.ext_id FROM game_profile g JOIN game_work_key k ON k.work_id = g.work_id AND k.keyspace = %s ORDER BY 1", (keyspace,))]


PROFILE_KEYS = ("title", "summary", "image", "genres", "modes", "platforms", "ja_text", "ja_voice", "released", "store_url", "about_ja", "about_en", "names")


def profile_of(conn, work_id: str) -> dict | None:
    r = conn.execute("SELECT title, summary, image_url, genres, modes, platforms, ja_text, ja_voice, released, store_url, about_ja, about_en, names "
                     "FROM game_profile WHERE work_id=%s", (work_id,)).fetchone()
    return dict(zip(PROFILE_KEYS, r)) if r else None


def upcoming_works(conn, limit: int) -> list[str]:
    """最新の近日発売の一覧の上位（順位の順）。"""
    return [a for (a,) in conn.execute("SELECT work_id FROM game_upcoming WHERE day = (SELECT max(day) FROM game_upcoming) ORDER BY rank LIMIT %s", (limit,))]


def asset_rows(conn, source: str, limit: int):
    return conn.execute("SELECT s.item_id, s.received_at, s.payload FROM source_item s LEFT JOIN game_assets a ON a.source = s.source AND a.item_id = s.item_id "
                        "WHERE s.source = %s AND a.item_id IS NULL ORDER BY s.item_id LIMIT %s", (source, limit)).fetchall()


def upsert_assets(conn, rows: list[tuple]) -> int:
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO game_assets (work_id, source, item_id, capsule_url, hero_url, fetched_at) VALUES (%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (work_id) DO UPDATE SET capsule_url = EXCLUDED.capsule_url, hero_url = EXCLUDED.hero_url, fetched_at = EXCLUDED.fetched_at, "
                        "source = EXCLUDED.source, item_id = EXCLUDED.item_id", rows)
        return cur.rowcount


def attribute_rows(conn, source: str, limit: int):
    """まだ属性にしていない項目と、属性にした後で取り直した項目（受け取った時刻が属性より新しい。取り直しても属性が古いままだった: #2 2026-11-09）。"""
    return conn.execute("SELECT s.item_id, s.received_at, s.payload FROM source_item s "
                        "WHERE s.source = %s AND NOT EXISTS (SELECT 1 FROM game_attribute a WHERE a.source = s.source AND a.item_id = s.item_id AND a.fetched_at >= s.received_at) "
                        "AND NOT (s.payload ? 'no_attributes') ORDER BY s.item_id LIMIT %s", (source, limit)).fetchall()


def upsert_attributes(conn, rows: list[tuple]) -> int:
    """(work_id, key, source, item_id, value, fetched_at) を置き換える。"""
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO game_attribute (work_id, key, source, item_id, value, fetched_at) VALUES (%s,%s,%s,%s,%s::jsonb,%s) "
                        "ON CONFLICT (work_id, key, source) DO UPDATE SET value = EXCLUDED.value, item_id = EXCLUDED.item_id, fetched_at = EXCLUDED.fetched_at",
                        [(a, k, s, i, json.dumps(v, ensure_ascii=False), t) for a, k, s, i, v, t in rows])
        return cur.rowcount


def attributes_of(conn, work_ids: list[str]) -> dict[str, dict[str, list[dict]]]:
    """作品ごと・項目ごとの属性（取得元・値・取得の時刻）。"""
    out: dict[str, dict[str, list[dict]]] = {}
    for a, k, s, v, t in conn.execute("SELECT work_id, key, source, value, fetched_at FROM game_attribute WHERE work_id = ANY(%s) ORDER BY work_id, key, fetched_at DESC",
                                      (list(work_ids),)):
        out.setdefault(a, {}).setdefault(k, []).append({"source": s, "value": v, "fetched_at": t.isoformat()})
    return out


def attribute_targets(conn, source: str, refresh_days: int, keyspace: str) -> list[str]:
    """属性を取りに行く作品: 作品の情報のある作品のうち、その取得元の属性がない・refresh_days より古いもの（その取得元の番号。名前空間 keyspace の鍵）。"""
    return [a for (a,) in conn.execute(
        "SELECT k.ext_id FROM game_profile g JOIN game_work_key k ON k.work_id = g.work_id AND k.keyspace = %s "
        "WHERE NOT EXISTS (SELECT 1 FROM source_item s WHERE s.source = %s AND s.item_id = k.ext_id "
        "AND s.received_at > now() - make_interval(days => %s)) ORDER BY g.work_id", (keyspace, source, refresh_days))]


def platforms_of(conn, work_ids: list[str]) -> dict[str, list[str]]:
    return {a: p or [] for a, p in conn.execute("SELECT work_id, platforms FROM game_profile WHERE work_id = ANY(%s)", (list(work_ids),))}


def newest_catalog_at(conn):
    """作品の情報・画像・属性のいちばん新しい取得の時刻と、作品の情報の中身の指紋（公開の作り直しの判定）。
    指紋は、同じ取得の応答から作品の情報を作り直したとき（読み方を直したときなど。取得の時刻は変わらない）にも作り直すため（#2 2026-11-11）。"""
    at, fp = conn.execute("SELECT greatest((SELECT max(fetched_at) FROM game_profile), (SELECT max(fetched_at) FROM game_assets), "
                          "(SELECT max(fetched_at) FROM game_attribute)), (SELECT md5(string_agg(g::text, '' ORDER BY g.work_id)) FROM game_profile g)").fetchone()
    return f"{at}|{fp}"
