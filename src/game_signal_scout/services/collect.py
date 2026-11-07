"""収集の Service: どの取得元にも同じ手順で、束ごとに「項目の保存と続きの位置の記録」を 1 つの取引で行う。

- 冪等: 同じ項目は 1 件（source_item の主キー）。何度流しても件数は変わらない。版が変わった項目だけ置き換える。
- 再開: 途中で落ちても、最後に記録した位置から読み直す（記録より後の束は保存されていないので、重複も欠落もない）。
- 削除への追従: 全件の写し（配布物）を読み終えたら、写しにない項目を消す。写しが保存済みより極端に少なければ、
  壊れた写しの疑いとして消さずに異常（snapshot_too_small）を残す。
- 保持期限: 取得元の設定 retention_days（0 なら無期限）を過ぎた項目を消す。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from game_signal_scout.repositories import source_item as repo


@dataclass
class CollectResult:
    batches: int = 0
    read: int = 0
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    purged: int = 0
    complete: bool = False
    cursor: dict | None = None
    anomalies: list[str] = field(default_factory=list)

    def as_detail(self) -> dict:
        return {k: getattr(self, k) for k in ("read", "inserted", "updated", "deleted", "purged", "complete", "anomalies")}


def collect(conn, reader, max_batches: int | None = None, should_stop=lambda: False, now: datetime | None = None) -> CollectResult:
    name, settings = reader.name, reader.settings
    res = CollectResult(cursor=repo.get_checkpoint(conn, name))
    conn.commit()
    for batch in reader.read(res.cursor):
        snapshot = batch.cursor.get("snapshot")
        with conn.transaction():
            ins, upd = repo.upsert_items(conn, batch.items, snapshot)
            res.inserted, res.updated = res.inserted + ins, res.updated + upd
            res.complete = bool(batch.cursor.get("complete"))
            if res.complete and snapshot:
                n = repo.delete_missing(conn, name, snapshot, float(settings.get("min_snapshot_ratio", 0.9)))
                if n < 0:
                    res.anomalies.append("snapshot_too_small")
                else:
                    res.deleted += n
            repo.set_checkpoint(conn, name, batch.cursor)
        conn.commit()
        res.batches += 1
        res.read += len(batch.items)
        res.cursor = batch.cursor
        if (max_batches and res.batches >= max_batches) or should_stop():
            break
    if res.complete and res.read == 0 and res.inserted == 0 and not (res.cursor or {}).get("offset"):
        res.anomalies.append("source_empty")
    days = int(settings.get("retention_days") or 0)
    if days > 0:
        with conn.transaction():
            res.purged = repo.purge_received_before(conn, name, (now or datetime.now(timezone.utc)) - timedelta(days=days))
        conn.commit()
    return res
