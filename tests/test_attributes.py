"""作品の属性（#2）: 日本語の UI・字幕・音声と、開発元・開発元の国・地域を、取得元ごとに出典つきで持つ。推定しない。"""
from datetime import datetime, timezone

from game_signal_scout.sources.steam_attributes import JAPANESE, SteamAttributes
from game_signal_scout.sources.wikidata_works import WikidataWorks

T = datetime(2026, 11, 8, tzinfo=timezone.utc)


class Http:
    def __init__(self, body):
        self.body, self.urls = body, []

    def get_json(self, source, url):
        self.urls.append(url)
        return self.body


def test_steam_languages_keep_ui_subtitles_and_audio_apart_and_missing_japanese_is_not_listed():
    body = {"response": {"store_items": [
        {"appid": 1, "supported_languages": [{"elanguage": 0, "supported": True}, {"elanguage": JAPANESE, "supported": True, "subtitles": True, "full_audio": False}],
         "basic_info": {"developers": [{"name": "Dev A"}], "publishers": [{"name": "Pub B"}]}},
        {"appid": 2, "supported_languages": [{"elanguage": 0, "supported": True}]},
        {"appid": 3}]}}   # 言語の情報のない作品は属性を作らない（画面は未確認）
    r = SteamAttributes({"appids": ["1", "2", "3"]}, Http(body))
    r.name = "steam_attributes"
    items = [i for b in r.read(None) for i in b.items]
    assert [i.item_id for i in items] == ["1", "2"]
    rows = {(a, k): v for i in items for a, k, v in SteamAttributes.attributes(i.item_id, T, i.payload)}
    assert rows[("1", "ja")] == {"listed": True, "ui": True, "subtitles": True, "audio": False}
    assert rows[("2", "ja")] == {"listed": False, "ui": False, "subtitles": False, "audio": False}
    assert rows[("1", "developers")] == ["Dev A"] and ("2", "developers") not in rows


def test_wikidata_countries_are_taken_as_written_and_unknown_is_left_empty():
    b = lambda app, dev=None, label=None, country=None: {"app": {"value": app}, "game": {"value": f"http://www.wikidata.org/entity/Q{app}"},
                                                         **({"dev": {"value": f"http://www.wikidata.org/entity/{dev}"}, "devLabel": {"value": label}} if dev else {}),
                                                         **({"countryLabel": {"value": country}} if country else {})}
    body = {"results": {"bindings": [b("10", "Q1", "スタジオ甲", "日本"), b("10", "Q2", "Studio B", "ポーランド"), b("10", "Q2", "Studio B", "カナダ"),
                                     b("20", "Q3", "Studio C"), b("30")]}}
    r = WikidataWorks({"appids": ["10", "20", "30", "40"]}, Http(body))
    r.name = "wikidata_works"
    items = {i.item_id: i for b_ in r.read(None) for i in b_.items}
    assert set(items) == {"10", "20", "30", "40"} and items["40"].payload.get("no_attributes")
    got = {i: WikidataWorks.attributes(i, T, items[i].payload) for i in items}
    dc = dict((k, v) for _, k, v in got["10"])["developer_countries"]
    assert [(d["developer"], d["countries"]) for d in dc] == [("スタジオ甲", ["日本"]), ("Studio B", ["ポーランド", "カナダ"])]
    assert dict((k, v) for _, k, v in got["20"])["developer_countries"][0]["countries"] == []   # 国の記載がなければ空（推定しない）
    assert got["30"] == [] and got["40"] == []


def test_screen_values_keep_unknown_apart_and_never_show_ids_as_names():
    from game_signal_scout.ops.work_display import work_attrs
    assert work_attrs({}) == {"jp": None, "dev": []}                                    # 属性がない = 未確認（非対応と混ぜない）
    a = {"ja": [{"source": "s1", "value": {"listed": False, "ui": False, "subtitles": False, "audio": False}, "fetched_at": "2026-11-08T00:00:00+00:00"}],
         "developers": [{"source": "s1", "value": ["Studio Z"], "fetched_at": "x"}],
         "developer_countries": [{"source": "s2", "value": [{"developer": "Q123", "countries": ["日本"]}], "fetched_at": "x"}]}
    got = work_attrs(a)
    assert got["jp"] == {"ui": False, "sub": False, "voice": False} and got["jp_at"] == "2026-11-08"
    assert got["dev"] == [{"n": "Studio Z", "c": None}]                                  # 名前のない記載は使わず、国は未確認のまま（推定しない）


def test_scene_images_keep_store_order_and_only_all_ages():
    """場面の画像は、年齢の制限のない場面だけを配信元の順に、上限まで（画像は複製せず URL だけ）。"""
    from game_signal_scout.sources import steam_assets
    xs = {"all_ages_screenshots": [{"filename": f"steam/apps/1/s{i}.jpg", "ordinal": 10 - i} for i in range(12)],
          "mature_content_screenshots": [{"filename": "steam/apps/1/m.jpg", "ordinal": 0}]}
    got = steam_assets.shot_urls(xs)
    assert len(got) == steam_assets.MAX_SHOTS and got[0].endswith("s11.jpg") and not any("m.jpg" in u for u in got)
    assert steam_assets.shot_urls({}) == []
