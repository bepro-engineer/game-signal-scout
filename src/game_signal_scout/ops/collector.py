"""常駐の取得元の収集器（launchd の collect-<取得元> が `source-collect --source <取得元>` で動かす）。Anime の sources/runner.run の移植。

- 対象: config/sources.toml で resident = true の取得元（声の取得元はすべて同じ形で常駐。取得元の名前で分けない）。
- 1 周期 = 取得元の read の束（services/collect）を保存する。次の周期まで poll_seconds 待つ（Anime の cycle_wait と同じ考え方。0 なら続けて受信）。
- DB の接続の持ち方は、資源の条件で決まる共通の規則（取得元・システムの名前で分けない。#3 G10）:
  次の周期までの待ち（poll_seconds）が [collector] hold_connection_below_seconds より短い取得元は接続を持ち続け、
  それ以上待つ取得元は周期のあいだだけ接続し、待つあいだは閉じる（共有の PostgreSQL の接続の上限に近づかないため）。
- 二重起動: 周期のあいだ DB の advisory lock（collect:source:<取得元>）を持つ。取れなければその周期を飛ばす。launchd が同じ名前を 1 つだけ動かす。
- 止め方: SIGTERM / SIGINT で、周期の区切りで止まる（Anime と同じ）。1 周期の失敗で止めない（記録して error_backoff_seconds 待って次へ）。
- 生きている印: runtime/sources/<取得元>.heartbeat（周期ごと。ops/status が読む）。使えない取得元（記述がない・無効・常駐でない）は 0 で終わる。
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
    """常駐で収集する取得元（記述があり、enabled が false でなく、resident = true で、利用条件で禁止されていないもの）。"""
    from game_signal_scout import source_terms
    return [n for n, s in cfg.items() if isinstance(s, dict) and s.get("adapter") and s.get("enabled", True) and s.get("resident") and source_terms.allowed(n)]


def heartbeat_path(source: str):
    return config.RUNTIME / "sources" / f"{source}.heartbeat"


def holds_connection(poll_seconds: int, cfg: dict | None = None) -> bool:
    """待ちが短い取得元は接続を持ち続ける（資源の条件による共通の規則）。"""
    c = (cfg if cfg is not None else config.load_daily_config()).get("collector") or {}
    return poll_seconds < int(c.get("hold_connection_below_seconds", 60))


def cycle(source: str, reader, stop=lambda: False, conns: tuple | None = None) -> bool:
    """1 周期: 接続 → lock → 収集 → 記録 → 閉じる。成功なら True。conns（接続・lock の接続）を渡されたら、それを使い閉じない。"""
    from game_signal_scout.services.collect import collect
    conn, lock = conns or (db.connect(), db.connect(autocommit=True))
    try:
        if not session.try_advisory_lock(lock, f"collect:source:{source}"):
            log("locked", source=source)
            return True
        now = datetime.now(timezone.utc)
        fetch_repo.mark_attempt(conn, source, now)
        conn.commit()
        reader.conn = conn
        try:
            r = collect(conn, reader, max_batches=reader.settings.get("max_batches"), should_stop=stop)
            fetch_repo.mark_result(conn, source, datetime.now(timezone.utc))
            log("cycle", source=source, **r.as_detail())
            ok = True
        except Exception as e:  # noqa: BLE001 — 1 周期の失敗で止めない（記録して次へ）
            conn.rollback()
            etype = classify(e)[1]
            fetch_repo.mark_result(conn, source, now, etype, str(e))
            log("error", source=source, error_type=etype, error=f"{type(e).__name__}: {str(e)[:200]}")
            ok = False
        finally:
            rows = getattr(reader, "log", None) or getattr(getattr(reader, "http", None), "log", None)
            if rows and not (conn.closed or conn.broken):
                fetch_repo.save_log(conn, rows)
                rows.clear()
            if not (conn.closed or conn.broken):
                conn.commit()
            session.advisory_unlock(lock, f"collect:source:{source}")
        return ok
    finally:
        reader.conn = None
        if conns is None:
            lock.close()
            conn.close()


def run(source: str, once: bool = False, max_cycles: int | None = None, reader=None, sleep=time.sleep) -> int:
    from game_signal_scout.sources import factory
    from game_signal_scout.sources.http import Fetcher
    cfg = factory.load_sources_config()
    if source not in residents(cfg):
        log("disabled", source=source, reason="config/sources.toml で enabled かつ resident = true の取得元ではない")
        return EXIT_DISABLED
    scfg = cfg[source]
    if reader is None:
        reader = factory.create(source, Fetcher(config.load_daily_config()["daily_run"]["user_agent"]), cfg)
    poll, backoff = int(scfg.get("poll_seconds", 600)), int(scfg.get("error_backoff_seconds", 30))
    hb = heartbeat_path(source)
    hb.parent.mkdir(parents=True, exist_ok=True)
    stop = {"flag": False}

    def _term(*_):
        stop["flag"] = True
    prev = {s: signal.signal(s, _term) for s in (signal.SIGTERM, signal.SIGINT)}
    log("start", source=source, once=once)
    cycles = 0
    held = None
    try:
        while not stop["flag"]:
            if holds_connection(poll) and (held is None or any(c.closed or c.broken for c in held)):
                held = (db.connect(), db.connect(autocommit=True))
            ok = cycle(source, reader, stop=lambda: stop["flag"], conns=held)
            hb.write_text(datetime.now(timezone.utc).isoformat())
            cycles += 1
            if once or (max_cycles and cycles >= max_cycles):
                break
            for _ in range(poll if ok else backoff):          # 次の周期まで待つ（止めの合図で抜ける）
                if stop["flag"]:
                    break
                sleep(1)
    finally:
        for c in held or ():
            c.close()
        for s, h in prev.items():
            signal.signal(s, h)
        log("end", source=source, cycles=cycles, reason="signal" if stop["flag"] else "once")
    return 0
