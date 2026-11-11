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
    cfg = {**cfg, "web": {**cfg["web"], "allow_from": [*cfg["web"]["allow_from"], "testclient"]}}   # 試験の相手（TestClient）
    with TestClient(create_app(cfg=cfg, pool=pool)) as c:
        yield c, last, docs
    pool.close()


def test_anime_pages_and_api_serve_game_documents(client):
    c, last, docs = client
    for path in ("/", "/finds.html", "/spread.html", "/revival.html", "/langspread.html", "/search.html", "/solo.html", "/coop.html", "/versus.html", "/pad.html",
                 "/about.html", "/work.html", "/api/days", "/api/pages", "/api/search", "/api/works/w2246340", "/healthz", "/static/site-header.jpg"):
        assert c.get(path).status_code == 200, path
    assert c.get("/api/days").json()["days"] == [last.isoformat()]               # 画面に出す日は観測を始めた日から（先月の日を出さない）
    d = c.get(f"/api/days/{last.isoformat()}").json()["dashboard"]
    assert d["works_today"] == 2 and (any(x["id"] == "w2246340" for x in d["checks"])   # 普段（2 人）から 12 人に増えた作品が「今チェック」に出る
                                      or (d["lead"].get("work") == "w2246340" and d["checks_lead"] == 1))   # 見出しの主役なら今日の兆しで紹介し、今日の注目からは除く（#2 2026-11-11）
    assert {x["code"] for x in d["lang_obs"]["langs"]} >= {"en", "ja"}
    assert "https://*.steamstatic.com" in c.get("/").headers["content-security-policy"]


def test_menu_keeps_anime_names_and_adds_play_styles():
    """左の案内: Anime の名前を保ち、遊び方のページを足す。「世界で広がる」は「プレイヤーの発見」に置き換えた（#2）。"""
    from pathlib import Path
    js = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/common.js").read_text()
    for name in ('"index", "ダッシュボード"', '"finds", "注目の作品"', '"langspread", "言語圏の広がり"', '"search", "作品を探す"',
                 '"about", "このサイトについて"', '"solo", "一人（ソロ）で遊べる"', '"coop", "協力プレイで遊べる"', '"versus", "対戦プレイで遊べる"', '"pad", "コントローラで遊べる"'):
        assert name in js
    assert "放送後も熱い" not in js                                                  # Game にない放送のページは置かない


def test_todays_pick_card_has_no_language_area_list():
    """今日の注目の代表カード（ck1）に話題の言語圏の一覧を出さない（#7）。注目の理由・その後・初検知と人数は残す。並び（今日の兆し → 地図 → 今日の注目 → もっと見る）は変えない。"""
    from pathlib import Path
    root = Path(__file__).parents[1] / "src/game_signal_scout/web"
    js = (root / "static/dashboard.js").read_text()
    ck1 = js[js.index('<article class="ck1"'):js.index("</article>", js.index('<article class="ck1"'))]
    assert "spread" not in ck1 and '"広がり"' not in ck1
    for keep in ("ck1-line", '"その後"', '"初検知"', "grow(top)", "art(top)", "wn(top.name"):
        assert keep in ck1
    html = (root / "templates/pages/index.html").read_text()
    order = [html.index(f'id="{i}"') for i in ("intro", "lead", "world", "others", "more")]
    assert order == sorted(order)


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


def test_pages_carry_plain_text_for_readers_without_javascript(client):
    """JavaScript を動かさない読み手（ページを読みに来る AI など）にも、最初の HTML に文の要約がある。ブラウザでは boot.js が消す。"""
    c, last, docs = client
    top = c.get("/").text
    assert 'id="plain"' in top and "work.html?id=w2246340" in top
    work = c.get("/work.html?id=w2246340").text
    assert 'id="plain"' in work and "狩りに出よう。" in work
    assert 'id="plain"' not in c.get("/work.html?id=w0").text            # 公開していない作品: 要約なしで、ページは出す
    assert 'id="plain"' not in c.get("/about.html").text
    r = c.get("/robots.txt")
    assert "ChatGPT-User" not in r.text and "GPTBot" in r.text and r.headers["cache-control"] == "public, max-age=300"   # 頼まれて読む ChatGPT は断らない。学習用は断る                 # 説明のページは本文がもともと HTML にある
    from pathlib import Path
    assert 'getElementById("plain")' in (Path(__file__).parents[1] / "src/game_signal_scout/web/static/boot.js").read_text()


def test_non_game_software_is_not_a_work(conn):
    """ゲームでないソフト（Steam のジャンルがユーティリティなど。例: Wallpaper Engine）は作品として出さない。"""
    from game_signal_scout.ops.work import publishable_works
    for a, g in (("431960", '["カジュアル", "ユーティリティ", "写真編集"]'), ("1245620", '["アクション", "RPG"]')):
        conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES ('steam_store', %s, now(), now(), '{}')", (a,))
        conn.execute("INSERT INTO game_profile (appid, source, item_id, title, genres, modes, platforms, fetched_at) VALUES (%s, 'steam_store', %s, 'x', %s, '[]', '[]', now())", (a, a, g))
    assert publishable_works(conn, [431960, 1245620]) == {1245620}



def test_only_known_peers_and_no_health_through_the_public_entrance(client):
    """受けてよい相手（Issue #6）: 知らない相手は 403。公開の入口（X-Forwarded-For つき）からは稼働の確認の口を出さない。"""
    c, last, docs = client
    assert c.get("/healthz").status_code == 200
    assert c.get("/healthz", headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 404
    assert c.get("/", headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 200
    from fastapi.testclient import TestClient
    from game_signal_scout.web.app import create_app
    app = c.app
    assert TestClient(app, client=("192.168.11.3", 1234)).get("/").status_code == 200       # VAIO の共通の入口（/game/・公開の名前）からの中継は受ける
    assert TestClient(app, client=("192.168.11.50", 1234)).get("/").status_code == 403      # 裏の口を直接開くことはできない（利用者は VAIO の入口から）
    assert TestClient(app, client=("8.8.8.8", 1234)).get("/").status_code == 403


def test_public_documents_do_not_quote_posts_unless_terms_allow(client):
    """原文の引用は、利用条件（config/source_terms.toml）で public_quote が allowed と記録された取得元だけ。既定は出さない（#3 G2）。"""
    import json as _json
    c, last, docs = client
    w = c.get("/api/works/w2246340").json()
    assert all(not p.get("quotes") for s in w.get("streams") or [] for p in s.get("points") or [])
    d = _json.dumps(c.get(f"/api/days/{last.isoformat()}").json(), ensure_ascii=False)
    assert '"quote":' not in d


def test_todays_signal_separates_the_lead_title_from_the_others(client):
    """今日の兆し（#2 2026-11-10 オーナー）: 作品の列の作品は選んだ理由の役割を持つ。主役（lead）は見出しの作品だけで 1 つまで、
    普段より動いた作品（moved）は今チェックしておきたい作品にあり変化の名前を持ち、残りは話題にした人の多い作品（talked）。作品は重ならず、消えない。"""
    c, last, docs = client
    d = c.get(f"/api/days/{last.isoformat()}").json()["dashboard"]
    ft, ck = d["featured"], {x["id"]: x for x in d["checks"]}
    assert ft and all(w["role"] in ("lead", "moved", "talked") for w in ft) and len({w["id"] for w in ft}) == len(ft)
    leads = [w for w in ft if w["role"] == "lead"]
    assert len(leads) <= 1 and (not leads or leads[0]["id"] == d["lead"].get("work"))
    assert all(w["id"] in ck and w["label"] == ck[w["id"]]["label"] for w in ft if w["role"] == "moved")
    assert all(w["id"] not in ck or w["role"] == "lead" for w in ft if w["role"] != "moved")
    from pathlib import Path
    js = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/dashboard.js").read_text()
    for s_ in ('MAIN ? `<a class="g-cov" href="${A.workUrl(MAIN.id)}"', "ほかに、普段より話題が動いた作品", "ほかに、この日話題にした人が多かった作品"):
        assert s_ in js


def test_todays_pick_does_not_repeat_the_lead_title():
    """今日の注目（#2 2026-11-11 オーナー）: 見出しの主役は今日の兆しで紹介し、今日の注目には出さない。並びは検出の順のまま。
    ほかに動いた作品がなければ空（ほかの作品で埋めない）。主役がいない・主役が動いた作品にない日は、そのまま。"""
    from game_signal_scout.signal.content import checks_without_lead
    ck = lambda *ids: [{"id": i} for i in ids]
    ids = lambda xs: [x["id"] for x in xs]
    shown, n = checks_without_lead(ck("w1", "w2", "w3"), {"work": "w2"})          # 重複あり: 主役だけ除き、順は保つ
    assert ids(shown) == ["w1", "w3"] and n == 1
    shown, n = checks_without_lead(ck("w1", "w3"), {"work": "w9"})                # 重複なし: そのまま
    assert ids(shown) == ["w1", "w3"] and n == 0
    assert checks_without_lead(ck("w2"), {"work": "w2"}) == ([], 1)               # 主役だけ: 空（埋めない）
    assert checks_without_lead([], {"work": "w2"}) == ([], 0)                     # 候補なし
    assert ids(checks_without_lead(ck("w1", "w2"), {})[0]) == ["w1", "w2"]       # 主役なし
    assert ids(checks_without_lead(ck("w1", "w2"), None)[0]) == ["w1", "w2"]


def test_published_days_never_show_the_lead_title_in_todays_pick(client):
    """公開したすべての日（最新の日と古い日）で、主役は今日の注目にいない。除いた数は 0 か 1 で、主役がいた日だけ 1。"""
    c, last, docs = client
    from datetime import timedelta
    seen = 0
    for k in range(0, 40):
        r = c.get(f"/api/days/{(last - timedelta(days=k)).isoformat()}")
        if r.status_code != 200:
            continue
        d = r.json()["dashboard"]
        w = (d.get("lead") or {}).get("work")
        assert all(x["id"] != w for x in d["checks"]) and d["checks_lead"] in (0, 1)
        assert d["checks_lead"] == 0 or w
        seen += 1
    assert seen >= 1
    from pathlib import Path
    js = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/dashboard.js").read_text()
    assert "cks.sort" not in (Path(__file__).parents[1] / "src/game_signal_scout/signal/content.py").read_text()
    assert "今日の兆しで紹介した作品を除く" in js and "上の今日の兆しで紹介した作品のほかにはありませんでした" in js
