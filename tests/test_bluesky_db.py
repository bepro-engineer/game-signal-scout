"""2 つの取得元（ProtonDB の報告・Bluesky の発言）を日次の 4 段で流す（一時の DB。Bluesky は偽の websocket）。
- 発言は player_post に正規化され、作品の辞書（ProtonDB の題名）か Steam のリンクで同定される
- 削除・アカウントの停止の event で、保存済みの発言が消える（正規化した行も）
- 発言の多い作品が Viewer の文書に出て、投稿者の HMAC・投稿の URI は出ない
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from conftest import make_dump, report
from test_bluesky import A, WORDS, FakeWS, frame
from game_signal_scout.ops import runner
from game_signal_scout.repositories import public_document
from game_signal_scout.sources import bluesky as bs, factory

T0 = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
DAY = 86400


@pytest.fixture
def run(conn, tmp_path, monkeypatch):
    from game_signal_scout import actor_key
    actor_key.create_key()
    recs = [report("2246340", T0 + i * DAY, False, i) for i in range(3)] + [report("252490", T0, False, 1)]
    for r in recs:
        r["app"]["title"] = {"2246340": "Monster Hunter Wilds", "252490": "Rust Console Edition"}[r["app"]["steam"]["appId"]]
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", recs)
    cfg = {"protondb": {"adapter": "game_signal_scout.sources.protondb:ProtonDBDump", "local_path": str(path),
                        "normalizer": "game_signal_scout.services.normalize:protondb"},
           "bluesky": {"adapter": "game_signal_scout.sources.bluesky:Bluesky", "normalizer": "game_signal_scout.services.normalize:bluesky",
                       "endpoints": ["wss://fake.invalid/a"], "batch_seconds": 5, "idle_seconds": 0.05, "context_words": WORDS,
                       "ambiguous_titles": ["Rust"]}}
    monkeypatch.setattr(factory, "load_sources_config", lambda: cfg)
    frames = [[]]

    def make(name):
        r = factory.create(name, None, cfg)
        if name == "bluesky":
            monkeypatch.setattr(r, "_connect", lambda url: FakeWS(frames[0]))
        return r

    def go(*f):
        frames[0] = list(f)
        code, out = runner.daily_run(date(2026, 10, 31), reader_factory=make)
        assert code == runner.EXIT_OK, out
        return out
    return go


def posts(conn):
    return conn.execute("SELECT item_id, appid, matched_by FROM player_post ORDER BY item_id").fetchall()


def test_two_sources_flow_to_normalized_posts_and_viewer_documents(run, conn):
    authors = [f"did:plc:u{i}" for i in range(6)]
    f = [frame(i + 1, did=d, rkey="a", text="Monster Hunter Wilds crashes after the patch, game is broken") for i, d in enumerate(authors)]
    f += [frame(10, rkey="b", text="Rust Console Edition on steam is fun"),
          frame(11, rkey="c", text="look", link="Store", link_uri="https://store.steampowered.com/app/999/X/"),
          frame(12, rkey="d", text="weather is nice")]
    out = run(*f)
    assert [j["job"] for j in out["jobs"]] == ["collect", "normalize", "analyze", "publish"]
    assert out["jobs"][1]["detail"] == {"protondb": 4, "bluesky": 8}
    got = posts(conn)
    assert [r for r in got if r[1] == "2246340"] and all(r[2] == "title" for r in got if r[1] == "2246340")
    assert (f"{A}b", "252490", "title") in got and (f"{A}c", "999", "steam_link") in got
    ov = public_document.get_document(conn, "overview")
    g = public_document.get_document(conn, "game/2246340")
    assert g["posts"]["authors"] == 6 and set(g["posts"]["recent"][0]) == {"at", "lang", "matched_by", "text"}
    assert public_document.get_document(conn, "game/999") is None                 # リンクだけの投稿（印 link_only）は数えない
    assert "did:plc" not in json.dumps(ov) + json.dumps(g)


def test_deleted_posts_and_gone_accounts_are_removed_with_their_normalized_rows(run, conn):
    run(frame(1, rkey="a", text="Monster Hunter Wilds game"), frame(2, did="did:plc:bob", rkey="b", text="Monster Hunter Wilds game"),
        frame(3, rkey="c", text="play"))
    assert len(posts(conn)) == 3
    run(frame(4, op="delete", rkey="c"), frame(5, did="did:plc:bob", kind="account"))
    assert [r[0] for r in posts(conn)] == [f"{A}a"]
    assert conn.execute("SELECT count(*) FROM source_item WHERE source='bluesky'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM source_fetch WHERE source='bluesky' AND ok").fetchone()[0] == 2
