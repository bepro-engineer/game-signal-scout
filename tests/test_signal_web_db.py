"""Anime の画面の流用（web/ = Anime の web をそのまま）と、その文書（signal/ = Anime の publication/content を流用）を一時の DB で通す。
- プレイヤーの発言（player_post）→ 観測の集計（observations。Anime の sources/observations）→ 公開用の文書（day/・pages・search・work/・days）
- Anime と同じページ・接続口が返る。メニューは Anime の名前のまま（ダッシュボード・作品を探す）に、遊び方の 4 項目を足しただけ
- 画面に出す日は Game が観測を始めた日から（config/daily.toml [publish] start_day）。それより前の日は「普段」を測るためだけに使う
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from game_signal_scout.days import day_range


def post(conn, appid, i, day, lang="en", stance="positive"):
    t = day_range(day)[0] + timedelta(hours=1, minutes=i)
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES ('steam_reviews', %s, %s, %s, '{}') ON CONFLICT DO NOTHING",
                 (f"{appid}-{day}-{i}", t, t))
    conn.execute("INSERT INTO player_post (source, item_id, at, author, lang, appid, title, matched_by, flags, text, stance) "
                 "VALUES ('steam_reviews', %s, %s, %s, %s, %s, NULL, 'source', '[]', %s, %s)",
                 (f"{appid}-{day}-{i}", t, f"a{appid}{day}{i}", lang, appid, f"review {i} about the latest update and the boss fight balance", stance))


@pytest.fixture
def client(conn, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from psycopg_pool import ConnectionPool
    from game_signal_scout import config, db, observations
    from game_signal_scout.days import default_day
    from game_signal_scout.signal import publishing
    from game_signal_scout.web.app import create_app
    last = default_day()
    for a, title in (("2246340", "モンスターハンターワイルズ"), ("1808500", "ARC Raiders")):
        conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES ('steam_store', %s, now(), now(), '{}')", (a,))
        conn.execute("INSERT INTO game_profile (appid, source, item_id, title, summary, image_url, genres, modes, platforms, fetched_at, about_ja, about_en) "
                     "VALUES (%s, 'steam_store', %s, %s, 's', %s, '[\"アクション\"]', %s, '[\"Windows\"]', now(), '狩りに出よう。', 'Go hunting.')",
                     (a, a, title, f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{a}/header.jpg",
                      '["協力プレイ"]' if a == "1808500" else '["ひとりで遊べる"]'))
    for k in range(1, 21):                       # 普段（毎日 2 人）
        for i in range(2):
            post(conn, "2246340", i, last - timedelta(days=k))
    for i in range(12):                          # 最新の日に急に増えた
        post(conn, "2246340", i, last, lang="en" if i % 2 else "ja", stance="negative")
    for i in range(3):
        post(conn, "1808500", i, last)
    conn.commit()
    observations.run(conn, [last - timedelta(days=k) for k in range(28)])
    cfg = {**config.load_daily_config(), "publish": {"start_day": last.isoformat()}}
    docs, st = publishing.build_documents(conn, cfg)
    from game_signal_scout.repositories import public_document
    now = datetime.now(timezone.utc)
    bid = public_document.create_build(conn, "v", "test", now)
    public_document.replace_documents(conn, bid, docs, now)
    public_document.finish_build(conn, bid, "published", now, latest_day=last, documents=len(docs))
    conn.commit()
    pool = ConnectionPool(config.db_dsn(), min_size=1, max_size=2, kwargs={"autocommit": True}, configure=db.verify_identity, open=True)
    with TestClient(create_app(cfg=cfg, pool=pool)) as c:
        yield c, last, docs
    pool.close()


def test_anime_pages_and_api_serve_game_documents(client):
    c, last, docs = client
    for path in ("/", "/spread.html", "/revival.html", "/langspread.html", "/search.html", "/solo.html", "/coop.html", "/versus.html", "/pad.html",
                 "/about.html", "/work.html", "/api/days", "/api/pages", "/api/search", "/api/works/w2246340", "/healthz", "/static/site-header.jpg"):
        assert c.get(path).status_code == 200, path
    assert c.get("/api/days").json()["days"] == [last.isoformat()]               # 画面に出す日は観測を始めた日から（先月の日を出さない）
    d = c.get(f"/api/days/{last.isoformat()}").json()["dashboard"]
    assert d["works_today"] == 2 and any(x["id"] == "w2246340" for x in d["checks"])   # 普段（2 人）から 12 人に増えた作品が「今チェック」に出る
    assert {x["code"] for x in d["lang_obs"]["langs"]} >= {"en", "ja"}
    assert "https://*.steamstatic.com" in c.get("/").headers["content-security-policy"]


def test_menu_keeps_anime_names_and_adds_play_styles():
    from pathlib import Path
    js = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/common.js").read_text()
    for name in ('"index", "ダッシュボード"', '"spread", "世界で広がる"', '"revival", "再燃"', '"langspread", "言語圏の広がり"', '"search", "作品を探す"',
                 '"about", "このサイトについて"', '"solo", "一人（ソロ）で遊べる"', '"coop", "協力プレイで遊べる"', '"versus", "対戦プレイで遊べる"', '"pad", "コントローラで遊べる"'):
        assert name in js
    assert "放送後も熱い" not in js                                                  # Game にない放送のページは置かない


def test_search_items_carry_play_modes_for_menu_pages(client):
    c, last, docs = client
    works = {w["id"]: w for w in c.get("/api/search").json()["works"]}
    assert works["w1808500"]["modes"] == ["協力プレイ"] and works["w2246340"]["modes"] == ["ひとりで遊べる"]


def test_work_page_shows_game_content_instead_of_synopsis(client):
    c, last, docs = client
    w = c.get("/api/works/w2246340").json()
    assert w["synopsis"] == {"ja": "狩りに出よう。", "en": "Go hunting."} and w["synopsis_mt"] is False and w["genres"] == ["アクション"]
    from pathlib import Path
    js = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/work.js").read_text()
    assert 'tr("ゲーム内容", "About the game")' in js
