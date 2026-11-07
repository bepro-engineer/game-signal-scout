"""一時の DB での試験: 移行・収集の 1 周期・冪等な再実行・途中の失敗からの再開・二重起動の排他・他の DB への誤接続の防止。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from conftest import ADMIN, make_dump, report
from game_signal_scout import config, db
from game_signal_scout.ops import runner
from game_signal_scout.repositories import source_item
from game_signal_scout.sources import factory

DAY = 86400
T0 = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
TARGET = date(2026, 10, 31)


def dump_records():
    """作品 A は 6 月 1 日から遊べなくなる（7 件・機材 7 種類）。作品 C は変化なし。"""
    reps = [report("A", T0 - 50 * DAY + i * DAY, False, i) for i in range(10)]
    reps += [report("A", T0 + i * DAY, True, 100 + i, note="anti-cheat blocks launch") for i in range(7)]
    reps += [report("C", T0 + i * 3600, False, i) for i in range(20)]
    return reps


def reader_for(path, batch_size=4, fail_after=None):
    cfg = {"protondb": {"adapter": "game_signal_scout.sources.protondb:ProtonDBDump", "local_path": str(path), "batch_size": batch_size}}
    r = factory.create("protondb", None, cfg)
    if fail_after is None:
        return r
    real = r.read

    def broken(cursor):
        for k, b in enumerate(real(cursor)):
            if k == fail_after:
                raise ConnectionError("通信が切れた（試験）")
            yield b
    r.read = broken
    return r


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_migration_down_and_up(test_db, conn):
    from alembic import command
    conn.close()
    command.downgrade(test_db["alembic"], "base")
    with psycopg.connect(test_db["dsn"]) as c:
        assert c.execute("SELECT to_regclass('source_item')").fetchone()[0] is None
    command.upgrade(test_db["alembic"], "head")
    with db.connect(test_db["dsn"]) as c:
        assert [r[0] for r in c.execute("SELECT scout FROM scout_identity")] == ["game"]


def test_daily_run_one_cycle_and_idempotent_rerun(conn, tmp_path):
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", dump_records())
    code, out = runner.daily_run(TARGET, reader_factory=lambda name: reader_for(path))
    assert code == runner.EXIT_OK, out
    assert [j["job"] for j in out["jobs"]] == ["collect", "normalize", "analyze"]
    assert (count(conn, "source_item"), count(conn, "player_report")) == (37, 37)
    ev = conn.execute("SELECT side, appid, n_key FROM shift_event").fetchall()
    assert ev == [("fail", "A", 7)]
    # もう一度流しても同じ結果（重複しない・同じ版の検出は置き換え）
    code, out = runner.daily_run(TARGET, reader_factory=lambda name: reader_for(path))
    assert code == runner.EXIT_OK
    assert out["jobs"][0]["output"] == 0 and out["jobs"][1]["output"] == 0
    assert (count(conn, "source_item"), count(conn, "player_report"), count(conn, "shift_event")) == (37, 37, 1)
    assert [r[1] for r in conn.execute("SELECT job, status FROM job_run ORDER BY id")] == ["ok"] * 6


def test_failure_midway_is_retryable_and_resumes_without_duplicates(conn, tmp_path):
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", dump_records())
    code, out = runner.daily_run(TARGET, reader_factory=lambda name: reader_for(path, fail_after=3))
    assert code == runner.EXIT_RETRY and out["failed_job"] == "collect" and out["error_type"] == "network"
    assert count(conn, "source_item") == 12                              # 3 束（4 件ずつ）は保存済み
    assert source_item.get_checkpoint(conn, "protondb") == {"dump": path.name, "offset": 12}
    assert conn.execute("SELECT status, retryable, error_type FROM job_run").fetchall() == [("failed", True, "network")]
    code, out = runner.daily_run(TARGET, attempt=2, reader_factory=lambda name: reader_for(path))
    assert code == runner.EXIT_OK
    assert out["jobs"][0]["detail"]["protondb"]["read"] == 25              # 続きから読んだ
    assert (count(conn, "source_item"), count(conn, "player_report")) == (37, 37)


def test_concurrent_run_is_locked_out(test_db, conn, tmp_path):
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", dump_records())
    with runner.AdvisoryLock(f"daily:{TARGET}"):
        code, out = runner.daily_run(TARGET, reader_factory=lambda name: reader_for(path))
    assert code == runner.EXIT_RETRY and out["status"] == "locked" and out["retryable"]
    assert count(conn, "source_item") == 0


def test_stale_running_rows_are_abandoned(conn, tmp_path):
    conn.execute("INSERT INTO job_run (daily_run_id, job, target_day, attempt, started_at, status) VALUES ('x','collect',%s,1,%s,'running')",
                 (TARGET, datetime.now(timezone.utc) - timedelta(hours=12)))
    conn.commit()
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", dump_records())
    code, out = runner.daily_run(TARGET, only=["collect"], reader_factory=lambda name: reader_for(path))
    assert code == runner.EXIT_OK and out["abandoned_runs"] == 1


def test_refuses_database_of_another_scout(test_db):
    other = f"game_signal_scout_other_{test_db['name'][-8:]}"
    with psycopg.connect(ADMIN, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{other}"')
    try:
        dsn = make_conninfo(ADMIN, dbname=other)
        with psycopg.connect(dsn, autocommit=True) as c:   # 名前は Game の形でも、中身が別の Scout の DB
            c.execute("CREATE TABLE scout_identity (scout text); INSERT INTO scout_identity VALUES ('anime')")
        with pytest.raises(config.WrongDatabaseError):
            db.connect(dsn)
        with pytest.raises(config.WrongDatabaseError):     # 名前が Game でない DB には接続の前に止まる
            db.connect(make_conninfo(ADMIN, dbname="postgres"))
    finally:
        with psycopg.connect(ADMIN, autocommit=True) as c:
            c.execute(f'DROP DATABASE "{other}" WITH (FORCE)')
