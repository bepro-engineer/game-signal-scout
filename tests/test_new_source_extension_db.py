"""拡張の試験（Issue #3 の最重要の条件）: 架空の取得元をこの試験の中だけで足し、共通の処理（収集・正規化・作品の同定・観測の集計・公開の文書・画面）を
1 行も変えずに、登録 → 取得 → 共通の保存 → 正規化 → 同定 → 集計 → 公開の文書 → 作品詳細の取得元の切り替え まで進むことを確かめる。

足したのは、この試験の中の SourceReader の子クラス（FakeForum）と、記述（取得元の記述・観測の集計に入れる記述）だけ。外のサイトには接続しない。
"""
from __future__ import annotations

from datetime import timedelta

from game_signal_scout.days import day_range, default_day
from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

DAY = default_day()


class FakeForum(SourceReader):
    """架空の掲示板。作品の掲示板の投稿（作品が決まる）と、総合の板の投稿（本文の題名で同定する）を返す。"""

    def read(self, cursor):
        t = day_range(DAY)[0] + timedelta(hours=2)
        items = [SourceItem(self.name, f"p{i}", t + timedelta(minutes=i), {"appid": "2246340", "author": f"a{i}", "lang": "de", "text": f"Patch {i} hat die Bosse verändert"})
                 for i in range(3)]
        items.append(SourceItem(self.name, "g1", t, {"author": "b1", "lang": "en", "text": "Monster Hunter Wilds patch broke my saves"}))
        yield Batch(items, {"done": True})


def test_a_new_source_flows_to_documents_without_changing_common_code(conn, monkeypatch):
    from game_signal_scout import config
    from game_signal_scout.ops import runner
    from game_signal_scout.repositories import public_document
    from game_signal_scout.sources import factory
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES ('steam_store', '2246340', now(), now(), '{}')")
    conn.execute("INSERT INTO game_profile (appid, source, item_id, title, image_url, genres, modes, platforms, fetched_at, names) VALUES "
                 "('2246340', 'steam_store', '2246340', 'モンスターハンターワイルズ', 'https://shared.akamai.steamstatic.com/x.jpg', '[\"アクション\"]', '[]', '[]', now(), "
                 "'{\"en\": \"Monster Hunter Wilds\"}')")
    conn.commit()
    # 記述だけで足す: 取得元の記述（adapter・normalizer）と、観測の集計に入れる記述（map_sources）
    src_cfg = {"fake_forum": {"adapter": "test_new_source_extension_db:FakeForum", "normalizer": "game_signal_scout.services.normalize:voices", "game_only": True}}
    monkeypatch.setattr(factory, "load_sources_config", lambda: src_cfg)
    real_toml = config.load_toml
    monkeypatch.setattr(config, "load_toml", lambda name: {"sources": {"fake_forum": {"reader": "foundation", "production": True, "history": True, "label": ["架空の掲示板", "Fake forum"]}}}
                        if name == "map_sources.toml" else real_toml(name))
    real_daily = config.load_daily_config
    monkeypatch.setattr(config, "load_daily_config", lambda: {**real_daily(), "publish": {**real_daily().get("publish", {}), "start_day": DAY.isoformat()}})

    code, out = runner.daily_run(DAY, only=["collect", "normalize", "observe", "publish"], reader_factory=lambda n: factory.create(n, None, src_cfg))
    assert code == runner.EXIT_OK, out

    # 共通の保存と正規化: 作品の掲示板の 3 件は取得元で、総合の板の 1 件は本文の題名（英語の題名）で同定
    rows = conn.execute("SELECT item_id, appid, matched_by, lang FROM player_post WHERE source = 'fake_forum' ORDER BY item_id").fetchall()
    assert rows == [("g1", "2246340", "title", "en"), ("p0", "2246340", "source", "de"), ("p1", "2246340", "source", "de"), ("p2", "2246340", "source", "de")]
    # 観測の集計: 取得元ごと・言語ごとの人数（取得元をまたいで足さない）
    obs = dict(conn.execute("SELECT lang, persons FROM obs_work_lang_day WHERE source = 'fake_forum' AND target_day = %s AND work_id = 2246340", (DAY,)).fetchall())
    assert obs["*"] == 4 and obs["de"] == 3 and obs["en"] == 1
    # 公開の文書と画面: 作品詳細の話題の動きは作品全体の 1 つの系列で、この取得元は出典の説明に出る（#7: 出典の切り替えはしない）
    work = public_document.get_document(conn, "work/w2246340")
    assert len(work["streams"]) == 1 and work["streams"][0]["all"], work["streams"]
    assert any(x["label"] == ["架空の掲示板", "Fake forum"] for x in work["streams"][0]["sources"]), work["streams"][0]["sources"]
    assert not any(k.startswith("_") for k in work["streams"][0]), "内部の値は公開しない"
    day = public_document.get_document(conn, f"day/{DAY.isoformat()}")
    assert day["dashboard"]["works_today"] == 1


def test_common_code_has_no_source_name_branches():
    """共通の処理（収集・正規化・同定・集計・公開・画面・運用）に、取得元の名前がない（取得元ごとの読み方は sources/ だけ）。
    名前は決め打ちせず、記述（config/sources.toml・config/map_sources.toml）にあるすべての取得元から作る。文字列も関数名も調べる（#3 G9）。"""
    import re
    import tomllib
    from pathlib import Path
    top = Path(__file__).parents[1]
    root = top / "src/game_signal_scout"
    names = set(tomllib.loads((top / "config/sources.toml").read_text()))
    names |= set((tomllib.loads((top / "config/map_sources.toml").read_text()).get("sources") or {}))
    assert len(names) > 30
    alt = "|".join(sorted(map(re.escape, names), key=len, reverse=True))
    pat = re.compile(rf"""['"]({alt})['"]|\bdef ({alt})\b|\bdef ({alt})_""")
    found = [f"{p.relative_to(root)}:{i}: {line.strip()[:80]}" for p in root.rglob("*.py") if "sources" not in p.parts
             for i, line in enumerate(p.read_text().splitlines(), 1) if pat.search(line)]
    assert found == []


def test_sql_only_in_repositories():
    """3 層: SQL を書くのは Repository（repositories/）と接続（db.py）だけ。Controller（web・cli）・Service・取得元の読み方・画面の文書は Repository を呼ぶ。"""
    from pathlib import Path
    root = Path(__file__).parents[1] / "src/game_signal_scout"
    found = [str(p.relative_to(root)) for p in root.rglob("*.py") if ".execute(" in p.read_text() and p.parts[-2] != "repositories" and p.name != "db.py"]
    assert found == []


def test_days_before_a_source_started_are_not_covered(conn, monkeypatch):
    """観測の範囲（Anime の §14）: 取得元が観測を始める前の日は not_covered（0 人を観測した日として数えない）。過去を遡る取得元（history）は最も古い項目の日から。"""
    from datetime import datetime, timezone
    from game_signal_scout import observations
    t = day_range(DAY)[0] + timedelta(hours=1)
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES ('forum_x', 'a', %s, %s, '{}'), ('reviews_x', 'b', %s, %s, '{}')",
                 (t, t, t - timedelta(days=5), t))
    conn.commit()
    assert observations.read_foundation(conn, "forum_x", DAY - timedelta(days=1), {}).reason == observations.NOT_COVERED
    assert observations.read_foundation(conn, "forum_x", DAY, {}).reason != observations.NOT_COVERED
    assert observations.read_foundation(conn, "reviews_x", DAY - timedelta(days=3), {"history": True}).reason != observations.NOT_COVERED
    assert observations.read_foundation(conn, "never_seen", DAY, {}).reason == observations.NOT_COVERED


def test_publish_is_rejected_when_screen_documents_fail(conn, monkeypatch):
    """公開（Anime の §16.1・REQ-OPS-006）: 画面の文書が作れない・検査に通らないときは、公開を止めて前の回のままにする（例外を握りつぶさない）。"""
    import pytest
    from game_signal_scout import config
    from game_signal_scout.publication import publishing
    from game_signal_scout.signal import publishing as sp
    monkeypatch.setattr(sp, "build_documents", lambda c, cfg: ({"day/2026-11-07": {}, "days": {}}, {"audit": ["work/w1: bad field"]}))
    with pytest.raises(publishing.PublishRejectedError):
        publishing.build_documents(conn, config.load_daily_config())
    def boom(c, cfg):
        raise RuntimeError("壊れた")
    monkeypatch.setattr(sp, "build_documents", boom)
    with pytest.raises(RuntimeError):
        publishing.build_documents(conn, config.load_daily_config())


def test_quote_links_are_only_public_https_urls():
    """引用から原投稿へ（Anime の §8）: 取得元が渡した https の URL だけ。ID を URL の代わりにしない。"""
    from game_signal_scout.sources import factory
    assert factory.permalink("x", "12345", "12345") is None and factory.permalink("x", "1", "https://f/t/1") == "https://f/t/1"


def test_language_is_uncertain_when_the_detector_is_not_sure():
    """言語（Anime の §7）: 確信度 0.8 未満は uncertain（数えない）。文字で決まる言語はそのまま。"""
    from game_signal_scout.languages_detect import detect
    assert detect("これは重い") == "ja" and detect("이 게임 재밌다") == "ko" and detect("這個遊戲很好玩") == "zh-Hant"
    assert detect("ok lol") in ("uncertain", "en")


def test_posts_are_reidentified_when_the_title_dictionary_changes(conn):
    """同定の版（Anime の §5.3・§21）: 作品の辞書が変わったら、本文の題名で同定する発言を作り直す（取得元で決まる発言はそのまま）。"""
    from game_signal_scout.services import normalize
    t = day_range(DAY)[0] + timedelta(hours=1)
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES "
                 "('forum_y', 'a', %s, %s, '{\"author\": \"u1\", \"text\": \"Hollow Knight Silksong is great\"}'), "
                 "('forum_y', 'b', %s, %s, '{\"author\": \"u2\", \"text\": \"fun\", \"appid\": \"10\"}')", (t, t, t, t))
    conn.commit()
    cfg = {"game_only": True}
    normalize.voices(conn, "forum_y", cfg)
    assert dict(conn.execute("SELECT item_id, appid FROM player_post WHERE source='forum_y'").fetchall()) == {"a": None, "b": "10"}
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES ('steam_store', '1030300', now(), now(), '{}')")
    conn.execute("INSERT INTO game_profile (appid, source, item_id, title, genres, modes, platforms, fetched_at) "
                 "VALUES ('1030300', 'steam_store', '1030300', 'Hollow Knight: Silksong', '[]', '[]', '[]', now())")
    conn.commit()
    normalize.voices(conn, "forum_y", cfg)                       # 辞書が変わった: 今の版で作り直す（取得元で決まる発言は同じ結果）
    assert dict(conn.execute("SELECT item_id, appid FROM player_post WHERE source='forum_y'").fetchall()) == {"a": "1030300", "b": "10"}


def test_every_observed_source_is_optional(monkeypatch):
    """どの取得元も、なくても困らない（CLAUDE.md）: 観測の集計に入れる取得元のどれを外しても、残りで今日の兆しの声・集計の取得元が決まる（特定の取得元に依存しない）。"""
    from game_signal_scout import config, observations
    from game_signal_scout.ops import dashboard_digest as dd
    srcs = observations.sources()
    assert len(srcs) >= 2
    real = config.load_toml
    for drop in srcs:
        rest = {k: v for k, v in srcs.items() if k != drop}
        monkeypatch.setattr(config, "load_toml", lambda name, rest=rest: {"sources": rest} if name == "map_sources.toml" else real(name))
        assert set(observations.sources()) == set(rest) and set(dd.voice_sources({"dashboard_digest": {"voice_sources": "all"}})) == set(rest)


def test_digest_candidates_skip_works_without_profile(conn, monkeypatch):
    """今日の兆しの候補は画面に出せる作品だけ（作品の情報がまだない作品の声で止まらない。2026-11-08 KeyError）。"""
    from game_signal_scout.ops import dashboard_digest as dd
    monkeypatch.setattr(dd, "day_works", lambda conn, source, day, limit: [{"work_id": 899770, "voices": 9}, {"work_id": 1245620, "voices": 5}])
    from game_signal_scout.ops import work
    monkeypatch.setattr(work, "publishable_works", lambda conn, ids: {1245620})
    assert [w["work_id"] for w in dd._candidate_works(conn, "x", DAY, {})] == [1245620]


def test_no_source_has_special_structure():
    """特定の取得元を特別視しない（CLAUDE.md）: 取得元の記述はどれも同じ形。特定の取得元だけの順位・常駐・専用の起動を持たない。
    共通のコード・移行・設定の説明・起動の定義に、取得元の名前を書かない（取得元ごとの読み方 sources/ と、その取得元自身の記述だけ）。"""
    import tomllib
    from pathlib import Path
    root = Path(__file__).parents[1]
    m = tomllib.loads((root / "config/map_sources.toml").read_text())["sources"]
    allowed = {"reader", "production", "label", "history"}
    assert all(set(v) <= allowed for v in m.values()), {k: set(v) - allowed for k, v in m.items() if set(v) - allowed}
    s = tomllib.loads((root / "config/sources.toml").read_text())
    voice = set(m)
    assert all(s[k].get("resident") for k in voice if k in s)                              # 声の取得元はどれも同じ形で常駐（特定の取得元だけの常駐はない）
    from game_signal_scout.ops import launchd
    from game_signal_scout import source_terms
    assert set(launchd.services(root)) == {"daily-run", "web"} | {f"collect-{k}" for k in voice if k in s and s[k].get("enabled", True) and source_terms.allowed(k)}
    names = [k for k in s if isinstance(s[k], dict) and s[k].get("adapter")]
    texts = [p for p in list((root / "migrations").rglob("*.py")) + [root / "pyproject.toml", root / "config/daily.toml"]]
    found = [f"{p.name}:{n}" for p in texts for n in names if n in p.read_text().lower() and len(n) > 6]
    assert found == []


class FailingSource(SourceReader):
    def read(self, cursor):
        raise ConnectionError("取得元が止まっている（試験）")
        yield  # noqa


class EmptySource(SourceReader):
    def read(self, cursor):
        yield Batch([], {"done": True})


def test_system_works_when_any_source_is_stopped_disabled_or_empty(conn, monkeypatch):
    """全 Issue 共通の原則（2026-11-08）: どの取得元が止まっても・無効でも・0 件でも、ほかの取得元でシステムが成り立つ
    （収集 → 正規化 → 観測の集計 → 公開の文書まで進む。止まった取得元の失敗は、その取得元の記録に残る）。"""
    from game_signal_scout import config
    from game_signal_scout.ops import runner
    from game_signal_scout.repositories import public_document
    from game_signal_scout.sources import factory
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES ('steam_store', '2246340', now(), now(), '{}')")
    conn.execute("INSERT INTO game_profile (appid, source, item_id, title, genres, modes, platforms, fetched_at) "
                 "VALUES ('2246340', 'steam_store', '2246340', 'Monster Hunter Wilds', '[\"アクション\"]', '[]', '[]', now())")
    conn.commit()
    voices = "game_signal_scout.services.normalize:voices"
    src_cfg = {"src_ok": {"adapter": "test_new_source_extension_db:FakeForum", "normalizer": voices, "game_only": True},
               "src_down": {"adapter": "test_new_source_extension_db:FailingSource", "normalizer": voices},
               "src_empty": {"adapter": "test_new_source_extension_db:EmptySource", "normalizer": voices},
               "src_off": {"adapter": "test_new_source_extension_db:FailingSource", "normalizer": voices, "enabled": False}}
    monkeypatch.setattr(factory, "load_sources_config", lambda: src_cfg)
    real_toml = config.load_toml
    obs = {k: {"reader": "foundation", "production": True, "history": True, "label": [k, k]} for k in ("src_ok", "src_down", "src_empty")}
    monkeypatch.setattr(config, "load_toml", lambda name: {"sources": obs} if name == "map_sources.toml" else real_toml(name))
    real_daily = config.load_daily_config
    monkeypatch.setattr(config, "load_daily_config", lambda: {**real_daily(), "publish": {**real_daily().get("publish", {}), "start_day": DAY.isoformat()}})
    code, out = runner.daily_run(DAY, only=["collect", "normalize", "observe", "publish"], reader_factory=lambda n: factory.create(n, None, src_cfg))
    assert code == runner.EXIT_OK, out
    collect = out["jobs"][0]["detail"]
    assert collect["src_down"]["error_type"] and "src_off" not in collect                         # 止まった取得元は記録に残り、無効の取得元は読まない
    assert conn.execute("SELECT last_error_type IS NOT NULL FROM source_state WHERE source='src_down'").fetchone()[0]
    assert conn.execute("SELECT count(*) FROM player_post WHERE source='src_ok' AND appid='2246340'").fetchone()[0] == 4
    assert public_document.get_document(conn, f"day/{DAY.isoformat()}")["dashboard"]["works_today"] == 1   # 残りの取得元で画面の文書が成り立つ


def test_common_normalizer_applies_the_same_rules_to_every_source(conn):
    """共通 Service（5 原則）: ストアのリンクからの作品の特定・宣伝などの印・言語の判定は、取得元の読み方ではなく共通の正規化が、どの取得元にも同じに当てる。"""
    from game_signal_scout.services import normalize
    t = day_range(DAY)[0] + timedelta(hours=1)
    for src in ("src_a", "src_b"):
        conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES "
                     "(%s, 'l', %s, %s, '{\"author\": \"u1\", \"text\": \"look https://store.steampowered.com/app/2246340/X/\"}'), "
                     "(%s, 'p', %s, %s, '{\"author\": \"u2\", \"text\": \"live now playing the game twitch.tv/x\"}'), "
                     "(%s, 'j', %s, %s, '{\"author\": \"u3\", \"text\": \"アプデで重くなった\"}')", (src, t, t, src, t, t, src, t, t))
    conn.commit()
    got = {}
    for src in ("src_a", "src_b"):
        normalize.voices(conn, src, {})
        got[src] = {i: (a, m, "stream" in f, l) for i, a, m, f, l in conn.execute(
            "SELECT item_id, appid, matched_by, flags, lang FROM player_post WHERE source=%s", (src,))}
    assert got["src_a"] == got["src_b"]                                          # 取得元が違っても同じ結果
    assert got["src_a"]["l"][:2] == ("2246340", "steam_link") and got["src_a"]["p"][2] is True and got["src_a"]["j"][3] == "ja"


def test_non_fetch_contract_matches_anime_defaults():
    """取得しない用途の契約（Anime と同じ名前・既定）: 引用してよい項目は既定ですべて、原投稿の URL は https だけ、記述のない取得元は None（#3 G1）。"""
    from game_signal_scout.sources import factory
    from game_signal_scout.sources.contract import SourceReader
    for m in ("quotable", "permalink", "internal_id_markers", "voice", "profile", "report"):
        assert hasattr(SourceReader, m)
    assert factory.reader_for("never_described") is None
    assert factory.permalink("never_described", "1", "http://x") is None and factory.permalink("never_described", "1", "https://x") == "https://x"
    assert factory.permalink("never_described", "123") is None          # ID を URL の代わりに返さない


def test_every_enabled_source_has_a_terms_record_and_prohibited_ones_are_not_read():
    """利用条件（#3 G2）: 有効な取得元はすべて、一次資料の URL・確認日のある記録を持つ。禁止が明記された取得元は収集・集計に入らない。
    禁止のサイトだけを外した取得元は、そのサイトを記述で読まない。"""
    import tomllib
    from pathlib import Path
    from game_signal_scout import observations, source_terms
    from game_signal_scout.ops import collector
    from game_signal_scout.sources import factory
    top = Path(__file__).parents[1]
    cfg = tomllib.loads((top / "config/sources.toml").read_text())
    terms = tomllib.loads((top / "config/source_terms.toml").read_text())["sources"]
    enabled = [n for n, s in cfg.items() if isinstance(s, dict) and s.get("enabled", True)]
    for n in enabled:
        t = terms.get(n)
        assert t and t["category"] in ("explicitly_prohibited", "conditional", "explicitly_allowed", "unconfirmed"), n
        assert t["evidence"] and all(e["url"].startswith("https://") and e["checked"] for e in t["evidence"]), n
    banned = [n for n in enabled if not source_terms.allowed(n)]
    assert banned
    assert not set(banned) & set(factory.sources(cfg)) and not set(banned) & set(collector.residents(cfg))
    assert not set(banned) & set(observations.sources())
    text = (top / "config/sources.toml").read_text()
    for n in enabled:
        for h in source_terms.excluded_hosts(n):
            assert f"//{h}" not in text, (n, h)
    voices = set(tomllib.loads((top / "config/map_sources.toml").read_text()).get("sources") or {})
    assert not any(source_terms.quote_allowed(n) for n in enabled if n in voices)      # 発言の原文を公開の画面に引用する取得元は今は 0


# 作品の鍵が 1 つのストアの作品番号そのもの（#3 2026-11-11 の最終監査で記録した構造の不適合。作品の鍵を取得元に依らない形にするには本番の DB の作りを変える移行が要り、
# オーナーの承認が要る）。それを説明する 4 ファイルと、画像の配信元を許す画面の安全設定（web/app.py）だけは、ストアの名前を書いてよい。直したらここから外す
KNOWN_STORE_KEY_FILES = {"services/identify.py", "repositories/work.py", "ops/work.py", "web/app.py"}


def test_common_code_does_not_name_sources_even_in_descriptions():
    """取得元を特別視しない（CLAUDE.md・#3）: 共通の処理（sources/ の外）の説明・注釈にも、取得元の名前を書かない。取得元ごとの読み方は sources/ だけ。
    例外は、作品の鍵が 1 つのストアの番号であることを説明するファイル（KNOWN_STORE_KEY_FILES。構造の不適合として #3 に記録）だけ。
    Anime から流用した、Game にない外部サービスの名前（AniList）も、使わない共通の Python に残さない。"""
    import re
    from pathlib import Path
    root = Path(__file__).parents[1] / "src/game_signal_scout"
    names = re.compile(r"Steam|ProtonDB|Proton|Bluesky|Mastodon|Lemmy|Reddit|GOG|Blizzard|Discourse|Pantip|PTT|ニコニコ|はてな|Tildes|ResetEra|Famiboards|NeoGAF|AniList|Wikidata|IGDB|YouTube")
    found = [f"{p.relative_to(root)}:{i}" for p in root.rglob("*.py") if "sources" not in p.parts and str(p.relative_to(root)) not in KNOWN_STORE_KEY_FILES
             for i, line in enumerate(p.read_text().splitlines(), 1) if names.search(line)]
    assert found == []
