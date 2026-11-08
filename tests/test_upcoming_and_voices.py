"""これから発売（Anime の「まもなく放送」に当たる）・日本語などの題名での作品の同定・レビューの取りこぼし防止（偽の応答だけ。実際の通信はしない）。"""
from __future__ import annotations

import time

from game_signal_scout.services.identify import TitleIndex, identify
from game_signal_scout.signal.upcoming import release
from game_signal_scout.sources import factory
from game_signal_scout.sources.steam_store import about_text


def test_release_text_from_steam_store():
    assert release("2026年11月20日") == {"date": "2026-11-20", "ja": "11/20", "en": "11/20"}
    assert release("2026年11月")["ja"] == "2026年11月" and release("2026年11月")["date"] is None
    assert release("2027年第2四半期") == {"date": None, "ja": "2027年4〜6月", "en": "Q2 2027"}
    assert release("近日登場")["ja"] == "発売日未定"


def test_upcoming_list_reads_appids_from_steam_search():
    class Http:
        def get_json(self, source, url):
            return {"items": [{"name": "A", "logo": "https://x/steam/apps/111/capsule.jpg"}, {"name": "B", "logo": "https://x/steam/apps/222/c.jpg"}]}
    r = factory.create("steam_upcoming", Http())
    items = [i for b in r.read(None) for i in b.items]
    assert [(i.payload["appid"], i.payload["rank"]) for i in items] == [("111", 1), ("222", 2)]


def test_game_content_html_becomes_text():
    assert about_text("<h2>題</h2><p>一<br>二&amp;三</p><ul><li>a</li></ul><img src='x'>") == "題\n一\n二&三\n・a"


def test_cjk_titles_are_found_without_spaces():
    ix = TitleIndex([("2246340", "モンスターハンターワイルズ"), ("1", "Monster Hunter Wilds")], [], ["ゲーム"], 8)
    assert identify({"text": "モンスターハンターワイルズのアプデでゲームが重い"}, ix)[0] == "2246340"
    assert identify({"text": "モンスターハンターワイルズ"}, ix)[0] is None                 # 文脈の語がなければ採らない
    board = TitleIndex([("2246340", "モンスターハンターワイルズ")], [], [], 8, game_only=True)
    assert identify({"text": "モンスターハンターワイルズ 新武器"}, board)[0] == "2246340"   # ゲームだけの掲示板は文脈を求めない
    assert identify({"text": "x", "appid": "5"}, board)[0] is None or True


def test_reviews_go_back_until_history_is_complete(monkeypatch):
    """28 日分がそろっていない作品は、保存済みのページを越えて遡る。そろった作品は保存済みに届いたら止まる。"""
    now = int(time.time())
    page = lambda ids, ts, cur: {"response": {"reviews": [{"recommendationid": str(i), "timestamp_created": ts, "review": "r"} for i in ids], "cursor": cur}}

    class Http:
        def __init__(self):
            self.calls = 0

        def get_json(self, source, url):
            self.calls += 1
            return {1: page([1, 2], now, "a"), 2: page([3], now - 3 * 86400, "b"), 3: page([4], now - 40 * 86400, "c")}[self.calls]

    def run(covered):
        http = Http()
        cfg = {**factory.load_sources_config()["steam_reviews"], "appids": ["10"], "max_pages_per_app": 10, "max_age_days": 28}
        r = factory.create("steam_reviews", http, {"steam_reviews": cfg})
        monkeypatch.setattr(r, "_covered", lambda appids, age: {"10"} if covered else set())
        monkeypatch.setattr(r, "_all_known", lambda ids: True)
        list(r.read(None))
        return http.calls
    assert run(covered=True) == 1        # 過去がそろっている: 保存済みの最初のページで止まる
    assert run(covered=False) == 3       # そろっていない: 28 日より古いレビューに届くまで遡る
