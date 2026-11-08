"""日次の実行の記録（job_run。Anime の repositories/job の該当部分を移植）。"""
from __future__ import annotations

import json
from datetime import timezone, date, datetime


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


def is_daily_run_active(conn, within_hours: int) -> bool:
    """日次処理が動いている最中か（running の行が within_hours 以内に始まっている）。Anime の repositories/job から移植。"""
    return conn.execute("SELECT EXISTS (SELECT 1 FROM job_run WHERE status='running' AND started_at > now() - make_interval(hours => %s))",
                        (within_hours,)).fetchone()[0]


def last_ok_finished_at(conn, job: str):
    return conn.execute("SELECT max(finished_at) FROM job_run WHERE job=%s AND status='ok'", (job,)).fetchone()[0]



# ---- 日ごとの成果物（Anime の repositories/job の job_artifact の関数をそのまま流用）
def get_artifact(conn, job: str, day: date, input_hash: str, generator_version: str) -> dict | None:
    """鍵が完全に一致する成果物（冪等の確認）。"""
    r = conn.execute("SELECT output FROM job_artifact WHERE job=%s AND target_day=%s AND input_hash=%s AND generator_version=%s",
                     (job, day, input_hash, generator_version)).fetchone()
    return r[0] if r else None


def has_artifact(conn, job: str, day: date) -> bool:
    """その日の成果物が 1 つでもあるか（版を問わない）。"""
    return conn.execute("SELECT 1 FROM job_artifact WHERE job=%s AND target_day=%s LIMIT 1", (job, day)).fetchone() is not None


def latest_artifact(conn, job: str, day: date, passed_only: bool = False) -> dict | None:
    """その日のいちばん新しい成果物（created_at で選ぶ）。passed_only なら output.passed が真のものだけ。"""
    cond = " AND (output->>'passed')::boolean" if passed_only else ""
    r = conn.execute(f"SELECT output FROM job_artifact WHERE job=%s AND target_day=%s{cond} ORDER BY created_at DESC LIMIT 1", (job, day)).fetchone()
    return r[0] if r else None


def latest_artifact_for_input(conn, job: str, day: date, input_hash: str) -> dict | None:
    """同じ入力（input_hash）の成果物のうちいちばん新しいもの（版を問わない）。"""
    r = conn.execute("SELECT output FROM job_artifact WHERE job=%s AND target_day=%s AND input_hash=%s ORDER BY created_at DESC LIMIT 1",
                     (job, day, input_hash)).fetchone()
    return r[0] if r else None


def list_artifacts(conn, job: str, day: date) -> list[dict]:
    """その日の成果物を新しい順に。"""
    return [o for (o,) in conn.execute("SELECT output FROM job_artifact WHERE job=%s AND target_day=%s ORDER BY created_at DESC", (job, day))]


def upsert_artifact(conn, job: str, day: date, input_hash: str, generator_version: str, output: dict) -> None:
    """同じ鍵があれば output と created_at を置き換える。"""
    conn.execute(
        "INSERT INTO job_artifact (job,target_day,input_hash,generator_version,created_at,output) VALUES (%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (job,target_day,input_hash,generator_version) DO UPDATE SET output=EXCLUDED.output, created_at=EXCLUDED.created_at",
        (job, day, input_hash, generator_version, datetime.now(timezone.utc), json.dumps(output, ensure_ascii=False, default=str)))


def replace_artifact(conn, job: str, day: date, input_hash: str, generator_version: str, output: dict) -> None:
    """その日の成果物を 1 行だけにする（古い行を残さない）。"""
    conn.execute("DELETE FROM job_artifact WHERE job=%s AND target_day=%s", (job, day))
    conn.execute("INSERT INTO job_artifact (job,target_day,input_hash,generator_version,created_at,output) VALUES (%s,%s,%s,%s,%s,%s)",
                 (job, day, input_hash, generator_version, datetime.now(timezone.utc), json.dumps(output, ensure_ascii=False, default=str)))


def newest_artifact_at(conn) -> datetime | None:
    """全成果物のうちいちばん新しい created_at（画面が内容を作り直す合図に使う）。"""
    return conn.execute("SELECT max(created_at) FROM job_artifact").fetchone()[0]


