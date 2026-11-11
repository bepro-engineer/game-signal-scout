"""2 つの取得元（ProtonDB の報告・Bluesky の発言）を日次の 4 段で流す（一時の DB。Bluesky は偽の websocket）。
- 発言は player_post に正規化され、作品の辞書（ProtonDB の題名）か Steam のリンクで同定される
- 削除・アカウントの停止の event で、保存済みの発言が消える（正規化した行も）
- 発言の多い作品が Viewer の文書に出て、投稿者の HMAC・投稿の URI は出ない
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from conftest import KS, known_works, make_dump, report
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
    # 作品の辞書は作品の情報（game_profile）だけから作る（観測の取得元の表は読まない。#3 G3）
    from game_signal_scout.repositories import catalog
    at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    works = (("2246340", "Monster Hunter Wilds"), ("252490", "Rust Console Edition"))
    for a, _ in works:
        conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES ('works', %s, %s, %s, '{}')", (a, at, at))
    catalog.upsert(conn, [{"work_id": a, "source": "works", "item_id": a, "title": t, "genres": [], "modes": [], "platforms": [], "fetched_at": at} for a, t in works])
    conn.commit()
    cfg = {"protondb": {"adapter": "game_signal_scout.sources.protondb:ProtonDBDump", "local_path": str(path),
                        "normalizer": "game_signal_scout.services.normalize:reports", "work_keyspace": KS, "work_link": r"store\.steampowered\.com/app/(\d{1,10})"},
           "bluesky": {"adapter": "game_signal_scout.sources.bluesky:Bluesky", "normalizer": "game_signal_scout.services.normalize:voices", "work_keyspace": KS,
                       "endpoints": ["wss://fake.invalid/a"], "batch_seconds": 5, "idle_seconds": 0.05, "context_words": WORDS,
                       "ambiguous_titles": ["Rust"]}}
    monkeypatch.setattr(factory, "load_sources_config", lambda: cfg)
    known_works(conn, [a for a, _ in works] + sorted({r["app"]["steam"]["appId"] for r in recs}))   # 移行の前からある作品（番号はそのまま）
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
    return conn.execute("SELECT item_id, work_id, matched_by FROM player_post ORDER BY item_id").fetchall()


def test_two_sources_flow_to_normalized_posts_and_viewer_documents(run, conn, stub_screen_docs):
    authors = [f"did:plc:u{i}" for i in range(6)]
    f = [frame(i + 1, did=d, rkey="a", text="Monster Hunter Wilds crashes after the patch, game is broken") for i, d in enumerate(authors)]
    f += [frame(10, rkey="b", text="Rust Console Edition on steam is fun"),
          frame(11, rkey="c", text="look", link="Store", link_uri="https://store.steampowered.com/app/999/X/"),
          frame(12, rkey="d", text="weather is nice")]
    out = run(*f)
    assert [j["job"] for j in out["jobs"]] == ["collect", "normalize", "observe", "analyze", "insight", "digest", "publish"]
    assert out["jobs"][1]["detail"] == {"protondb": 4, "bluesky": 8}
    got = posts(conn)
    assert [r for r in got if r[1] == "2246340"] and all(r[2] == "title" for r in got if r[1] == "2246340")
    new = conn.execute("SELECT work_id FROM game_work_key WHERE keyspace = %s AND ext_id = '999'", (KS,)).fetchone()[0]   # 知らない作品のページ: 新しい作品
    assert int(new) >= 1_000_000_000
    assert (f"{A}b", "252490", "title") in got and (f"{A}c", new, "link") in got
    assert len({r[0] for r in got if r[1] == "2246340"}) == 6                    # 6 人の発言が同じ作品に結び付く
    assert public_document.get_document(conn, "overview") is None and public_document.get_document(conn, "game/2246340") is None   # 古い文書は作らない（#3 2026-11-11）
    assert "did:plc" not in json.dumps([r[0] for r in conn.execute("SELECT path FROM public_document").fetchall()])


def test_deleted_posts_and_gone_accounts_are_removed_with_their_normalized_rows(run, conn, stub_screen_docs):
    run(frame(1, rkey="a", text="Monster Hunter Wilds game"), frame(2, did="did:plc:bob", rkey="b", text="Monster Hunter Wilds game"),
        frame(3, rkey="c", text="play"))
    assert len(posts(conn)) == 3
    run(frame(4, op="delete", rkey="c"), frame(5, did="did:plc:bob", kind="account"))
    assert [r[0] for r in posts(conn)] == [f"{A}a"]
    assert conn.execute("SELECT count(*) FROM source_item WHERE source='bluesky'").fetchone()[0] == 1
    # 削除の事実は残す（Anime の §2）: 消えた投稿 1 件と消えたアカウント 1 件。本文・名前は持たない
    assert sorted(k for (k,) in conn.execute("SELECT kind FROM source_gone WHERE source='bluesky'")) == ["author", "item"]
    assert conn.execute("SELECT count(*) FROM source_fetch WHERE source='bluesky' AND ok").fetchone()[0] == 2
