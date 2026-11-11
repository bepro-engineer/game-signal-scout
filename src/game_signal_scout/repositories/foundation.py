"""Anime の repositories/foundation（共通層の発言の読み取り）の Game 版。Game の共通の発言は player_post（取得元に依らない）。
流用した Anime の部品（foundation/signals・signal/content・area_input・work_events）が使う関数を、同じ形で返す。"""
from __future__ import annotations

from datetime import date

from game_signal_scout.days import day_range
from game_signal_scout.repositories.post import EXCLUDE

_ID = "work_id ~ '^[0-9]+$'"


def _span(first: date, last: date):
    return day_range(first)[0], day_range(last)[1]


def list_judged_utterances(conn, source: str, first: date, last: date) -> list[tuple]:
    """(utterance_id, work_id, actor_ref, posted_at, lang, text_head, anime_context, about_work, behavior_kind, voice_role, actor_role)。"""
    s, e = _span(first, last)
    return conn.execute(f"SELECT item_id, work_id::bigint, author, at, lang, left(text, 30), 'yes', 'yes', NULL, NULL, NULL FROM player_post "
                        f"WHERE source=%s AND at >= %s AND at < %s AND {_ID} AND NOT flags ?| %s", (source, s, e, EXCLUDE)).fetchall()


def list_covered_days(conn, source: str, first: date, last: date, coverages: list[str]) -> list[date]:
    """観測のそろった日（Game は観測の確定の状態 obs_day_state で決める）。"""
    want = ["complete"] if "partial" not in coverages else ["complete", "provisional"]
    return [d for (d,) in conn.execute("SELECT target_day FROM obs_day_state WHERE source=%s AND target_day BETWEEN %s AND %s AND state = ANY(%s) ORDER BY 1",
                                       (source, first, last, want))]


def list_confirmed_quotes_of_work(conn, work_id: int, first: date, last: date) -> list[tuple]:
    """作品の、期間の日ごとの引用 (target_day, source, 発言の ID, 分類, lang, 引用)（Anime と同じ並び）。
    分類は Anime の発言の分類の名前に当てる: 好意的なレビュー = recommend、否定的なレビュー = complaint、SNS の発言 = emotion。"""
    s, e = _span(first, last)
    from game_signal_scout.days import broadcast_day
    rows = conn.execute(f"SELECT source, item_id, at, lang, text, stance FROM player_post WHERE work_id=%s AND at >= %s AND at < %s AND NOT flags ?| %s "
                        f"AND length(text) BETWEEN 20 AND 300 ORDER BY at, item_id", (str(work_id), s, e, EXCLUDE)).fetchall()
    kind = {"positive": "recommend", "negative": "complaint"}
    return [(broadcast_day(at), src, uid, kind.get(st, "emotion"), lang, " ".join(text.split())) for src, uid, at, lang, text, st in rows]


def list_longest_posts_with_roles(conn, source: str, ids: list) -> list[tuple]:
    return []


def list_utterance_items(conn, source: str, uris: list) -> list[tuple]:
    return []


def list_normalize_details(conn, source: str, first: date, last: date) -> dict:
    return {}


def count_creators_by_work_day(conn, source: str, first: date, last: date, exclude) -> list[tuple]:
    return []


def count_anime_utterances_by_lang_day(conn, start, end) -> list[tuple]:
    return count_identified_utterances_by_lang_day(conn, start, end)


def count_identified_utterances_by_lang_day(conn, start, end) -> list[tuple]:
    """(lang, 放送日, 件数): 作品に結び付いた発言（Anime と同じ形。start・end は時刻）。"""
    return conn.execute(f"SELECT lang, ((at) AT TIME ZONE 'Asia/Tokyo' - interval '3 hours')::date, count(*) FROM player_post "
                        f"WHERE at >= %s AND at < %s AND {_ID} GROUP BY 1, 2", (start, end)).fetchall()



# ---- 今日の兆し（ops/dashboard_digest。Anime と同じ形）が読むもの。Game の共通の発言 player_post から
def list_utterances_with_actor_role(conn, source: str, roles: list[str], utterance_ids: list[str]) -> set[str]:
    return set()   # Game は投稿者の役割（まとめ・宣伝の発信者）の判定を持たない（宣伝などは印 flags で除く）


def list_longest_voice_per_actor(conn, source: str, day: date, work_ids: list[int]) -> list[tuple]:
    """その日のその作品の、投稿者ごとにいちばん長い本文 (actor_ref, 発言の分類, utterance_id, lang, 本文)。印のある発言は除く。"""
    s, e = day_range(day)
    return conn.execute("SELECT DISTINCT ON (author) author, 'unknown', item_id, lang, text FROM player_post WHERE source=%s AND at >= %s AND at < %s "
                        "AND work_id = ANY(%s) AND NOT flags ?| %s ORDER BY author, length(text) DESC, item_id",
                        (source, s, e, [str(w) for w in work_ids], EXCLUDE)).fetchall()


def count_voice_actors_by_work(conn, source: str, day: date, news_kinds: list[str], min_chars: int, url_pattern: str,
                               exclude_roles: list[str] | None) -> list[tuple[int, int]]:
    """その日の作品ごとの、本文が min_chars 字以上で URL を含まない声の投稿者の数 (work_id, 人数)。"""
    s, e = day_range(day)
    return conn.execute(f"SELECT work_id::bigint, count(DISTINCT author) FILTER (WHERE length(text) >= %s AND text !~* %s) FROM player_post "
                        f"WHERE source=%s AND at >= %s AND at < %s AND {_ID} AND NOT flags ?| %s GROUP BY 1",
                        (min_chars, url_pattern, source, s, e, EXCLUDE)).fetchall()


def list_news_texts(conn, source: str, day: date, work_ids: list[int], news_kinds: list[str], url_pattern: str) -> list[str]:
    """その日のその作品の、URL を含む発言の本文（出来事の文脈。根拠・人数には使わない）。"""
    s, e = day_range(day)
    return [t for (t,) in conn.execute("SELECT text FROM player_post WHERE source=%s AND at >= %s AND at < %s AND work_id = ANY(%s) AND text ~* %s ORDER BY item_id",
                                       (source, s, e, [str(w) for w in work_ids], url_pattern))]
