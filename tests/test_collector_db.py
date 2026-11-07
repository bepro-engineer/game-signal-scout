"""常駐の収集器（ops/collector。Anime の sources/runner.run の振る舞いを移植）。一時の DB と偽の websocket だけを使う。"""
from __future__ import annotations

from datetime import date

import pytest

from test_bluesky import A, WORDS, FakeWS, frame
from game_signal_scout.ops import collector, runner
from game_signal_scout.repositories import session
from game_signal_scout.sources import factory

CFG = {"bluesky": {"adapter": "game_signal_scout.sources.bluesky:Bluesky", "resident": True, "endpoints": ["wss://fake.invalid/a"],
                   "batch_seconds": 5, "idle_seconds": 0.05, "context_words": WORDS, "error_backoff_seconds": 2}}


@pytest.fixture
def reader(monkeypatch):
    from game_signal_scout import actor_key
    actor_key.create_key()
    monkeypatch.setattr(factory, "load_sources_config", lambda: CFG)
    feeds = [[frame(1, rkey="a", text="new patch broke the game")], [frame(2, rkey="b", text="steam deck game night"), frame(3, op="delete", rkey="a")]]
    r = factory.create("bluesky", None, CFG)
    monkeypatch.setattr(r, "_connect", lambda url: FakeWS(feeds.pop(0) if feeds else []))
    return r


def items(conn):
    return [x[0] for x in conn.execute("SELECT item_id FROM source_item WHERE source='bluesky' ORDER BY item_id")]


def test_cycles_save_resume_and_follow_deletes_with_heartbeat(reader, conn):
    assert collector.run("bluesky", max_cycles=2, reader=reader) == 0
    assert items(conn) == [f"{A}b"]
    assert conn.execute("SELECT cursor->>'last_seq' FROM source_checkpoint WHERE source='bluesky'").fetchone()[0] == "3"
    st = conn.execute("SELECT last_ok_at IS NOT NULL, last_error_type FROM source_state WHERE source='bluesky'").fetchone()
    assert st == (True, None)
    assert conn.execute("SELECT count(*) FROM source_fetch WHERE source='bluesky' AND ok").fetchone()[0] == 2
    assert collector.heartbeat_path("bluesky").exists()


def test_failed_cycle_is_recorded_and_the_next_cycle_runs(reader, conn, monkeypatch):
    calls = []

    def connect(url):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("接続できない")
        return FakeWS([frame(5, rkey="z", text="game")])
    monkeypatch.setattr(reader, "_connect", connect)
    slept = []
    assert collector.run("bluesky", max_cycles=2, reader=reader, sleep=slept.append) == 0
    assert items(conn) == [f"{A}z"] and len(slept) == 2
    assert conn.execute("SELECT count(*) FROM source_fetch WHERE source='bluesky' AND NOT ok").fetchone()[0] == 1


def test_second_process_exits_75_and_disabled_source_exits_0(reader, conn, test_db):
    from game_signal_scout import db
    other = db.connect(test_db["dsn"], autocommit=True)
    assert session.try_advisory_lock(other, "collect:source:bluesky")
    try:
        assert collector.run("bluesky", once=True, reader=reader) == collector.EXIT_LOCKED
    finally:
        other.close()
    assert collector.run("protondb", once=True) == collector.EXIT_DISABLED
    assert items(conn) == []


def test_daily_collect_does_not_read_resident_sources(reader, conn):
    assert factory.sources(CFG) == [] and collector.residents(CFG) == ["bluesky"]
    code, out = runner.daily_run(date(2026, 10, 31), only=["collect"], reader_factory=lambda n: pytest.fail(f"読んではいけない: {n}"))
    assert code == runner.EXIT_OK and out["jobs"][0]["detail"] == {}
