"""取り込んだ項目（source_item）と、取得元ごとの続きの位置（source_checkpoint）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from game_signal_scout.sources.contract import SourceItem

UPSERT = (
    "INSERT INTO source_item (source, item_id, occurred_at, received_at, payload, seen_in, version) VALUES (%s,%s,%s,%s,%s,%s,%s) "
    "ON CONFLICT (source, item_id) DO UPDATE SET seen_in = EXCLUDED.seen_in, "
    "  payload = CASE WHEN source_item.version IS DISTINCT FROM EXCLUDED.version THEN EXCLUDED.payload ELSE source_item.payload END, "
    "  occurred_at = CASE WHEN source_item.version IS DISTINCT FROM EXCLUDED.version THEN EXCLUDED.occurred_at ELSE source_item.occurred_at END, "
    "  received_at = CASE WHEN source_item.version IS DISTINCT FROM EXCLUDED.version THEN EXCLUDED.received_at ELSE source_item.received_at END, "
    "  version = EXCLUDED.version "
    "WHERE source_item.version IS DISTINCT FROM EXCLUDED.version OR source_item.seen_in IS DISTINCT FROM EXCLUDED.seen_in")


def upsert_items(conn, items: list[SourceItem], seen_in: str | None) -> tuple[int, int]:
    """項目を入れる。同じ項目は 1 件（何度流しても同じ）。版が変わった項目は置き換え、その正規化を消す（次の正規化でやり直す）。
    返り値は (新しく入れた数, 版が変わって置き換えた数)。前の版は保存の前に読む（PostgreSQL 17 の RETURNING は更新後の値しか返さない）。"""
    if not items:
        return 0, 0
    source = items[0].source
    before = dict(conn.execute("SELECT item_id, version FROM source_item WHERE source=%s AND item_id = ANY(%s)",
                               (source, list({i.item_id for i in items}))).fetchall())
    latest = {i.item_id: i.version for i in items}
    inserted = sum(1 for k in latest if k not in before)
    changed = [k for k, v in latest.items() if k in before and before[k] != v]
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.executemany(UPSERT, [(i.source, i.item_id, i.occurred_at, now, json.dumps(i.payload, ensure_ascii=False), seen_in, i.version)
                                 for i in items])
    if changed:
        for table in NORMALIZED:
            conn.execute(f"DELETE FROM {table} WHERE source=%s AND item_id = ANY(%s)", (source, changed))
    return inserted, len(changed)


NORMALIZED = ("player_report", "player_post", "game_profile", "game_activity", "game_assets")   # 正規化した行の表（版が変わった項目の行を消し、次の正規化でやり直す）


def _record_gone(conn, source: str, kind: str, refs: list[str]) -> None:
    """削除の事実を残す（Anime の §2: 行の本文は消し、消えたことは残す）。本文・名前は持たない。"""
    if refs:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO source_gone (source, ref, kind, gone_at) VALUES (%s, %s, %s, now()) ON CONFLICT DO NOTHING",
                            [(source, r, kind) for r in refs])


def delete_items(conn, source: str, item_ids: list[str]) -> int:
    """取得元で消えた項目を消す（正規化した行も外部キーで一緒に消える）。消えた事実は source_gone に残す。"""
    if not item_ids:
        return 0
    gone = [r[0] for r in conn.execute("SELECT item_id FROM source_item WHERE source=%s AND item_id = ANY(%s)", (source, list(item_ids)))]
    _record_gone(conn, source, "item", gone)
    return conn.execute("DELETE FROM source_item WHERE source=%s AND item_id = ANY(%s)", (source, list(item_ids))).rowcount


def delete_by_author(conn, source: str, authors: list[str]) -> int:
    """消えた投稿者（アカウントの削除・停止）の項目をすべて消す。投稿者は payload の author（HMAC）。"""
    if not authors:
        return 0
    _record_gone(conn, source, "author", list(authors))
    return conn.execute("DELETE FROM source_item WHERE source=%s AND payload->>'author' = ANY(%s)", (source, list(authors))).rowcount


def delete_missing(conn, source: str, snapshot: str, min_ratio: float) -> int:
    """全件の写しを読み終えた後、その写しにない項目を消す（削除への追従）。写しの件数が保存済みの min_ratio 未満なら、
    壊れた・途中で切れた写しの疑いがあるので消さずに 0 を返す（呼ぶ側が異常として記録する）。"""
    seen, total = conn.execute("SELECT count(*) FILTER (WHERE seen_in = %s), count(*) FROM source_item WHERE source=%s", (snapshot, source)).fetchone()
    if total == 0 or seen < total * min_ratio:
        return -1 if total else 0
    gone = [r[0] for r in conn.execute("SELECT item_id FROM source_item WHERE source=%s AND seen_in IS DISTINCT FROM %s", (source, snapshot))]
    _record_gone(conn, source, "item", gone)
    return conn.execute("DELETE FROM source_item WHERE source=%s AND seen_in IS DISTINCT FROM %s", (source, snapshot)).rowcount


def purge_received_before(conn, source: str, cutoff: datetime) -> int:
    """保持期限を過ぎた項目を消す（正規化した行も外部キーで一緒に消える）。"""
    return conn.execute("DELETE FROM source_item WHERE source=%s AND received_at < %s", (source, cutoff)).rowcount


def count(conn, source: str) -> int:
    return conn.execute("SELECT count(*) FROM source_item WHERE source=%s", (source,)).fetchone()[0]


def get_checkpoint(conn, source: str) -> dict | None:
    r = conn.execute("SELECT cursor FROM source_checkpoint WHERE source=%s", (source,)).fetchone()
    return r[0] if r else None


def set_checkpoint(conn, source: str, cursor: dict) -> None:
    conn.execute(
        "INSERT INTO source_checkpoint (source, cursor, updated_at) VALUES (%s,%s,now()) "
        "ON CONFLICT (source) DO UPDATE SET cursor=EXCLUDED.cursor, updated_at=EXCLUDED.updated_at",
        (source, json.dumps(cursor)))


def summary(conn) -> list[tuple]:
    """取得元ごとの件数・最新の発生時刻（データの鮮度）・最後に保存した時刻・続きの位置。"""
    return conn.execute("SELECT s.source, count(*), max(s.occurred_at), max(s.received_at), c.cursor, c.updated_at FROM source_item s "
                        "LEFT JOIN source_checkpoint c ON c.source = s.source GROUP BY s.source, c.cursor, c.updated_at ORDER BY s.source").fetchall()



# ---- Anime の source_item の、観測の範囲の表示に使う 2 つの関数（Game は共通の発言 player_post の言語で数える）
def count_items_by_lang_day(conn, start, end) -> list[tuple]:
    """期間に受け取った発言の数を言語 × 放送日（3:00 JST の区切り）で (lang, 放送日, 件数)。"""
    return conn.execute("SELECT lang, ((at) AT TIME ZONE 'Asia/Tokyo' - interval '3 hours')::date, count(*) FROM player_post "
                        "WHERE at >= %s AND at < %s GROUP BY 1, 2", (start, end)).fetchall()


def get_last_ok_fetch_of_any_source(conn):
    return conn.execute("SELECT max(ts) FROM source_fetch WHERE ok").fetchone()[0]



def list_item_texts(conn, source: str, item_ids: list[str]) -> list[tuple]:
    """項目の本文と言語 (item_id, 言語, body)（Anime と同じ形。Game は共通の発言 player_post の本文）。"""
    return conn.execute("SELECT item_id, lang, text FROM player_post WHERE source=%s AND item_id = ANY(%s)", (source, item_ids)).fetchall()


def apps_with_items_before(conn, source: str, appids: list[str], days: int) -> set[str]:
    """保存したいちばん古い項目が days 日より前の作品（payload の appid ごと。レビューの過去がそろったか）。"""
    rows = conn.execute("SELECT payload->>'appid' FROM source_item WHERE source = %s AND payload->>'appid' = ANY(%s) GROUP BY 1 "
                        "HAVING min(occurred_at) < now() - make_interval(days => %s)", (source, list(appids), days)).fetchall()
    return {r[0] for r in rows}


def count_known(conn, source: str, item_ids: list[str]) -> int:
    return conn.execute("SELECT count(*) FROM source_item WHERE source = %s AND item_id = ANY(%s)", (source, list(item_ids))).fetchone()[0]


def first_seen(conn, source: str, by_occurred: bool = False):
    """取得元の観測を始めた時刻: by_occurred なら保存したいちばん古い項目の時刻（過去を遡って取る取得元）、ほかは最初に受信した時刻。"""
    col = "occurred_at" if by_occurred else "received_at"
    return conn.execute(f"SELECT min({col}) FROM source_item WHERE source = %s", (source,)).fetchone()[0]
