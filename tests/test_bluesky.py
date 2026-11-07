"""Bluesky の取得元（Anime の tests/test_bluesky_stream・test_bluesky_adapter を移植し、文脈の語をゲームに替えた）。
投稿・投稿者はすべて架空。偽の websocket だけを使い、ネットワークには出ない。"""
from __future__ import annotations

import json

import pytest

from game_signal_scout.discovery.text import MalformedRecordError, extract_post_text
from game_signal_scout.services.identify import TitleIndex, identify
from game_signal_scout.sources import bluesky as bs
from game_signal_scout.sources.bluesky import GameContext, Stream, parse_frame

A = "at://did:plc:alice/app.bsky.feed.post/"
WORDS = ["game", "play", "patch", "steam", "ゲーム"]


def frame(seq, kind="commit", did="did:plc:alice", op="create", rkey="r1", text="", link=None, link_uri="https://example.com",
          collection="app.bsky.feed.post", account=None, when="2026-09-29T00:00:00Z"):
    p = {"$type": f"network.bsky.jetstream.subscribeEvents#{kind}", "seq": seq, "did": did, "time": when}
    if kind == "commit":
        p.update(operation=op, collection=collection, rkey=rkey, rev="x")
        if op != "delete":
            rec = {"$type": collection, "text": text, "createdAt": "2026-09-29T00:00:00Z", "langs": ["en"]}
            if link:
                rec["embed"] = {"$type": "app.bsky.embed.external", "external": {"uri": link_uri, "title": link}}
            p.update(cid=f"cid{seq}", record=rec)
    elif kind == "account":
        p["account"] = account or {"active": False, "status": "deleted"}
    return json.dumps({"$type": "message", "payload": p})


@pytest.fixture
def proc():
    return Stream(GameContext(WORDS))


@pytest.fixture
def feed(proc):
    def _feed(*frames, now=1_000_000.0):
        return [proc.handle(parse_frame(f), now) for f in frames]
    return _feed


@pytest.fixture(autouse=True)
def author_key():
    from game_signal_scout import actor_key
    actor_key.create_key()


# --- 1 周期の受信（Anime の test_bluesky_stream と同じ振る舞い） ---

def test_only_game_context_or_steam_link_is_stored(proc, feed):
    assert feed(frame(1, text="今日は天気がいい"), frame(2, rkey="b", text="new patch broke the game"),
                frame(3, rkey="c", text="look", link="Some Page", link_uri="https://store.steampowered.com/app/2246340/X/")) == \
        ["unmatched", "buffered", "buffered"]
    assert proc.rows[f"{A}c"]["steam_appids"] == ["2246340"]
    assert proc.rows[f"{A}b"]["steam_appids"] == []


def test_duplicate_seq_is_suppressed_and_resume_skips_inclusive_event(proc, feed):
    f = frame(10, text="game night")
    assert feed(f, f) == ["buffered", "duplicate"]
    assert feed(frame(9, rkey="old", text="game")) == ["duplicate"]
    p2 = Stream(GameContext(WORDS), last_seq=10)
    r = [p2.handle(parse_frame(frame(s, rkey=f"r{s}", text="game")), 2.0) for s in (10, 11)]
    assert r == ["duplicate", "buffered"] and p2.last_seq == 11


def test_delete_update_and_unmatched_update_are_gone(proc, feed):
    feed(frame(1, rkey="a", text="game night"))
    feed(frame(2, op="update", rkey="a", text="game night, boss fight"))
    assert "boss" in proc.rows[f"{A}a"]["text"]
    assert feed(frame(3, op="update", rkey="a", text="just dinner")) == ["unmatched"]
    feed(frame(4, rkey="b", text="play"), frame(5, op="delete", rkey="b"))
    assert proc.rows == {} and proc.gone == [(f"{A}a", "update_unmatched"), (f"{A}b", "deleted")]


def test_account_gone_drops_earlier_posts_and_ignores_posts_while_inactive(proc, feed):
    feed(frame(1, rkey="a", text="game"), frame(2, did="did:plc:bob", rkey="c", text="game"))
    feed(frame(3, kind="account", account={"active": False, "status": "takendown"}))
    assert set(proc.rows) == {"at://did:plc:bob/app.bsky.feed.post/c"} and proc.actors_gone == [("did:plc:alice", "account_takendown")]
    assert feed(frame(4, rkey="b", text="game")) == ["inactive_account"]
    feed(frame(5, kind="account", account={"active": True}, when="2026-09-29T00:05:00Z"), frame(6, rkey="d", text="game"))
    assert f"{A}d" in proc.rows


def test_malformed_record_is_skipped_and_program_errors_are_not(proc, feed):
    raw = json.dumps({"$type": "message", "payload": {"$type": "x#commit", "seq": 1, "did": "did:plc:alice", "time": "2026-10-04T15:13:48Z",
                                                     "operation": "create", "collection": "app.bsky.feed.post", "rkey": "m", "cid": "c",
                                                     "record": ["not", "a", "record"]}})
    assert feed(raw, frame(2, rkey="ok", text="game")) == ["malformed", "buffered"] and proc.last_seq == 2
    with pytest.raises(MalformedRecordError):
        extract_post_text({"text": 123})

    class Boom:
        def match(self, pt, link):
            raise ValueError("bug")
    proc.context = Boom()
    with pytest.raises(ValueError):
        feed(frame(3, rkey="p", text="game"))


def test_promo_stream_and_link_only_are_flagged_not_dropped(proc, feed):
    feed(frame(1, rkey="a", text="live now playing the game twitch.tv/x"), frame(2, rkey="b", text="Game Title", link="Game Title"),
         frame(3, rkey="c", text="great game #ad amzn.to/x"), frame(4, rkey="d", text="Download game v1.2 Switch NSP/XCI ROMs"),
         frame(5, rkey="e", text="Now playing on Radio: Song! Tune in now"))
    assert "stream" in proc.rows[f"{A}a"]["flags"] and "link_only" in proc.rows[f"{A}b"]["flags"] and "affiliate" in proc.rows[f"{A}c"]["flags"]
    assert "piracy" in proc.rows[f"{A}d"]["flags"]
    assert f"{A}e" not in proc.rows or "autopost" in proc.rows[f"{A}e"]["flags"]


# --- 接続の切り替えと再開位置（Anime の test_bluesky_adapter と同じ振る舞い） ---

class FakeWS:
    def __init__(self, frames):
        self.frames = list(frames)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def recv(self, timeout=None):
        if not self.frames:
            raise TimeoutError
        return self.frames.pop(0)


def adapter(monkeypatch, connect, endpoints=("wss://fake.invalid/a", "wss://fake.invalid/b")):
    ad = bs.Bluesky({"endpoints": list(endpoints), "batch_seconds": 5, "idle_seconds": 0.05, "context_words": WORDS}, None)
    monkeypatch.setattr(ad, "_connect", connect)
    return ad


def one(ad, cursor):
    return next(iter(ad.read(cursor)))


def test_cursor_too_old_switches_to_time_on_the_other_endpoint(monkeypatch):
    calls = []

    class Http400(Exception):
        def __init__(self):
            super().__init__("http")
            self.response = type("R", (), {"status_code": 400})()

    def connect(url):
        calls.append(url)
        if "/a" in url and "cursor=5" in url:
            raise Http400()
        return FakeWS([frame(9, rkey="z", text="game")])
    ad = adapter(monkeypatch, connect)
    b = one(ad, {"endpoint": "wss://fake.invalid/a", "last_seq": 5, "last_time_us": 1_700_000_000_000_000})
    assert len(b.items) == 1 and "cursor=5" in calls[0] and "cursor=5" not in calls[1]
    assert [r["ok"] for r in ad.log] == [False, True] and ad.log[0]["source"] == "bluesky"


def test_seq_from_another_instance_recovers_by_time(monkeypatch):
    calls = []

    def connect(url):
        calls.append(url)
        return FakeWS([frame(100, rkey="z", text="game")])
    b = one(adapter(monkeypatch, connect), {"endpoint": "wss://fake.invalid/a", "last_seq": 27_000, "last_time_us": 1_700_000_000_000_000})
    assert "/b" in calls[1] and "cursor=1699999940000000" in calls[1]
    assert [i.item_id for i in b.items] == [f"{A}z"] and b.cursor["endpoint"] == "wss://fake.invalid/b" and b.cursor["last_seq"] == 100


def test_one_endpoint_recovers_on_the_next_run(monkeypatch):
    ad = adapter(monkeypatch, lambda url: FakeWS([frame(100, rkey="z", text="game")]), endpoints=("wss://fake.invalid/a",))
    b = one(ad, {"endpoint": "wss://fake.invalid/a", "last_seq": 27_000, "last_time_us": 1_700_000_000_000_000})
    assert b.items == [] and b.cursor["force_time"] is True
    b = one(ad, b.cursor)
    assert len(b.items) == 1 and b.cursor["last_seq"] == 100 and "force_time" not in b.cursor


def test_all_endpoints_down_is_a_retryable_network_error(monkeypatch):
    from game_signal_scout.errors import classify

    def connect(url):
        raise OSError("接続できない")
    with pytest.raises(ConnectionError) as e:
        one(adapter(monkeypatch, connect), None)
    assert classify(e.value)[0] is True


def test_batch_carries_gone_and_author_hash_without_did(monkeypatch):
    ad = adapter(monkeypatch, lambda url: FakeWS([frame(1, rkey="a", text="game"), frame(2, rkey="b", text="play"), frame(3, op="delete", rkey="b"),
                                                  frame(4, did="did:plc:bob", kind="account")]))
    b = one(ad, None)
    assert [i.item_id for i in b.items] == [f"{A}a"] and b.gone == [f"{A}b"] and len(b.actors_gone) == 1
    assert "did:plc" not in json.dumps(b.items[0].payload) and len(b.items[0].payload["author"]) == 20


# --- 作品の同定（Game 固有。2026-11-07 の実データの誤同定を受けた規則） ---

def index():
    return TitleIndex([("2246340", "Monster Hunter Wilds"), ("252490", "Rust"), ("2", "Hades II"), ("4", "The Ball"), ("5", "Sweet Home")],
                      ["Sweet Home"], ["game", "steam", "ゲーム"], 8)


def test_identify_steam_link_first_then_longest_cased_title_with_game_context():
    ix = index()
    assert identify({"steam_appids": ["2246340"], "text": "Hades II"}, ix) == ("2246340", "Monster Hunter Wilds", "steam_link")
    assert identify({"text": "Monster Hunter Wilds keeps crashing, worst game"}, ix) == ("2246340", "Monster Hunter Wilds", "title")
    assert identify({"text": "Hades II on steam is great"}, ix) == ("2", "Hades II", "title")


def test_title_match_rejects_generic_phrases_seen_in_real_posts():
    ix = index()
    assert identify({"text": "Monster Hunter Wilds tonight"}, ix) == (None, None, None)              # ゲームに固有の文脈の語がない
    assert identify({"text": "monster hunter wilds game"}, ix) == (None, None, None)                 # 大文字・小文字が題名と違う
    assert identify({"text": "Rust wipe day on steam"}, ix) == (None, None, None)                    # 1 語の題名は題名では同定しない
    assert identify({"text": "watching the ball game"}, ix) == (None, None, None)                    # 一般の語句（大文字・小文字が違う）
    assert identify({"text": "Sweet Home game set"}, ix) == (None, None, None)                       # 衝突する題名の一覧
    ix2 = TitleIndex([("9", "Puzzle Game")], [], ["game"], 8)
    assert identify({"text": "Solved today's Puzzle Game in 2 guesses"}, ix2) == (None, None, None)  # 題名の中の語は文脈に数えない
    assert identify({"text": "Puzzle Game is my favorite game"}, ix2) == ("9", "Puzzle Game", "title")
