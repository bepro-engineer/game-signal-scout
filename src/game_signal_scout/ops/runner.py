"""daily-run: 段（collect → normalize → analyze）を順に実行する（Anime の ops/runner を Game の最小の形に移植）。

- 排他: 段ごと・日ごとの advisory lock（Game の DB の中だけで効く。LLM の機械全体の排他は llm_gate）。
- 記録: 段ごとに job_run（running → ok / failed / locked）。落ちて残った running は abandoned で閉じる。
- 再試行: 呼ぶ側の 1 層だけ。結果の JSON の retryable と終了コード（0 成功・75 再試行してよい・1 直らない）で返す。
- 冪等: どの段も何度流しても同じ結果（収集は続きの位置から、正規化は未処理だけ、分析は版ごとに置き換え）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from game_signal_scout import config, db
from game_signal_scout.errors import LockedError, classify
from game_signal_scout.repositories import job as job_repo, report as report_repo, session

EXIT_OK, EXIT_RETRY, EXIT_FATAL = 0, 75, 1


class AdvisoryLock:
    """名前の排他（専用の接続で持つ。プロセスが落ちれば自動で外れる）。"""

    def __init__(self, name: str, dsn: str | None = None):
        self.name = name
        self.conn = db.connect(dsn, autocommit=True)

    def __enter__(self):
        if not session.try_advisory_lock(self.conn, self.name):
            self.conn.close()
            raise LockedError(f"{self.name} は別のプロセスが使っている")
        return self

    def __exit__(self, *exc):
        try:
            session.advisory_unlock(self.conn, self.name)
        finally:
            self.conn.close()


@dataclass
class JobResult:
    input_count: int | None = None
    output_count: int | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class Context:
    conn: object
    day: date
    cfg: dict
    reader_factory: object = None     # 試験で取得元を差し替える（既定は sources.factory）


def job_collect(ctx: Context) -> JobResult:
    from game_signal_scout.services.collect import collect
    from game_signal_scout.sources import factory
    from game_signal_scout.sources.http import Fetcher
    make = ctx.reader_factory or (lambda name: factory.create(name, Fetcher(ctx.cfg["daily_run"]["user_agent"])))
    total, read, detail = 0, 0, {}
    for name in factory.sources():
        r = collect(ctx.conn, make(name))
        total, read = total + r.inserted, read + r.read
        detail[name] = r.as_detail()
    return JobResult(input_count=read, output_count=total, detail=detail)


def job_normalize(ctx: Context) -> JobResult:
    from game_signal_scout.services.normalize import normalize
    return JobResult(output_count=normalize(ctx.conn))


def analysis_range(day: date, p: dict) -> tuple[datetime, datetime]:
    """窓の始まりの範囲: 対象日までの 6 か月（検証P と同じ長さ）。"""
    end = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1)
    return end - timedelta(days=int(p.get("range_days", 184))), end


def job_analyze(ctx: Context) -> JobResult:
    from game_signal_scout.services.shift import detect
    p = ctx.cfg["analysis"]
    start, end = analysis_range(ctx.day, p)
    rows = report_repo.reports_for_analysis(ctx.conn, start - timedelta(days=p["prev_days"]), end + timedelta(days=p["window_days"]))
    events = detect(rows, start, end, p)
    with ctx.conn.transaction():
        report_repo.replace_events(ctx.conn, p["version"], events)
    ctx.conn.commit()
    return JobResult(input_count=len(rows), output_count=len(events),
                     detail={"fail": sum(e["side"] == "fail" for e in events), "fix": sum(e["side"] == "fix" for e in events)})


JOBS = {"collect": job_collect, "normalize": job_normalize, "analyze": job_analyze}


def _run_job(ctx: Context, run_id: str, name: str, attempt: int) -> dict:
    conn = ctx.conn
    rid = job_repo.insert_run(conn, run_id, name, ctx.day, attempt, datetime.now(timezone.utc), job_repo.count_failed_runs(conn, name, ctx.day))
    conn.commit()
    t0 = time.perf_counter()
    try:
        with AdvisoryLock(f"job:{name}:{ctx.day}"):
            res = JOBS[name](ctx)
    except BaseException as e:  # noqa: BLE001 — 記録して上へ返す
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        if conn.closed or conn.broken:
            conn = ctx.conn = db.connect()
        retryable, etype = classify(e)
        status = "locked" if isinstance(e, LockedError) else "failed"
        job_repo.finish_run(conn, rid, status=status, finished_at=datetime.now(timezone.utc), elapsed_seconds=time.perf_counter() - t0,
                            retryable=retryable, error_type=etype, error_message=str(e)[:2000], detail={})
        conn.commit()
        e.job_status = {"job": name, "status": status, "retryable": retryable, "error_type": etype, "error_message": str(e)[:500]}
        raise
    job_repo.finish_run(conn, rid, status="ok", finished_at=datetime.now(timezone.utc), elapsed_seconds=time.perf_counter() - t0,
                        input_count=res.input_count, output_count=res.output_count, detail=res.detail)
    conn.commit()
    return {"job": name, "status": "ok", "seconds": round(time.perf_counter() - t0, 2), "output": res.output_count, "detail": res.detail}


def daily_run(day: date | None = None, only: list[str] | None = None, attempt: int = 1, reader_factory=None) -> tuple[int, dict]:
    cfg = config.load_daily_config()
    dr = cfg["daily_run"]
    day = day or (datetime.now(timezone.utc).date() - timedelta(days=1))
    conn = db.connect()
    ctx = Context(conn, day, cfg, reader_factory)
    run_id = f"{day.isoformat()}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}"
    out = {"ok": False, "daily_run_id": run_id, "target_day": day.isoformat(), "attempt": attempt, "max_attempts": int(dr["max_attempts"]),
           "retry_after_minutes": int(dr["retry_after_minutes"]), "jobs": []}
    now = datetime.now(timezone.utc)
    out["abandoned_runs"] = job_repo.abandon_stale_runs(conn, now - timedelta(hours=int(dr["max_running_hours"])), now)
    conn.commit()
    try:
        with AdvisoryLock(f"daily:{day}"):
            for name in only or dr["jobs"]:
                out["jobs"].append(_run_job(ctx, run_id, name, attempt))
        out.update(ok=True, status="ok")
        code = EXIT_OK
    except BaseException as e:  # noqa: BLE001
        retryable, etype = classify(e)
        if getattr(e, "job_status", None):
            out["jobs"].append(e.job_status)
        out.update(status="locked" if isinstance(e, LockedError) else "failed", retryable=retryable, error_type=etype,
                   error_message=str(e)[:500], failed_job=getattr(e, "job_status", {}).get("job"))
        code = EXIT_RETRY if retryable else EXIT_FATAL
    finally:
        if not ctx.conn.closed:
            ctx.conn.close()
    return code, out
