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


def test_menu_has_the_four_intents_and_finds_keeps_its_own_kinds():
    """左のメニュー（#2 2026-11-11 オーナーの最終判断）: ダッシュボード・注目の作品 → 遊ぶ目的の 4 つの入口（独立した項目）→ 作品を探す・このサイトについて。
    「すべて」は置かない。注目の作品は細かな面白さの種類で探すページで、4 つの入口と親子の絞り込みにしない。選んだ種類はもう一度押すと解除。
    4 つの入口のページの上に、メニューと同じ切り替えを重ねない。遊び方・言語圏のページは消さない。"""
    from pathlib import Path
    root = Path(__file__).parents[1] / "src/game_signal_scout/web"
    js = (root / "static/common.js").read_text()
    nav = js[js.index("const NAV = ["):js.index("const NAV_OF")]
    order = ['"index", "ダッシュボード"', '"finds", "注目の作品"', "...INTENTS.map", '"search", "作品を探す"', '"about", "このサイトについて"']
    pos = [nav.index(x) for x in order]
    assert pos == sorted(pos) and '"h"' not in nav and "すべて" not in nav and '"soon"' not in nav
    for k, ja in (("deep", "じっくり没頭したい"), ("short", "短時間で楽しみたい"), ("novel", "新しい体験がしたい"), ("friends", "友達と遊びたい")):
        assert f'["{k}", "{ja}"' in js and (root / f"templates/pages/{k}.html").exists()
    fj = (root / "static/finds.js").read_text()
    assert "fi4" not in fj and "intentView" not in fj and "INTENT" not in fj and "fk-all" not in fj      # 4 つの入口・「すべて」の行は注目の作品に置かない
    assert '<a href="${K === k ? "finds.html" : `finds.html?k=${k}`}"' in fj                            # もう一度押すと解除
    ij = (root / "static/intent.js").read_text()
    assert "it-tabs" not in ij and 'getElementById("it-body")' in ij
    for k in ("solo", "coop", "versus", "pad", "langspread", "split"):
        assert (root / f"templates/pages/{k}.html").exists()
    assert "finds.html?i=" not in (root / "templates/pages/search.html").read_text()
    from game_signal_scout.web.pages import PAGES
    assert PAGES["finds"].extra_scripts == () and all(PAGES[k].script == "intent.js" for k in ("deep", "short", "novel", "friends"))
    assert "放送後も熱い" not in js


def test_intent_pages_open_directly_and_short_is_not_filled_with_the_opposite(client):
    """4 つの入口のページはそのまま開く（転送しない）。短時間で楽しみたいが 0 作品のとき、時間がかかる作品の一覧で埋めない（6796702815）。"""
    c, last, docs = client
    for k in ("deep", "short", "novel", "friends", "finds", "split", "solo", "langspread"):
        r = c.get(f"/{k}.html", follow_redirects=False)
        assert r.status_code == 200, k
    p = c.get("/api/pages").json()
    assert "long" not in p["intents"]["short"]
    from pathlib import Path
    ij = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/intent.js").read_text()
    assert "1 回に時間がかかると書かれた作品" not in ij and "I.short || {}).long" not in ij


def test_divided_titles_need_both_sides():
    """賛否が分かれる作品: 面白いと書いた人・不満を書いた人がどちらも 2 人以上。賛否の混じる体験は数えない。より割れている順。"""
    from game_signal_scout.services.intents import divided
    x = lambda **k: {"verdict": "fun", "people": 1, "act": "a", "result": "r", "against": 0, **k}
    works = {1: {"xs": [x(people=3), x(verdict="frustration", people=2)]},
             2: {"xs": [x(people=5, against=1), x(verdict="frustration")]},       # 不満 1 + 反対の声 1 = 2
             3: {"xs": [x(people=4), x(verdict="mixed", people=3)]},               # 不満がない
             4: {"xs": [x(), x(verdict="frustration", people=4)]}}                # 面白いが 1 人
    got = divided(works)
    from pathlib import Path
    dj = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/divided.js").read_text()
    assert "w.fun_xs.map(x => `<li>${line(x)}</li>`)" in dj and "line(x, true)" in dj                 # 注意の印は不満の側だけ
    assert [it["work"] for it in got] == [2, 1] and got[1]["fun"] == 3 and got[1]["against"] == 2 and got[0]["against"] == 2   # 割れ方が同じなら声の多い順


def test_intents_are_chosen_from_player_experiences_only():
    """遊びたい体験の入口（#2 2026-11-11）: 作品は実際に遊んだ人の体験だけで選ぶ。不満の体験は根拠にしない。根拠のない入口は空（埋めない）。
    注意（不満の体験・注意の人数）と、短時間の入口では 1 回が長いという声を添える。"""
    from game_signal_scout.services.intents import select
    x = lambda **k: {"verdict": "fun", "people": 1, "act": "a", "result": "r", "kind": None, "style": None, "session": None, "caution": None, "fits": "", **k}
    works = {1: {"xs": [x(kind="explore", people=3, fits="自力で進めたい人"), x(kind="story"), x(verdict="frustration", caution="bugs", people=2)]},
             2: {"xs": [x(style="coop", people=2), x(kind="surprise"), x(session="long", caution="time")]},
             3: {"xs": [x(kind="explore", verdict="frustration")]}}                     # 不満だけ: どの入口にも入らない
    s = select(works)
    assert [it["work"] for it in s["deep"]] == [1] and s["deep"][0]["why_people"] == 4 and s["deep"][0]["fits"] == "自力で進めたい人"
    assert s["deep"][0]["warn"][0]["caution"] == "bugs" and s["deep"][0]["cautions"] == {"bugs": 2}
    assert [it["work"] for it in s["friends"]] == [2] and [it["work"] for it in s["novel"]] == [2]
    assert s["short"] == []                                                            # 1 回が短いと書いた体験がない: 空のまま
    assert select({5: {"xs": [x(style="versus", verdict="mixed")]}})["friends"] == []   # 対戦で遊んだが賛否: 根拠にしない
    s2 = select({4: {"xs": [x(session="short", people=2)]}})
    assert [it["work"] for it in s2["short"]] == [4]


def test_intent_pages_are_published_with_reasons(client):
    """公開の文書 pages に入口ごとの作品・根拠・注意がある。作品は重複せず、根拠の体験が必ずある。"""
    c, last, docs = client
    p = c.get("/api/pages").json()
    I = p["intents"]
    assert set(I) >= {"deep", "short", "novel", "friends", "basis"} and I["basis"]["session_since"] == "2026-11-11"
    for k in ("deep", "short", "novel", "friends"):
        ids = [w["id"] for w in I[k]["items"]]
        assert len(ids) == len(set(ids)) and all(w["why"] and w["why_people"] >= 1 for w in I[k]["items"])
    from pathlib import Path
    js = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/intent.js").read_text()
    for s_ in ("この体験に合う根拠", "合わないかもしれない点", "まだ、短時間で楽しめたと書いた体験が見つかっていません", "ジャンルやストアの分類では選んでいません"):
        assert s_ in js


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


def test_play_style_pages_classify_only_what_the_store_lists():
    """遊び方のページ（#2 2026-11-11 オーナー）: ソロ・協力・対戦の分け方はストアの表示だけ。マルチプレイ（協力か対戦か分からない）は
    協力・対戦のどちらにも入れない。協力・対戦は、どこでつながるか（オンライン・同じ画面・LAN）も表示どおりに持つ。"""
    from game_signal_scout.sources.steam_store import profile_row
    m = lambda *cats: profile_row("1", None, {"type": "game", "name": "x", "categories": [{"id": c} for c in cats]})["modes"]
    assert m(2) == ["ひとりで遊べる"]
    assert m(1) == ["みんなで遊べる"]                                                     # 協力・対戦の印がない: どちらにも入れない
    assert m(9, 38) == ["協力プレイ", "オンラインで協力"]
    assert set(m(39)) == {"協力プレイ", "同じ画面で協力", "画面分割・同じ画面で"} and m(48) == ["協力プレイ", "LANで協力"]
    assert m(49, 36) == ["対戦", "オンラインで対戦"] and set(m(37)) == {"対戦", "同じ画面で対戦", "画面分割・同じ画面で"} and m(47) == ["対戦", "LANで対戦"]
    from pathlib import Path
    js = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/search.js").read_text()
    for s_ in ('["only", tr("ひとり用だけ"', '["online", tr("オンラインで協力"', '["online", tr("オンラインで対戦"', "表示のない作品は、どれにも入りません"):
        assert s_ in js
    assert "AniList" not in js                                                            # Game にない評価・リストの数で並べない


def test_intent_pages_open_with_their_own_catch_copy():
    """4 つの遊ぶ目的のページ（#2 2026-11-11 オーナー）: 見出しの直下にページごとに違うキャッチコピー（日英）。選び方の説明は小さな補足で、大きな主文にしない。"""
    from pathlib import Path
    root = Path(__file__).parents[1] / "src/game_signal_scout/web"
    want = {"deep": ("気づけば、もうこんな時間。夢中になれる世界へ。", "Lose track of time. Find a world to get lost in."),
            "short": ("少しの時間でも、心に残る遊びを。", "A little time. A memorable experience."),
            "novel": ("まだ知らない「面白い」に、出会おう。", "Discover a kind of fun you haven't met yet."),
            "friends": ("一緒だから、もっと面白い。", "Better together.")}
    for k, (ja, en) in want.items():
        h = (root / f"templates/pages/{k}.html").read_text()
        assert f'</h2><p class="it-copy" data-en="{en}">' in h and ja in h.replace("<span>", "").replace("</span>", "") and "プレイヤーが書いた作品" not in h
    css = (root / "static/finds.css").read_text()
    assert "main.it .fd-title .it-copy { margin: 4px 0 2px; font-size: 22px; font-weight: 800" in css and ".it-why { margin: 0 0 10px; font-size: 13px" in css
