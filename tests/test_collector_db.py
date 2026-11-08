"""常駐の収集器（ops/collector。Anime の sources/runner.run の移植）。一時の DB と、試験の中だけの取得元を使う（どの取得元も同じ形）。"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from game_signal_scout.ops import collector, runner
from game_signal_scout.repositories import session
from game_signal_scout.sources import factory
from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

CFG = {"src_x": {"adapter": "test_collector_db:Fake", "resident": True, "poll_seconds": 0, "error_backoff_seconds": 1}}


class Fake(SourceReader):
    calls = 0

    def read(self, cursor):
        Fake.calls += 1
        n = Fake.calls
        if n == 2 and self.settings.get("fail_second"):
            raise ConnectionError("止まった（試験）")
        yield Batch([SourceItem(self.name, f"i{n}", datetime.now(timezone.utc), {"text": "t", "author": "a"})], {"n": n})


@pytest.fixture
def reader(monkeypatch):
    Fake.calls = 0
    monkeypatch.setattr(factory, "load_sources_config", lambda: CFG)
    return factory.create("src_x", None, CFG)


def items(conn):
    return [x[0] for x in conn.execute("SELECT item_id FROM source_item WHERE source='src_x' ORDER BY item_id")]


def test_cycles_save_resume_and_write_heartbeat(reader, conn):
    assert collector.run("src_x", max_cycles=2, reader=reader, sleep=lambda s: None) == 0
    assert items(conn) == ["i1", "i2"]
    assert conn.execute("SELECT cursor->>'n' FROM source_checkpoint WHERE source='src_x'").fetchone()[0] == "2"
    assert conn.execute("SELECT last_ok_at IS NOT NULL, last_error_type FROM source_state WHERE source='src_x'").fetchone() == (True, None)
    assert collector.heartbeat_path("src_x").exists()


def test_failed_cycle_is_recorded_and_the_next_cycle_runs(reader, conn):
    reader.settings["fail_second"] = True
    slept = []
    assert collector.run("src_x", max_cycles=3, reader=reader, sleep=slept.append) == 0
    assert items(conn) == ["i1", "i3"] and len(slept) == 1 + 0                       # 失敗の後は error_backoff_seconds だけ待つ（poll_seconds = 0）


def test_locked_cycle_is_skipped_and_disabled_source_exits_0(reader, conn, test_db):
    from game_signal_scout import db
    other = db.connect(test_db["dsn"], autocommit=True)
    assert session.try_advisory_lock(other, "collect:source:src_x")
    try:
        assert collector.run("src_x", once=True, reader=reader) == 0 and items(conn) == []
    finally:
        other.close()
    assert collector.run("protondb", once=True) == collector.EXIT_DISABLED


def test_daily_collect_does_not_read_resident_sources(reader, conn):
    assert factory.sources(CFG) == [] and collector.residents(CFG) == ["src_x"]
    code, out = runner.daily_run(date(2026, 10, 31), only=["collect"], reader_factory=lambda n: pytest.fail(f"読んではいけない: {n}"))
    assert code == runner.EXIT_OK and out["jobs"][0]["detail"] == {}
