"""収集の Service: どの取得元にも同じ手順で、束ごとに「項目の保存と続きの位置の記録」を 1 つの取引で行う。

- 冪等: 同じ項目は 1 件（source_item の主キー）。何度流しても件数は変わらない。
- 再開: 途中で落ちても、最後に記録した位置から読み直す（記録より後の束は保存されていないので、重複も欠落もない）。
"""
from __future__ import annotations

from dataclasses import dataclass

from game_signal_scout.repositories import source_item as repo


@dataclass
class CollectResult:
    batches: int = 0
    read: int = 0
    inserted: int = 0
    complete: bool = False
    cursor: dict | None = None


def collect(conn, reader, max_batches: int | None = None, should_stop=lambda: False) -> CollectResult:
    res = CollectResult(cursor=repo.get_checkpoint(conn, reader.name))
    conn.commit()
    for batch in reader.read(res.cursor):
        with conn.transaction():
            res.inserted += repo.insert_items(conn, batch.items)
            repo.set_checkpoint(conn, reader.name, batch.cursor)
        conn.commit()
        res.batches += 1
        res.read += len(batch.items)
        res.cursor = batch.cursor
        res.complete = bool(batch.cursor.get("complete"))
        if (max_batches and res.batches >= max_batches) or should_stop():
            break
    return res
