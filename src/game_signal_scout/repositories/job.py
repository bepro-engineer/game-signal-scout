"""日次の実行の記録（job_run。Anime の repositories/job の該当部分を移植）。"""
from __future__ import annotations

import json
from datetime import date, datetime


def abandon_stale_runs(conn, older_than: datetime, now: datetime) -> int:
    """running のまま残った行（プロセスが落ちて終わりを書けなかった実行）を abandoned で閉じる。閉じた数。"""
    return conn.execute("UPDATE job_run SET status='abandoned', finished_at=%s, error_type='abandoned', "
                        "error_message='実行中のまま終わりが記録されなかった' WHERE status='running' AND started_at < %s",
                        (now, older_than)).rowcount


def count_failed_runs(conn, job: str, day: date) -> int:
    return conn.execute("SELECT count(*) FROM job_run WHERE job=%s AND target_day=%s AND status='failed'", (job, day)).fetchone()[0]


def insert_run(conn, daily_run_id: str, job: str, day: date, attempt: int, started_at: datetime, retry_count: int) -> int:
    return conn.execute("INSERT INTO job_run (daily_run_id, job, target_day, attempt, started_at, status, retry_count) "
                        "VALUES (%s,%s,%s,%s,%s,'running',%s) RETURNING id", (daily_run_id, job, day, attempt, started_at, retry_count)).fetchone()[0]


def finish_run(conn, run_id: int, *, status: str, finished_at: datetime, elapsed_seconds: float, input_count: int | None = None,
               output_count: int | None = None, retryable: bool | None = None, error_type: str | None = None, error_message: str | None = None,
               detail: dict | None = None) -> None:
    conn.execute("UPDATE job_run SET finished_at=%s, status=%s, input_count=%s, output_count=%s, elapsed_seconds=%s, retryable=%s, "
                 "error_type=%s, error_message=%s, detail=%s WHERE id=%s",
                 (finished_at, status, input_count, output_count, elapsed_seconds, retryable, error_type, error_message,
                  json.dumps(detail, ensure_ascii=False, default=str) if detail is not None else None, run_id))


def runs(conn, daily_run_id: str) -> list[tuple]:
    return conn.execute("SELECT job, status, retryable, error_type FROM job_run WHERE daily_run_id=%s ORDER BY id", (daily_run_id,)).fetchall()
