"""daily-run: 段（collect → normalize → analyze → publish）を順に実行する（Anime の ops/runner を Game の最小の形に移植）。

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
    """取得元ごとに収集する。1 つの取得元の失敗で他の取得元を止めない。一部の失敗では段を失敗にしない（残りで後の段へ進む）。すべて失敗したときだけ段の失敗。
    取得元の設定 min_interval_hours（既定 0）より前に成功していれば、その取得元は今回は取りに行かない（取得の間隔の管理）。
    通信の記録（Fetcher.log）は取得元ごとに source_fetch へ保存する。"""
    from game_signal_scout.services.collect import collect
    from game_signal_scout.sources import factory
    from game_signal_scout.sources.http import Fetcher
    from game_signal_scout.repositories import fetch as fetch_repo
    make = ctx.reader_factory or (lambda name: factory.create(name, Fetcher(ctx.cfg["daily_run"]["user_agent"])))
    cfg = factory.load_sources_config()
    total, read, detail, first_error = 0, 0, {}, None
    for name in factory.sources(cfg):
        now = datetime.now(timezone.utc)
        state = fetch_repo.get_state(ctx.conn, name)
        hours = float(cfg[name].get("min_interval_hours") or 0)
        if hours and state.get("last_ok_at") and now - state["last_ok_at"] < timedelta(hours=hours):
            detail[name] = {"skipped": "interval", "last_ok_at": state["last_ok_at"]}
            continue
        fetch_repo.mark_attempt(ctx.conn, name, now)
        ctx.conn.commit()
        reader = make(name)
        reader.conn = ctx.conn              # 取得元が読む対象を DB から引くとき（作品の情報など）。どの取得元にも同じに渡す
        try:
            r = collect(ctx.conn, reader)
        except Exception as e:  # noqa: BLE001 — 取得元ごとに記録して、他の取得元へ進む
            try:
                ctx.conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            if ctx.conn.closed or ctx.conn.broken:
                raise
            retryable, etype = classify(e)
            fetch_repo.mark_result(ctx.conn, name, now, etype, str(e))
            detail[name] = {"error_type": etype, "retryable": retryable, "error_message": str(e)[:300]}
            first_error = first_error or e
        else:
            fetch_repo.mark_result(ctx.conn, name, datetime.now(timezone.utc))
            total, read = total + r.inserted, read + r.read
            detail[name] = r.as_detail()
        finally:
            log = getattr(reader, "log", None) or getattr(getattr(reader, "http", None), "log", None)   # ストリームの取得元は自分で記録する
            if log and not (ctx.conn.closed or ctx.conn.broken):
                fetch_repo.save_log(ctx.conn, log)
                log.clear()
            if not (ctx.conn.closed or ctx.conn.broken):
                ctx.conn.commit()
    # 取得元はどれもなくても困らない（CLAUDE.md・全 Issue 共通の原則）: 一部の取得元が失敗しても、残りの取得元で正規化・集計・公開へ進む。
    # 失敗は取得元ごとに source_state・detail に残す。読みに行った取得元がすべて失敗したときだけ段を失敗にする（再試行に回す）
    tried = [k for k, v in detail.items() if not (isinstance(v, dict) and v.get("skipped"))]
    failed = [k for k in tried if isinstance(detail[k], dict) and detail[k].get("error_type")]
    if first_error is not None and tried and len(failed) == len(tried):
        first_error.collect_detail = detail
        raise first_error
    return JobResult(input_count=read, output_count=total, detail=detail)


def job_normalize(ctx: Context) -> JobResult:
    from game_signal_scout.services.normalize import normalize_all
    out = normalize_all(ctx.conn)
    return JobResult(output_count=sum(out["counts"].values()), detail={**out["counts"], **({"errors": out["errors"]} if out["errors"] else {})})


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


def job_insight(ctx: Context) -> JobResult:
    """作品ごとに、最近のプレイヤーの発言を AI が読んで日本語でまとめる（services/insight。共有の LLM の枠を通す）。
    材料（使う発言）が前回と同じ作品は作り直さない。1 回に max_per_run 作品まで（多い作品から。残りは次の回）。1 作品の失敗で止めない。"""
    from game_signal_scout.repositories import catalog, insight as repo
    from game_signal_scout.services import insight
    ic = ctx.cfg.get("insight") or {}
    if not ic.get("enabled"):
        return JobResult(output_count=0, detail={"skipped": "disabled"})
    days, done, failed, skipped = int(ic.get("days", 30)), [], [], 0
    todo = repo.candidates(ctx.conn, days, int(ic.get("min_statements", 30)), int(ic.get("max_games", 40)))
    titles = {a: p["title"] for a, p in catalog.profiles(ctx.conn, todo).items()}
    for appid in todo:
        if len(done) >= int(ic.get("max_per_run", 12)):
            break
        inputs = insight.pick(repo.statements(ctx.conn, appid, days))
        if repo.get_hash(ctx.conn, appid) == insight.input_hash(inputs):
            skipped += 1
            continue
        try:
            x = insight.read_game(ctx.conn, appid, titles.get(appid) or appid, ic["model"], days)
        except Exception as e:  # noqa: BLE001 — 1 作品の失敗で止めない
            ctx.conn.rollback()
            failed.append({"appid": appid, "error": f"{type(e).__name__}: {str(e)[:160]}"})
            continue
        if x:
            repo.upsert(ctx.conn, x)
            ctx.conn.commit()
            done.append(appid)
    return JobResult(input_count=len(todo), output_count=len(done), detail={"done": done, "unchanged": skipped, "failed": failed})


def job_observe(ctx: Context) -> JobResult:
    """観測の集計（Anime の sources/observations をそのまま流用: 日 × 作品 × 言語の独立した投稿者。画面と今日の兆しの材料）。直近 28 日を作り直す。"""
    from game_signal_scout import observations
    d = ctx.day   # 日次の対象日（daily_run が default_day で決める。段ごとに別の日を使わない。#3 G6）
    res = observations.run(ctx.conn, observations.days_to_refresh(ctx.conn, d))
    errs = [r for r in res if r.get("error")]
    if errs and len(errs) == len(res):   # 取得元 × 日の一部の失敗では段を止めない（取得元 × 日ごとに記録して続ける。Anime と同じ）
        raise RuntimeError(f"観測の集計の失敗: {errs[0]}")
    return JobResult(output_count=sum(1 for r in res if r.get("state") == "complete"),
                     detail={"day": d.isoformat(), "days": len(res), **({"errors": errs[:20]} if errs else {})})


def job_digest(ctx: Context) -> JobResult:
    """今日の兆し（Anime の ops/jobs.dashboard_digest をそのまま流用）。観測した最新の日について、プレイヤーの声から発見を 1 つ確定して書き、
    job_artifact に保存する。[dashboard_digest] enabled のときだけ。失敗しても日次（公開）を止めない。同じ入力の記録があれば作り直さない。"""
    import sys
    from game_signal_scout.ops import dashboard_digest as dd
    from game_signal_scout.signal import content
    if not (ctx.cfg.get("dashboard_digest") or {}).get("enabled", False):
        return JobResult(detail={"status": "disabled"})
    day = ctx.day
    try:
        vc = content.day_ctx(ctx.cfg, day)
    except content.NoObservedDayError as e:      # 観測した日がまだない（取得元が観測を始める前）: 書く材料がない。失敗にしない
        return JobResult(detail={"status": "no_observed_day", "reason": str(e)})
    try:
        changes = content.work_changes(vc, day)
    finally:
        vc.conn.close()
    ih = dd.input_key(ctx.conn, day, dd.voice_sources(ctx.cfg), changes)
    done = job_repo.get_artifact(ctx.conn, dd.JOB, day, ih, dd.VERSION)
    if done is not None:
        return JobResult(output_count=int(bool(done.get("passed"))), detail={"status": "already_generated", "passed": done.get("passed")})
    out = {"version": dd.VERSION, "input_hash": ih, "generated_at": datetime.now(timezone.utc).isoformat()}
    try:
        out.update(dd.generate_day(dd.DbDayReader(ctx.conn), ctx.cfg, day, log=lambda m: print(m, file=sys.stderr), changes=changes))
    except Exception as e:  # noqa: BLE001 — 兆しの失敗で日次を止めない（保存しない。次の回に作り直す）
        ctx.conn.rollback()
        return JobResult(detail={"passed": False, "saved": False, "reason": f"error:{type(e).__name__}:{str(e)[:200]}"})
    job_repo.upsert_artifact(ctx.conn, dd.JOB, day, ih, dd.VERSION, out)
    ctx.conn.commit()
    return JobResult(input_count=len(out.get("per_work") or []), output_count=int(bool(out.get("passed"))),
                     detail={"passed": out.get("passed"), "finding": bool(out.get("finding")), "reason": out.get("reason")})


def job_publish(ctx: Context) -> JobResult:
    """分析の結果から公開用の文書を作り、表 public_document に置き換える（Viewer が読む。外への公開ではない）。
    検査に通らない・作れないときは、表を前の回のままにして段を失敗にする。"""
    from game_signal_scout.publication import publishing
    r = publishing.publish(ctx.conn, ctx.conn, ctx.cfg, "daily")
    if r["status"] in ("rejected", "failed"):
        raise RuntimeError(f"公開用の文書を置き換えなかった（{r['status']}）: {r.get('error')}")
    return JobResult(output_count=r.get("documents"), detail=r)


JOBS = {"collect": job_collect, "normalize": job_normalize, "observe": job_observe, "analyze": job_analyze, "insight": job_insight, "digest": job_digest,
        "publish": job_publish}


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
                            retryable=retryable, error_type=etype, error_message=str(e)[:2000], detail=getattr(e, "collect_detail", {}))
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
    from game_signal_scout.days import default_day
    day = day or default_day()   # 対象日はどの段も同じ（日本時間 3:00 区切りの、終わって落ち着いた最新の日。Anime と同じ）
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
