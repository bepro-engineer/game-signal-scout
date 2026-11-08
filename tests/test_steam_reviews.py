"""Steam のレビューの取得元: 固定の偽の応答だけで確かめる（実際の API には接続しない）。"""
from __future__ import annotations

import json
import urllib.parse

import pytest

from game_signal_scout.errors import RetryableError, classify
from game_signal_scout.sources import factory
from game_signal_scout.sources.contract import SourceCorruptError, SourceNotConfiguredError


def review(rid, created, updated=None, text="crashes after the update"):
    return {"recommendationid": str(rid), "author": {"steamid": "76561190000000000", "playtime_at_review": 120}, "language": "english",
            "review": text, "timestamp_created": created, "timestamp_updated": updated or created, "voted_up": False}


class FakeHttp:
    """URL の input_json の cursor ごとに、決めた応答を返す。呼び出しを記録する。"""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get_json(self, source, url):
        q = json.loads(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["input_json"][0])
        self.calls.append(q)
        return self.pages.get((q["appid"], q["cursor"]))


def reader(http, **kw):
    cfg = factory.load_sources_config()
    return factory.create("steam_reviews", http, {"steam_reviews": {**cfg["steam_reviews"], "appids": ["10"], "max_pages_per_app": 3, **kw}})


def test_enabled_for_daily_collect():
    """2026-11-08 から日次で読む（Issue #2 の本人の指示を受けた判断。止めるときは enabled = false）。"""
    assert factory.load_sources_config()["steam_reviews"]["enabled"] is True
    assert "steam_reviews" in factory.sources()


def test_pages_with_cursor_and_stops_when_cursor_repeats():
    http = FakeHttp({(10, "*"): {"response": {"reviews": [review(1, 100), review(2, 101)], "cursor": "c1"}},
                     (10, "c1"): {"response": {"reviews": [review(3, 102)], "cursor": "c1"}}})
    batches = list(reader(http).read(None))
    assert [i.item_id for b in batches for i in b.items] == ["1", "2", "3"]
    assert batches[-1].cursor == {"10": {"cursor": "c1", "done": True}, "complete": True}
    assert [c["cursor"] for c in http.calls] == ["*", "c1"]
    assert http.calls[0]["filter"] == 1 and http.calls[0]["languages"] == ["all"]


def test_does_not_keep_the_author_id_and_uses_update_time_as_version():
    http = FakeHttp({(10, "*"): {"reviews": [review(1, 100, updated=150)], "cursor": "*"}})   # 旧来の直下の形も読む
    item = list(reader(http).read(None))[0].items[0]
    assert "author" not in item.payload and "76561190000000000" not in json.dumps(item.payload)
    assert item.payload["playtime_at_review"] == 120 and item.version == "150"


def test_resumes_from_saved_cursor_and_skips_finished_apps():
    http = FakeHttp({(10, "c1"): {"response": {"reviews": [review(3, 102)], "cursor": "c2"}}, (10, "c2"): {"response": {"reviews": [], "cursor": "c2"}},
                     (20, "*"): {"response": {"reviews": [], "cursor": "*"}}})
    r = reader(http, appids=["10", "20", "30"])
    batches = list(r.read({"10": {"cursor": "c1", "done": False}, "30": {"cursor": "x", "done": True}}))
    assert [i.item_id for b in batches for i in b.items] == ["3"]
    assert {(c["appid"], c["cursor"]) for c in http.calls} == {(10, "c1"), (10, "c2"), (20, "*")}
    assert batches[-1].cursor["complete"] is True
    http.calls.clear()
    http.pages[(10, "*")] = {"response": {"reviews": [], "cursor": "*"}}
    http.pages[(30, "*")] = {"response": {"reviews": [], "cursor": "*"}}
    list(r.read(batches[-1].cursor))                                          # 一巡を終えた次は最初から
    assert {(c["appid"], c["cursor"]) for c in http.calls} == {(10, "*"), (20, "*"), (30, "*")}


def test_errors_are_classified():
    with pytest.raises(RetryableError):
        list(reader(FakeHttp({})).read(None))                                 # 応答なし → 一時的な失敗
    with pytest.raises(SourceCorruptError) as e:
        list(reader(FakeHttp({(10, "*"): {"response": {"reviews": "x"}}})).read(None))
    assert classify(e.value) == (False, "source_corrupt")
    with pytest.raises(SourceNotConfiguredError):
        list(reader(FakeHttp({}), appids=[]).read(None))
