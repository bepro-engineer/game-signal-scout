"""正規化の Service: 取得元の形の項目を、分析に使う共通の行（player_report）にする。

ProtonDB の報告の対応:
- failed: 遊べない（verdict = no）か、起動しない（startsPlay = no）。検証P で事前に固定した定義。
- config_hash: 機材構成（CPU・GPU・カーネル・OS・メモリ）の hash。投稿者の ID がないので、独立した報告者の近似に使う。生の値は持たない。
- notes: 自由記述の欄をまとめたもの（分析の根拠の確認に使う。公開しない）。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from game_signal_scout.repositories import report as repo

CONFIG_KEYS = ("cpu", "gpu", "kernel", "os", "ram")


def failed(record: dict) -> bool:
    r = record.get("responses") or {}
    return r.get("verdict") == "no" or r.get("startsPlay") == "no"


def config_hash(record: dict) -> str:
    s = record.get("systemInfo") or {}
    return hashlib.sha256("|".join(str(s.get(k, "")) for k in CONFIG_KEYS).encode()).hexdigest()[:16]


def notes(record: dict) -> str:
    r = record.get("responses") or {}
    parts = [f"{k}: {v}" for k, v in (r.get("notes") or {}).items() if isinstance(v, str) and v.strip()]
    if isinstance(r.get("concludingNotes"), str) and r["concludingNotes"].strip():
        parts.append("concludingNotes: " + r["concludingNotes"])
    return " | ".join(parts)


def protondb_row(item_id: str, record: dict) -> tuple:
    r = record.get("responses") or {}
    app = record.get("app") or {}
    return (item_id, (app.get("steam") or {}).get("appId"), app.get("title"), datetime.fromtimestamp(record["timestamp"], timezone.utc),
            failed(record), config_hash(record), r.get("protonVersion") or r.get("customProtonVersion"), notes(record))


def normalize(conn, source: str = "protondb", batch: int = 5000) -> int:
    """まだ正規化していない項目をすべて正規化する。入れた数（何度流しても、新しい項目がなければ 0）。"""
    total = 0
    while rows := repo.unnormalized(conn, source, batch):
        with conn.transaction():
            total += repo.normalize_new(conn, source, (protondb_row(i, p) for i, p in rows))
        conn.commit()
    return total
