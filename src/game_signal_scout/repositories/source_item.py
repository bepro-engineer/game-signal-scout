"""取り込んだ項目（source_item）と、取得元ごとの続きの位置（source_checkpoint）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from game_signal_scout.sources.contract import SourceItem


def insert_items(conn, items: list[SourceItem]) -> int:
    """新しい項目だけ入れる（同じ (source, item_id) は入れない: 何度流しても同じ結果）。入れた数。"""
    if not items:
        return 0
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (source, item_id) DO NOTHING",
            [(i.source, i.item_id, i.occurred_at, now, json.dumps(i.payload, ensure_ascii=False)) for i in items])
        return cur.rowcount   # executemany の rowcount は全行の合計（psycopg 3.1 以降）


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
