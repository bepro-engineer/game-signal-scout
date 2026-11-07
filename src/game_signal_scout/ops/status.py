"""監視が読む状態（1 行の JSON）。取得・登録・分析・公開を分けて返し、データの鮮度と処理の成否を混ぜない。

- jobs: 段ごとの最後の実行（状態・再試行の可否・誤りの種類・件数）と、最後に成功した時刻
- sources: 取得元ごとの保存件数・最新の発生時刻（データの鮮度）・最後に保存した時刻・続きの位置・最後の収集の異常
- analysis: 規則の版ごとの事象の数
- publication: Viewer が読む文書を最後に作った回（public_build）と、外への公開（まだない: "none"）
"""
from __future__ import annotations

from game_signal_scout import config
from game_signal_scout.repositories import source_item


def status(conn) -> dict:
    jobs = {}
    for job, st, retryable, etype, out, finished, detail in conn.execute(
            "SELECT DISTINCT ON (job) job, status, retryable, error_type, output_count, finished_at, detail FROM job_run ORDER BY job, started_at DESC"):
        jobs[job] = {"status": st, "retryable": retryable, "error_type": etype, "output": out, "finished_at": finished}
        if job == "collect" and detail:
            jobs[job]["sources"] = {k: {"read": v.get("read"), "inserted": v.get("inserted"), "deleted": v.get("deleted"), "anomalies": v.get("anomalies")}
                                    for k, v in detail.items()}
    for job, ok_at in conn.execute("SELECT job, max(finished_at) FROM job_run WHERE status='ok' GROUP BY job"):
        jobs.setdefault(job, {})["last_ok_at"] = ok_at
    sources = {s: {"items": n, "newest_occurred_at": newest, "last_received_at": rec, "cursor": cur, "cursor_updated_at": upd}
               for s, n, newest, rec, cur, upd in source_item.summary(conn)}
    from game_signal_scout.repositories import fetch
    for s, st in fetch.states(conn).items():           # 最後の試行・成功・失敗（データがまだない取得元も出す）
        sources.setdefault(s, {"items": 0}).update(st)
    version = config.load_daily_config()["analysis"]["version"]
    events = dict(conn.execute("SELECT side, count(*) FROM shift_event WHERE version=%s GROUP BY side", (version,)).fetchall())
    from game_signal_scout.repositories import public_document
    last, tried = public_document.get_last_published_build(conn), public_document.get_last_finished_build(conn)
    publication = {"documents_built_at": last["finished_at"] if last else None, "documents": last["documents"] if last else 0,
                   "stale": bool(tried and tried["status"] != "published"), "external": "none"}
    return {"jobs": jobs, "sources": sources, "analysis": {"version": version, "events": events}, "publication": publication}
