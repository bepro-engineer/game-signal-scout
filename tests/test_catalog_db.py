"""作品の情報（steam_store → game_profile）と遊ばれている規模（steam_charts → game_activity）を、日次の段で流す（一時の DB・偽の応答）。
- 取得元は記述（config/sources.toml の形）と Factory だけで足す。収集・正規化・公開の共通の処理は取得元の名前で分けない
- 作品の情報は「プレイヤーの報告・発言・遊ばれている規模の多い作品」だけを取りに行き、取った作品は次の回に取り直さない
- 作品のカード・「ゲームを探す」の絞り込み・作品の文書に、画像・遊び方・日本語・機種・順位が出る
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from conftest import make_dump, report
from game_signal_scout.ops import runner
from game_signal_scout.repositories import public_document
from game_signal_scout.sources import factory

T0 = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())


class FakeHttp:
    """偽の通信（URL ごとの JSON）。呼ばれた URL を残す。"""

    def __init__(self, table):
        self.table, self.calls, self.log = table, [], []

    def get_json(self, source, url):
        self.calls.append(url)
        for key, body in self.table.items():
            if key in url:
                return body
        return None


def details(appid, name, cats=(2, 9), ja=True, kind="game"):
    langs = "英語<strong>*</strong>, 日本語<strong>*</strong>" if ja else "英語"
    return {str(appid): {"success": True, "data": {"type": kind, "name": name, "short_description": f"{name} の説明",
                                                   "header_image": f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg",
                                                   "genres": [{"description": "アクション"}], "categories": [{"id": c, "description": str(c)} for c in cats],
                                                   "platforms": {"windows": True, "mac": False, "linux": True}, "release_date": {"date": "2025年2月27日"},
                                                   "supported_languages": langs,
                                                   "about_the_game": f"<h2>{name}</h2><p>狩りに出よう。<br><img src='x.jpg'>仲間と&amp;一人で。</p>"}}}


@pytest.fixture
def run(conn, tmp_path, monkeypatch):
    recs = [report("2246340", T0 + i * 3600, False, i) for i in range(8)]
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", recs)
    cfg = {"protondb": {"adapter": "game_signal_scout.sources.protondb:ProtonDBDump", "local_path": str(path),
                        "normalizer": "game_signal_scout.services.normalize:reports"},
           "steam_charts": {"adapter": "game_signal_scout.sources.steam_charts:SteamCharts", "normalizer": "game_signal_scout.services.normalize:activity"},
           "steam_store": {"adapter": "game_signal_scout.sources.steam_store:SteamStore", "normalizer": "game_signal_scout.services.normalize:profiles",
                           "active_days": 100000, "max_games": 10, "refresh_days": 30, "batch_size": 1}}
    monkeypatch.setattr(factory, "load_sources_config", lambda: cfg)
    http = FakeHttp({"GetMostPlayedGames": {"response": {"rollup_date": T0 + 7 * 86400, "ranks": [
                         {"rank": 1, "appid": 730, "last_week_rank": 1, "peak_in_game": 1300000},
                         {"rank": 2, "appid": 999, "last_week_rank": 3, "peak_in_game": 5000}]}},
                     "appids=2246340&l=english": {"2246340": {"success": True, "data": {"about_the_game": "<p>Hunt &amp; explore.</p>"}}},
                     "appids=2246340": details(2246340, "モンスターハンターワイルズ"),
                     "appids=730": details(730, "Counter-Strike 2", cats=(1, 49, 36), ja=True),
                     "appids=999": details(999, "Soundtrack", kind="music")})

    def go():
        code, out = runner.daily_run(date(2026, 10, 31), reader_factory=lambda name: factory.create(name, http, cfg))
        assert code == runner.EXIT_OK, json.dumps(out, default=str)[:1500]
        return out
    return go, http


def test_profiles_and_activity_flow_to_cards_and_game_documents(run, conn, stub_screen_docs):
    go, http = run
    go()                                       # 1 回目: 順位が入る（作品の情報の対象はまだ ProtonDB の作品だけ）
    go()                                       # 2 回目: 順位の上位の作品も作品の情報の対象になる
    rows = dict(conn.execute("SELECT appid, title FROM game_profile").fetchall())
    assert rows == {"2246340": "モンスターハンターワイルズ", "730": "Counter-Strike 2"}          # 作品でない app ID（999）は作らない
    assert sum("appids=2246340&l=japanese" in u for u in http.calls) == 1                          # 取った作品は次の回に取り直さない
    # ゲーム内容（あらすじの代わり）: 日本語の取得の文（HTML を文に）と英語の取得の文
    assert conn.execute("SELECT about_ja, about_en FROM game_profile WHERE appid='2246340'").fetchone() == ("モンスターハンターワイルズ\n狩りに出よう。\n仲間と&一人で。", "Hunt & explore.")
    modes = dict(conn.execute("SELECT appid, modes FROM game_profile").fetchall())
    assert modes["730"] == ["みんなで遊べる", "対戦", "オンラインで対戦"] and modes["2246340"] == ["ひとりで遊べる", "協力プレイ"]
    prof = conn.execute("SELECT platforms, ja_text, ja_voice, image_url FROM game_profile WHERE appid='2246340'").fetchone()
    assert prof[0] == ["Windows", "Linux・Steam Deck"] and prof[1] is True and prof[2] is True
    assert conn.execute("SELECT peak_players FROM game_activity WHERE appid='730' ORDER BY day DESC LIMIT 1").fetchone()[0] == 1300000
    assert public_document.get_document(conn, "overview") is None                   # 古い文書は作らない（#3 2026-11-11）


def test_publish_input_changes_when_profiles_are_rebuilt_from_the_same_fetch(conn):
    """作品の情報を同じ取得の応答から作り直したとき（取得の時刻は同じ）も、公開の材料の版が変わって作り直される（#2 2026-11-11）。"""
    from game_signal_scout.repositories import catalog
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES ('x', '1', now(), now(), '{}')")
    conn.execute("INSERT INTO game_profile (appid, source, item_id, title, genres, modes, platforms, fetched_at) "
                 "VALUES ('1', 'x', '1', 't', '[]', '[\"対戦\"]', '[]', '2026-11-01T00:00:00Z')")
    v1 = catalog.newest_catalog_at(conn)
    conn.execute("UPDATE game_profile SET modes = '[\"対戦\", \"オンラインで対戦\"]' WHERE appid = '1'")
    v2 = catalog.newest_catalog_at(conn)
    assert v1 != v2 and v1.split("|")[0] == v2.split("|")[0]
    conn.rollback()
