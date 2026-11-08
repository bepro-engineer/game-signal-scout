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



@pytest.fixture(autouse=True)
def only_protondb(monkeypatch):
    """この試験は 1 つの取得元（ProtonDB の配布データ）の段の振る舞いを見る。ほかの取得元は記述から外す（偽の読み手を全取得元に渡すため）。"""
    from game_signal_scout.sources import factory
    real = factory.load_sources_config()
    monkeypatch.setattr(factory, "load_sources_config", lambda: {"protondb": real["protondb"], "steam_reviews": {**real["steam_reviews"], "enabled": False}})   # steam_reviews は試験の部品だけ使う

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


def test_daily_run_one_cycle_and_idempotent_rerun(conn, tmp_path, stub_screen_docs):
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", dump_records())
    code, out = runner.daily_run(TARGET, reader_factory=lambda name: reader_for(path))
    assert code == runner.EXIT_OK, out
    assert [j["job"] for j in out["jobs"]] == ["collect", "normalize", "observe", "analyze", "insight", "digest", "publish"]
    assert out["jobs"][6]["detail"]["status"] == "published" and out["jobs"][6]["output"] >= 2
    assert (count(conn, "source_item"), count(conn, "player_report")) == (37, 37)
    ev = conn.execute("SELECT side, appid, n_key FROM shift_event").fetchall()
    assert ev == [("fail", "A", 7)]
    # もう一度流しても同じ結果（重複しない・同じ版の検出は置き換え）
    code, out = runner.daily_run(TARGET, reader_factory=lambda name: reader_for(path))
    assert code == runner.EXIT_OK
    assert out["jobs"][0]["output"] == 0 and out["jobs"][1]["output"] == 0
    assert (count(conn, "source_item"), count(conn, "player_report"), count(conn, "shift_event")) == (37, 37, 1)
    assert [r[1] for r in conn.execute("SELECT job, status FROM job_run ORDER BY id")] == ["ok"] * 14


def test_failure_midway_is_retryable_and_resumes_without_duplicates(conn, tmp_path, stub_screen_docs):
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", dump_records())
    code, out = runner.daily_run(TARGET, reader_factory=lambda name: reader_for(path, fail_after=3))
    assert code == runner.EXIT_RETRY and out["failed_job"] == "collect" and out["error_type"] == "network"
    assert count(conn, "source_item") == 12                              # 3 束（4 件ずつ）は保存済み
    assert source_item.get_checkpoint(conn, "protondb") == {"dump": path.name, "snapshot": path.name, "offset": 12}
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


def collect_with(conn, path, **settings):
    from game_signal_scout.services.collect import collect
    r = reader_for(path)
    r.settings.update(settings)
    return collect(conn, r)


def test_empty_source_is_reported_not_silently_ok(conn, tmp_path):
    res = collect_with(conn, make_dump(tmp_path / "reports_nov1_2026.tar.gz", []))
    assert (res.complete, res.inserted, res.anomalies) == (True, 0, ["source_empty"])


def test_duplicate_reports_are_stored_once(conn, tmp_path):
    reps = dump_records()
    res = collect_with(conn, make_dump(tmp_path / "reports_nov1_2026.tar.gz", reps + reps[:5]))
    assert (res.read, res.inserted, count(conn, "source_item")) == (42, 37, 37)


def test_corrupt_dump_fails_without_moving_checkpoint(conn, tmp_path):
    good = make_dump(tmp_path / "g.tar.gz", dump_records() * 30).read_bytes()
    bad = tmp_path / "reports_nov1_2026.tar.gz"
    bad.write_bytes(good[: len(good) // 3])
    code, out = runner.daily_run(TARGET, reader_factory=lambda name: reader_for(bad, batch_size=100000))
    assert code == runner.EXIT_FATAL and out["error_type"] == "source_corrupt" and out["failed_job"] == "collect"
    assert source_item.get_checkpoint(conn, "protondb") is None and count(conn, "source_item") == 0


def test_items_missing_from_the_next_dump_are_deleted(conn, tmp_path):
    reps = dump_records()
    collect_with(conn, make_dump(tmp_path / "reports_oct1_2026.tar.gz", reps))
    from game_signal_scout.services.normalize import normalize
    normalize(conn)
    res = collect_with(conn, make_dump(tmp_path / "reports_nov1_2026.tar.gz", reps[2:]))   # 新しい月に 2 件が消えた
    assert (res.inserted, res.deleted, res.anomalies) == (0, 2, [])
    assert (count(conn, "source_item"), count(conn, "player_report")) == (35, 35)            # 正規化した行も一緒に消える


def test_suspiciously_small_dump_does_not_delete(conn, tmp_path):
    reps = dump_records()
    collect_with(conn, make_dump(tmp_path / "reports_oct1_2026.tar.gz", reps))
    res = collect_with(conn, make_dump(tmp_path / "reports_nov1_2026.tar.gz", reps[:3]))
    assert (res.deleted, res.anomalies) == (0, ["snapshot_too_small"]) and count(conn, "source_item") == 37


def test_retention_purges_old_items(conn, tmp_path):
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", dump_records())
    collect_with(conn, path)
    conn.execute("UPDATE source_item SET received_at = now() - interval '40 days' WHERE item_id IN (SELECT item_id FROM source_item LIMIT 7)")
    conn.commit()
    res = collect_with(conn, path, retention_days=30)
    assert res.purged == 7 and count(conn, "source_item") == 30


def test_edited_items_are_replaced_and_renormalized(conn, tmp_path):
    from game_signal_scout.services.collect import collect
    from test_steam_reviews import FakeHttp, reader as steam_reader, review
    collect(conn, steam_reader(FakeHttp({(10, "*"): {"response": {"reviews": [review(1, 100), review(2, 100)], "cursor": "*"}}})))
    conn.execute("INSERT INTO player_report (source, item_id, at, failed, config_hash) SELECT source, item_id, occurred_at, false, '-' FROM source_item")
    conn.commit()
    res = collect(conn, steam_reader(FakeHttp({(10, "*"): {"response": {"reviews": [review(1, 100, updated=200, text="fixed now"), review(2, 100)],
                                                                         "cursor": "*"}}})))
    assert (res.inserted, res.updated) == (0, 1)
    assert conn.execute("SELECT payload->>'review' FROM source_item WHERE item_id='1'").fetchone()[0] == "fixed now"
    assert [r[0] for r in conn.execute("SELECT item_id FROM player_report")] == ["2"]          # 編集された項目は正規化をやり直す


def test_status_separates_collection_analysis_and_publication(conn, tmp_path, stub_screen_docs):
    from game_signal_scout.ops.status import status
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", dump_records())
    runner.daily_run(TARGET, reader_factory=lambda name: reader_for(path))
    s = status(conn)
    assert s["jobs"]["collect"]["status"] == "ok" and s["jobs"]["collect"]["sources"]["protondb"]["inserted"] == 37
    assert s["sources"]["protondb"]["items"] == 37 and s["sources"]["protondb"]["cursor"]["complete"] is True
    assert s["analysis"]["events"] == {"fail": 1} and s["publication"]["external"] == "none"
    assert s["publication"]["documents"] >= 2 and s["publication"]["stale"] is False   # overview と作品 A（と Anime の流用の文書）


def test_recent_success_skips_fetching_until_interval(conn, tmp_path):
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", dump_records())
    runner.daily_run(TARGET, only=["collect"], reader_factory=lambda name: reader_for(path))
    code, out = runner.daily_run(TARGET, only=["collect"], reader_factory=lambda name: reader_for(path))
    assert code == runner.EXIT_OK and out["jobs"][0]["detail"]["protondb"]["skipped"] == "interval"
    conn.execute("UPDATE source_state SET last_ok_at = now() - interval '25 hours'")
    conn.commit()
    code, out = runner.daily_run(TARGET, only=["collect"], reader_factory=lambda name: reader_for(path))
    assert "skipped" not in out["jobs"][0]["detail"]["protondb"]


def test_one_failing_source_does_not_stop_the_others(conn, tmp_path, monkeypatch):
    good = make_dump(tmp_path / "reports_nov1_2026.tar.gz", dump_records())
    cfg = {n: {"adapter": "game_signal_scout.sources.protondb:ProtonDBDump", "min_interval_hours": 0} for n in ("protondb", "mirror")}
    monkeypatch.setattr(factory, "load_sources_config", lambda: cfg)

    class Log:
        def __init__(self, name):
            self.log = [{"ts": datetime.now(timezone.utc), "source": name, "host": "example.invalid", "endpoint": "/", "status": 200, "ok": True}]

    def make(name):
        r = reader_for(good, fail_after=1 if name == "protondb" else None)
        r.name, r.http = name, Log(name)
        return r
    code, out = runner.daily_run(TARGET, only=["collect"], reader_factory=make)
    assert code == runner.EXIT_OK                                                       # 一部の取得元の失敗では段を失敗にしない（残りで進む。全 Issue 共通の原則）
    states = {s: (ok is not None, et) for s, ok, et in conn.execute("SELECT source, last_ok_at, last_error_type FROM source_state")}
    assert states == {"protondb": (False, "network"), "mirror": (True, None)}          # 失敗した取得元の後も、次の取得元を集めた
    assert count(conn, "source_item") == 4 + 37                                          # 失敗した側は保存済みの 1 束（4 件）だけ
    detail = conn.execute("SELECT detail FROM job_run WHERE job='collect'").fetchone()[0]
    assert detail["protondb"]["error_type"] == "network" and detail["mirror"]["inserted"] == 37
    assert count(conn, "source_fetch") == 2                                               # 通信の記録を取得元ごとに保存


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
