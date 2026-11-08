"""短い間隔の収集（命令 poll。launchd の poll が poll_minutes ごとに起動する）。

対象: config/sources.toml で poll = true の取得元（新着だけを返すフィード・JSON の掲示板。日次 1 回では大半を取りこぼす）。
1 回 = 対象の取得元をそれぞれ collect → 正規化（services/normalize の記述の normalizer）。1 つの取得元の失敗で他を止めない。
二重起動は DB の advisory lock（poll）。日次の collect もこれらを読むが、続きの位置（checkpoint）は同じ取引で進むので重複も欠落もしない。
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone

from game_signal_scout import config, db
from game_signal_scout.errors import classify
from game_signal_scout.repositories import fetch as fetch_repo, session


def pollers(cfg: dict) -> list[str]:
    return [n for n, s in cfg.items() if isinstance(s, dict) and s.get("adapter") and s.get("enabled", True) and s.get("poll")]


def run(reader_factory=None) -> dict:
    from game_signal_scout.services.collect import collect
    from game_signal_scout.sources import factory
    from game_signal_scout.sources.http import Fetcher
    cfg = factory.load_sources_config()
    http = Fetcher(config.load_daily_config()["daily_run"]["user_agent"])
    make = reader_factory or (lambda n: factory.create(n, http, cfg))
    lock = db.connect(autocommit=True)
    if not session.try_advisory_lock(lock, "poll"):
        lock.close()
        return {"status": "locked"}
    out: dict[str, dict] = {}
    try:
        with db.connect() as conn:
            for name in pollers(cfg):
                now = datetime.now(timezone.utc)
                reader = make(name)
                reader.conn = conn
                try:
                    r = collect(conn, reader)
                    mod, fn = cfg[name]["normalizer"].split(":")
                    n = getattr(importlib.import_module(mod), fn)(conn, name, cfg[name])
                    fetch_repo.mark_result(conn, name, now)
                    out[name] = {"inserted": r.inserted, "normalized": n}
                except Exception as e:  # noqa: BLE001 — 取得元ごとに記録して次へ
                    conn.rollback()
                    _, etype = classify(e)
                    fetch_repo.mark_result(conn, name, now, etype, str(e))
                    out[name] = {"error_type": etype, "error": str(e)[:200]}
                finally:
                    log = getattr(reader, "http", None) and reader.http.log
                    if log:
                        fetch_repo.save_log(conn, log)
                        log.clear()
                    conn.commit()
    finally:
        lock.close()
    return {"status": "ok", "sources": out}


def main() -> int:
    print(json.dumps(run(), ensure_ascii=False, default=str), file=sys.stdout, flush=True)
    return 0
