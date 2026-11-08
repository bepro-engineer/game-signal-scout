"""常駐の取得元の収集器（launchd から `source-collect --source <取得元>`。Anime の sources/runner.run を Game の最小の形に移植）。

- 対象: config/sources.toml で resident = true の取得元（常駐で受信する取得元。日次の collect はこれを読まない: 続きの位置を 2 つのプロセスで取り合わない）。
- 1 周期 = 取得元の read の束 1 つ（ストリームの取得元は batch_seconds の間の受信）を services/collect で保存する。日次と同じ Service・同じ取引。
- 二重起動: DB の advisory lock（collect:source:<取得元>）。取れなければ 75 で終わり、launchd の ThrottleInterval の後に取り直す（Anime と同じ。
  再起動の直後は前のプロセスがまだ lock を持っていることがある）。
- 止め方: SIGTERM / SIGINT で、周期の区切りで止まる（Anime と同じ）。
- 1 周期の失敗で止めない（記録して error_backoff_seconds 待って次へ）。通信の記録は source_fetch、最後の成否は source_fetch_state に残す。
- 生きている印: runtime/sources/<取得元>.heartbeat（周期ごとに時刻を書く。ops/status が読む）。
- 使えない取得元（記述がない・無効・常駐でない）は 0 で終わる（launchd が起動し直さない。Anime の EXIT_SOURCE_DISABLED と同じ扱い）。
Anime にある、版の切り替え（76）・監視からの起動し直しの依頼・影運用の DB は、Game には版の切り替えの仕組みがまだないので移植していない。
"""
from __future__ import annotations

import json
import signal
import sys
import time
from datetime import datetime, timezone

from game_signal_scout import config, db
from game_signal_scout.errors import classify
from game_signal_scout.repositories import fetch as fetch_repo, session

EXIT_DISABLED, EXIT_LOCKED = 0, 75


def log(event: str, **kw) -> None:
    print(json.dumps({"event": event, "ts": datetime.now(timezone.utc).isoformat(), **kw}, ensure_ascii=False, default=str), file=sys.stderr, flush=True)


def residents(cfg: dict) -> list[str]:
    """常駐で収集する取得元（記述があり、enabled が false でなく、resident = true）。"""
    return [n for n, s in cfg.items() if isinstance(s, dict) and s.get("adapter") and s.get("enabled", True) and s.get("resident")]


def heartbeat_path(source: str):
    return config.RUNTIME / "sources" / f"{source}.heartbeat"


def run(source: str, once: bool = False, max_cycles: int | None = None, reader=None, sleep=time.sleep) -> int:
    from game_signal_scout.services.collect import collect
    from game_signal_scout.sources import factory
    from game_signal_scout.sources.http import Fetcher
    cfg = factory.load_sources_config()
    if source not in residents(cfg):
        log("disabled", source=source, reason="config/sources.toml で enabled かつ resident = true の取得元ではない")
        return EXIT_DISABLED
    scfg = cfg[source]
    if reader is None:
        reader = factory.create(source, Fetcher(config.load_daily_config()["daily_run"]["user_agent"]), cfg)
    backoff = float(scfg.get("error_backoff_seconds", 30))
    hb = heartbeat_path(source)
    hb.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    lock = db.connect(autocommit=True)   # 排他は専用の接続で持つ（周期の取引の commit・rollback と切り離す）
    if not session.try_advisory_lock(lock, f"collect:source:{source}"):
        log("already_running", source=source)
        lock.close()
        conn.close()
        return EXIT_LOCKED
    stop = {"flag": False}

    def _term(*_):
        stop["flag"] = True
    prev = {s: signal.signal(s, _term) for s in (signal.SIGTERM, signal.SIGINT)}
    log("start", source=source, once=once)
    cycles = 0
    try:
        while not stop["flag"]:
            now = datetime.now(timezone.utc)
            fetch_repo.mark_attempt(conn, source, now)
            conn.commit()
            failed = False
            try:
                r = collect(conn, reader, max_batches=1, should_stop=lambda: stop["flag"])
                fetch_repo.mark_result(conn, source, datetime.now(timezone.utc))
                log("cycle", source=source, **r.as_detail())
            except Exception as e:  # noqa: BLE001 — 1 周期の失敗で止めない（記録して次へ）
                conn.rollback()
                if conn.closed or conn.broken:
                    raise
                etype = classify(e)[1]
                fetch_repo.mark_result(conn, source, now, etype, str(e))
                log("error", source=source, error_type=etype, error=f"{type(e).__name__}: {str(e)[:200]}")
                failed = True
            finally:
                rows = getattr(reader, "log", None)
                if rows and not (conn.closed or conn.broken):
                    fetch_repo.save_log(conn, rows)
                    rows.clear()
                if not (conn.closed or conn.broken):
                    conn.commit()
            hb.write_text(datetime.now(timezone.utc).isoformat())
            cycles += 1
            if once or (max_cycles and cycles >= max_cycles):
                break
            if failed:
                for _ in range(int(backoff)):
                    if stop["flag"]:
                        break
                    sleep(1)
    finally:
        for s, h in prev.items():
            signal.signal(s, h)
        log("end", source=source, cycles=cycles, reason="signal" if stop["flag"] else "once")
        try:
            session.advisory_unlock(lock, f"collect:source:{source}")
        finally:
            lock.close()
            conn.close()
    return 0
