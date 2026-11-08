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
    zh = TitleIndex([("2246340", "魔物獵人 荒野")], [], [], 8, game_only=True)                       # 各言語の表示名（game_profile.names）
    assert identify({"text": "[心得] 魔物獵人荒野 新武器好用"}, zh)[0] == "2246340"
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


def test_steam_discussions_topics_and_replies_from_html():
    """Steam の掲示板: 一覧の新しい話題だけを開き、最初の投稿と返信を 1 件ずつ（引用した他人の文は除く・投稿者の番号は持たない）。"""
    from game_signal_scout.sources.steam_discussions import parse_list, parse_topic
    lst = ('<a class="forum_topic_overlay" href="https://steamcommunity.com/app/10/discussions/0/111/"></a>'
           '<div class="forum_topic_lastpost" title="x" data-timestamp="200">')
    assert parse_list(lst) == [("https://steamcommunity.com/app/10/discussions/0/111/", "111", 200)]
    page = ('<div id="forum_op_111"><a data-miniprofile="42"></a><div class="date commentthread_comment_timestamp" title="t" data-timestamp="100"></div>'
            '<div class="topic" id="forum_op_topic_111">Crash after patch</div>\n<div class="content" id="forum_op_content_111">Game crashes<br>help</div>\n'
            '<div class="forum_op_footer"></div></div>'
            '<div class="commentthread_comment  " id="comment_222"><a class="hoverunderline commentthread_author_link " data-miniprofile="43"></a>'
            '<div class="commentthread_comment_timestamp" title="t" data-timestamp="150"></div>'
            '<div class="commentthread_comment_text" id="comment_content_222"><blockquote class="bb_blockquote"><div>Originally posted by X:</div>quoted</blockquote>same here</div>'
            '\n<div class="comment_footer_ctn"></div></div><a href="?ctp=3">3</a>')
    posts, pages = parse_topic(page)
    assert [(p["id"], p["text"], p["at"]) for p in posts] == [("111", "Crash after patch\nGame crashes\nhelp", 100), ("222", "same here", 150)]
    assert pages == 3 and "42" not in posts[0]["author"]


def test_feed_and_discourse_sources_read_only_new_items():
    """共通の読み方: RSS / Atom の項目と Discourse の投稿を 1 件ずつ。前回より新しいものだけ。作品の掲示板は記述の appid。"""
    from game_signal_scout.sources.feeds import Discourse, FeedForum, parse_feed
    rss = ('<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item><title>Elden Ring patch</title><link>https://f/1</link><guid>g1</guid>'
           '<pubDate>Sat, 07 Nov 2026 10:00:00 +0000</pubDate><dc:creator>bob</dc:creator><description>&lt;p&gt;lag &amp;amp; crash&lt;/p&gt;</description></item></channel></rss>')
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>a1</id><title>[心得] 新作</title><updated>2026-11-07T10:00:00Z</updated>'
            '<author><name>x</name></author><link href="https://p/1"/><content>好玩</content></entry></feed>')
    assert [(e["id"], e["title"]) for e in parse_feed(rss) + parse_feed(atom)] == [("g1", "Elden Ring patch"), ("a1", "[心得] 新作")]

    class Http:
        def get_text(self, s, url):
            return rss

        def get_json(self, s, url):
            return {"latest_posts": [{"id": 5, "created_at": "2026-11-07T10:00:00Z", "cooked": "<p>queue is broken</p>", "topic_title": "Queue",
                                      "username": "u", "topic_slug": "q", "topic_id": 9, "post_number": 2}]}
    f = FeedForum({"feeds": [{"url": "https://f/rss", "appid": 1245620, "lang": "en"}]}, Http())
    b = list(f.read(None))[0]
    assert b.items[0].payload["appid"] == "1245620" and b.items[0].payload["text"] == "Elden Ring patch\nlag & crash" and "bob" not in str(b.items[0].payload)
    assert list(f.read(b.cursor))[0].items == []                                   # 前回より新しい項目だけ
    d = Discourse({"sites": [{"base": "https://forum.x", "appid": 236390}]}, Http())
    b = list(d.read(None))[0]
    assert b.items[0].payload["text"] == "Queue\nqueue is broken" and b.items[0].payload["appid"] == "236390"
    assert list(d.read(b.cursor))[0].items == []


def test_poll_sources_are_the_feed_forums():
    from game_signal_scout.ops.poll import pollers
    cfg = factory.load_sources_config()
    p = pollers(cfg)
    assert {"blizzard_forums", "ptt_games", "computerbase"} <= set(p) and "steam_reviews" not in p and "bluesky" not in p


def test_lemmy_and_mastodon_skip_bots_and_old_items():
    from game_signal_scout.sources.feeds import Lemmy, MastodonTags

    class Http:
        def get_json(self, s, url):
            if "/api/v3/post/" in url:
                return {"posts": [{"post": {"id": 3, "name": "Elden Ring DLC", "body": "so hard", "published": "2026-11-07T10:00:00Z", "ap_id": "https://l/p/3"},
                                   "creator": {"actor_id": "https://l/u/a"}},
                                  {"post": {"id": 4, "name": "bot", "published": "2026-11-07T10:00:00Z"}, "creator": {"bot_account": True}}]}
            if "/api/v3/comment/" in url:
                return {"comments": []}
            return [{"id": "9", "created_at": "2026-11-07T10:00:00Z", "content": "<p>Loving the new Hades II update, the boss is great</p>", "account": {"url": "https://m/@a"}},
                    {"id": "8", "created_at": "2026-11-07T10:00:00Z", "content": "<p>https://x.y #steam</p>", "account": {"url": "https://m/@b"}}]
    lb = list(Lemmy({"communities": [{"base": "https://l", "name": "games"}]}, Http()).read(None))[0]
    assert [i.payload["text"] for i in lb.items] == ["Elden Ring DLC\nso hard"]
    mb = list(MastodonTags({"base": "https://m", "tags": ["gaming"]}, Http()).read(None))[0]
    assert [i.item_id for i in mb.items] == ["9"] and mb.cursor["https://m#gaming"] == "9"


def test_gog_reviews_map_title_and_stop_at_last_seen():
    from datetime import datetime, timezone
    from game_signal_scout.sources.gog_reviews import GogReviews
    now = datetime.now(timezone.utc).isoformat()

    class Http:
        def get_json(self, s, url):
            if "catalog" in url:
                return {"products": [{"id": "9", "title": "Hades II: Soundtrack", "productType": "dlc"}, {"id": "7", "title": "Hades II", "productType": "game"}]}
            return {"pages": 1, "_embedded": {"items": [{"id": "r2", "creationDate": now, "content": {"title": "Great", "description": "boss &amp; music", "language": "de-DE"},
                                                          "reviewer": {"id": "1"}, "rating": {"value": 5}},
                                                         {"id": "r1", "creationDate": now, "content": {"title": "Ok", "description": "fine", "language": "en-US"},
                                                          "reviewer": {"id": "2"}}]}}
    r = GogReviews({"apps": [["1145350", "Hades II"]], "max_age_days": 28}, Http())
    b = list(r.read(None))[0]
    assert b.cursor["map"] == {"1145350": "7"} and [(i.item_id, i.payload["lang"], i.payload["appid"]) for i in b.items] == [("r2", "de", "1145350"), ("r1", "en", "1145350")]
    assert b.items[0].payload["text"] == "Great\nboss & music" and "1" not in b.items[0].payload["author"][:0]
    assert list(r.read(b.cursor))[0].items == []                                # 前回の最新に届いたら止まる


def test_nicopedia_responses_have_jst_time_and_daily_id():
    from game_signal_scout.sources.nicopedia import parse
    page = ('<span class="bbs_resInfo_resTime" >2026/11/07(土) 19:57:36</span> ID: abc'
            '</div></dt><dd class="st-bbs_resbody" data-article_id="1" data-res_no="46236" data-id_hash="abc" data-res_hidden="0">'
            '<div class="bbs_resbody_inner" ><a href="/b/a/x/1-#3" class="dic">&gt;&gt;3</a><br>アプデで<a class="auto" href="/a/x">重く</a>なった</div>\n  </dd>')
    r = parse(page)
    assert [(x["no"], x["at"].isoformat(), x["id"], x["text"]) for x in r] == [(46236, "2026-11-07T19:57:36+09:00", "abc", "アプデで重くなった")]


def test_pantip_comments_keep_text_but_not_member_number():
    from game_signal_scout.sources.pantip import actor, parse_comments
    raw = '﻿{"comments":[{"_id":"1","user":{"mid":42},"created_time":"1794121631","message":"สนุกมาก<br>","replies":[{"reply_id":"2","user":{"mid":43},"data_utime":"11/08/2026 14:07:11","message":"จริง"}]}]}'
    rows, n = parse_comments(raw)
    assert n == 1 and [(r["id"], r["text"], r["at"].isoformat()) for r in rows] == [("c:1", "สนุกมาก", "2026-11-08T07:07:11+00:00"), ("r:2", "จริง", "2026-11-08T07:07:11+00:00")]
    assert "42" not in actor(42)


def test_digest_headline_uses_short_title_for_long_names():
    from game_signal_scout.ops.digest_checks import short_title
    assert short_title("Probably Stolen - Cyberpunk Shopkeeper Sim") == "Probably Stolen"
    assert short_title("Monster Hunter Wilds: Ascension Expansion Pack") == "Monster Hunter Wilds"
    assert short_title("ELDEN RING NIGHTREIGN") == "ELDEN RING NIGHTREIGN"          # 短い題名はそのまま
