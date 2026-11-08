"""確定した観測の集計（全 Source 共通。sources/observations.py が確定し、画面が読む）。

- obs_day_state: Source × 日の状態（complete / provisional / incomplete / not_covered）と、確定した版・時刻。
- obs_work_lang_day: Source × 日 × 作品 × 言語の人数（'*' は全言語の合計の行）。
- obs_post: 確定した日の数えた記録（変化の判定の系列の入力）。
"""
from __future__ import annotations

from datetime import date, datetime

from psycopg.types.json import Json

COMPLETE_STATES = ("complete", "provisional")   # 画面に人数を出してよい日の状態


# ---------------------------------------------------------------- 日の状態
def get_day_state(conn, source: str, day: date) -> tuple[str, str] | None:
    """(state, version)。まだ記録がなければ None。"""
    r = conn.execute("SELECT state, version FROM obs_day_state WHERE source=%s AND target_day=%s", (source, day)).fetchone()
    return (r[0], r[1]) if r else None


def upsert_day_state(conn, source: str, day: date, *, state: str, version: str, reason: str | None, detail: dict, attempted_at: datetime,
                     finalized: bool) -> None:
    """日の状態を書く。finalized（その日をそろえて確定した）のときだけ版と確定の時刻を置き換える（そろわない日は前の確定の版・時刻を残す）。"""
    conn.execute(
        "INSERT INTO obs_day_state (source,target_day,state,version,reason,detail,attempted_at,finalized_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (source,target_day) DO UPDATE SET state=EXCLUDED.state, reason=EXCLUDED.reason, detail=EXCLUDED.detail, attempted_at=EXCLUDED.attempted_at, "
        "version = CASE WHEN %s THEN EXCLUDED.version ELSE obs_day_state.version END, "
        "finalized_at = CASE WHEN %s THEN EXCLUDED.finalized_at ELSE obs_day_state.finalized_at END",
        (source, day, state, version, reason, Json(detail), attempted_at, attempted_at if finalized else None, finalized, finalized))


def latest_complete_day(conn, sources: list[str] | None = None) -> tuple[date | None, datetime | None]:
    """そろった（complete）日のうち最新の日と、最後に確定した時刻。sources を渡せばその Source だけ。"""
    if sources is None:
        r = conn.execute("SELECT max(target_day), max(finalized_at) FROM obs_day_state WHERE state='complete'").fetchone()
    else:
        r = conn.execute("SELECT max(target_day), max(finalized_at) FROM obs_day_state WHERE state='complete' AND source = ANY(%s)", (list(sources),)).fetchone()
    return r[0], r[1]


def list_day_states(conn, day: date) -> dict[str, dict]:
    """その日の Source → {state, reason, finalized_at}。"""
    return {src: {"state": s, "reason": r, "finalized_at": f} for src, s, r, f in
            conn.execute("SELECT source, state, reason, finalized_at FROM obs_day_state WHERE target_day=%s", (day,))}


def day_states(conn, first: date, last: date, source: str | None = None) -> dict:
    """期間の日の状態。source を渡せば 日 → state、渡さなければ Source → 日 → state。"""
    if source is not None:
        return dict(conn.execute("SELECT target_day, state FROM obs_day_state WHERE source=%s AND target_day >= %s AND target_day <= %s",
                                 (source, first, last)).fetchall())
    out: dict[str, dict] = {}
    for src, d, st in conn.execute("SELECT source, target_day, state FROM obs_day_state WHERE target_day >= %s AND target_day <= %s", (first, last)):
        out.setdefault(src, {})[d] = st
    return out


def list_unsettled_days(conn, first: date, last: date, except_reason: str) -> set[date]:
    """期間の中で、まだそろっていない理由（reason）が残っている日（except_reason の日は除く）。"""
    return {r[0] for r in conn.execute("SELECT DISTINCT target_day FROM obs_day_state WHERE reason IS NOT NULL AND reason <> %s "
                                       "AND target_day >= %s AND target_day <= %s", (except_reason, first, last))}


def list_days_with_reason(conn, source: str, reason: str, first: date, before: date) -> list[date]:
    """first 以上 before 未満で、その理由のまま残っている日（新しい順）。"""
    return [r[0] for r in conn.execute("SELECT target_day FROM obs_day_state WHERE source=%s AND reason=%s AND target_day < %s AND target_day >= %s "
                                       "ORDER BY target_day DESC", (source, reason, before, first))]


# ---------------------------------------------------------------- 人数の集計
def replace_day_counts(conn, source: str, day: date, counts: dict[tuple[int, str], dict], version: str, computed_at: datetime) -> None:
    """その日の作品 × 言語の人数を置き換える（counts: (作品, 言語) → {persons, posts}）。"""
    conn.execute("DELETE FROM obs_work_lang_day WHERE source=%s AND target_day=%s", (source, day))
    for (wid, lang), v in counts.items():
        conn.execute("INSERT INTO obs_work_lang_day (source,target_day,work_id,lang,persons,posts,version,computed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                     (source, day, wid, lang, v["persons"], v["posts"], version, computed_at))


def replace_day_posts(conn, source: str, day: date, posts: list[tuple]) -> None:
    """その日の確定した記録を置き換える（posts: (unit, work_id, lang, actor, head, anime, at)）。"""
    conn.execute("DELETE FROM obs_post WHERE source=%s AND target_day=%s", (source, day))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO obs_post (source,target_day,unit,work_id,lang,actor,head,anime,at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING", [(source, day, *p) for p in posts])


def list_work_lang_persons(conn, day: date) -> list[tuple[str, int, str, int]]:
    """その日の (Source, 作品, 言語, 人数)。人数が 0 の行は含めない。"""
    return conn.execute("SELECT source, work_id, lang, persons FROM obs_work_lang_day WHERE target_day=%s AND persons > 0", (day,)).fetchall()


def get_day_counts(conn, source: str, day: date) -> dict[tuple[int, str], int]:
    """その Source・日の (作品, 言語) → 人数。"""
    return {(w, l): n for w, l, n in conn.execute("SELECT work_id, lang, persons FROM obs_work_lang_day WHERE source=%s AND target_day=%s", (source, day))}


def list_shown_counts(conn, first: date, last: date, sources: list[str]) -> list[tuple[str, date, int, str, int]]:
    """期間の (Source, 日, 作品, 言語, 人数) のうち、人数を出してよい日（complete・provisional）の行だけ。"""
    return conn.execute(
        "SELECT o.source, o.target_day, o.work_id, o.lang, o.persons FROM obs_work_lang_day o JOIN obs_day_state s "
        "ON s.source=o.source AND s.target_day=o.target_day AND s.state = ANY(%s) "
        "WHERE o.target_day >= %s AND o.target_day <= %s AND o.source = ANY(%s) AND o.persons > 0", (list(COMPLETE_STATES), first, last, list(sources))).fetchall()


def count_language_days(conn, first: date, last: date, min_persons: int) -> list[tuple[str, date, int]]:
    """期間の (言語, 日, 人数が min_persons 以上の作品の行の数)。全言語の合計の行（'*'）は含めない。"""
    return conn.execute("SELECT lang, target_day, count(*) FROM obs_work_lang_day WHERE target_day >= %s AND target_day <= %s AND lang <> '*' "
                        "AND persons >= %s GROUP BY 1, 2", (first, last, min_persons)).fetchall()


def iter_complete_posts(conn, source: str, first: date, last: date):
    """そろった日の確定した記録 (日, 作品, 言語, 投稿者, 見出し, anime, 時刻)。"""
    return conn.execute(
        "SELECT p.target_day, p.work_id, p.lang, p.actor, p.head, p.anime, p.at FROM obs_post p JOIN obs_day_state s "
        "ON s.source = p.source AND s.target_day = p.target_day AND s.state = 'complete' "
        "WHERE p.source=%s AND p.target_day >= %s AND p.target_day <= %s", (source, first, last))


# ---------------------------------------------------------------- 作品をまとめたときの付け替え（ops/work.merge_works）
def move_work_counts(conn, keep: int, drop: int) -> int:
    """drop の確定した集計を keep へ移す。人数は keep と drop の投稿者の和（obs_post で両方にいる人を 1 人に数える）。何度流しても同じ。移した (Source, 日) の数。"""
    days = conn.execute("SELECT DISTINCT source, target_day FROM obs_work_lang_day WHERE work_id=%s", (drop,)).fetchall()
    for src, day in days:
        for lang, _persons, _posts in conn.execute("SELECT lang, persons, posts FROM obs_work_lang_day WHERE source=%s AND target_day=%s AND work_id=%s",
                                                   (src, day, drop)).fetchall():
            both = conn.execute(
                "SELECT count(DISTINCT d.actor) FROM obs_post d JOIN obs_post k ON k.source=d.source AND k.target_day=d.target_day AND k.actor=d.actor "
                "AND k.work_id=%s AND (%s = '*' OR k.lang = d.lang) WHERE d.source=%s AND d.target_day=%s AND d.work_id=%s AND (%s = '*' OR d.lang=%s)",
                (keep, lang, src, day, drop, lang, lang)).fetchone()[0]
            conn.execute("INSERT INTO obs_work_lang_day (source,target_day,work_id,lang,persons,posts,version,computed_at) "
                         "SELECT source,target_day,%s,lang,persons,posts,version,computed_at FROM obs_work_lang_day "
                         "WHERE source=%s AND target_day=%s AND work_id=%s AND lang=%s ON CONFLICT (source,target_day,work_id,lang) "
                         "DO UPDATE SET persons = obs_work_lang_day.persons + EXCLUDED.persons - %s, posts = obs_work_lang_day.posts + EXCLUDED.posts",
                         (keep, src, day, drop, lang, both))
        conn.execute("DELETE FROM obs_work_lang_day WHERE source=%s AND target_day=%s AND work_id=%s", (src, day, drop))
    conn.execute("UPDATE obs_post d SET work_id=%s WHERE work_id=%s AND NOT EXISTS (SELECT 1 FROM obs_post k WHERE k.source=d.source "
                 "AND k.target_day=d.target_day AND k.unit=d.unit AND k.work_id=%s)", (keep, drop, keep))
    conn.execute("DELETE FROM obs_post WHERE work_id=%s", (drop,))
    return len(days)


def list_counts_left_on_merged_works(conn) -> list[tuple[int, int, int]]:
    """まとめ済み（work.detail.merged_into）の作品に残った確定の集計: (drop, keep, Source × 日の数)。"""
    return conn.execute(
        "SELECT o.work_id, (w.detail->>'merged_into')::int, count(DISTINCT (o.source, o.target_day)) FROM obs_work_lang_day o "
        "JOIN work w ON w.work_id=o.work_id WHERE w.detail ? 'merged_into' GROUP BY 1, 2 ORDER BY 1").fetchall()
