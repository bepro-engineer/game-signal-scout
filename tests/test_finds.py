"""プレイヤーの発見（#2）: LLM は読むこととまとめることだけ。人数・内訳・前との比較はこちらで数える。データにないものは作らない。"""
import json
from datetime import datetime, timedelta, timezone

from game_signal_scout.services import insight

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)
SINCE = NOW - timedelta(days=7)


def post(i, author, days_ago, lang="en"):
    return {"item_id": f"p{i}", "author": author, "at": NOW - timedelta(days=days_ago), "lang": lang, "text": f"text {i} " * 10}


def test_reads_keep_only_concrete_experiences_and_bad_answers_are_retried_later():
    rows = [post(i, f"a{i}", 1) for i in range(8)]
    answers = [json.dumps([{"id": 0, "exp": {"did": "分隊で拠点を奪った", "happened": "逆転勝ちした", "verdict": "fun", "topic": "拠点の奪取"}},
                           {"id": 1, "exp": None}, {"id": 2, "exp": {"did": "x", "happened": "y", "verdict": "great"}}]),   # 決まりにない verdict は捨てる
               "壊れた返事"]
    got = insight.read_statements(lambda p: answers.pop(0), "T", rows)
    assert got["p0"]["verdict"] == "fun" and got["p1"] is None and got["p2"] is None
    assert "p6" not in got and "p7" not in got      # 読めなかった束は残さない（次の回に読み直す）


def test_people_and_trend_are_counted_here_not_by_the_llm():
    posts = {p["item_id"]: p for p in [post(1, "a", 1), post(2, "b", 2, "ja"), post(3, "c", 3), post(4, "c", 4), post(5, "d", 9), post(6, "e", 1)]}
    exps = {k: {"did": "d", "happened": "h", "verdict": "fun" if k != "p6" else "frustration", "topic": "t"} for k in posts}
    groups = [{"title": "拠点を奪うと逆転できる", "members": ["p1", "p2", "p3", "p4", "p5"]}, {"title": "一人だけ", "members": ["p6"]}]
    f = insight.tally(groups, posts, exps, SINCE, 3)
    assert len(f) == 1 and f[0]["people"] == 3 and f[0]["prev"] == 1 and f[0]["trend"] == "up" and f[0]["verdict"] == "fun"   # c の 2 件は 1 人
    assert set(f[0]["langs"]) == {"en", "ja"}


def test_group_ignores_numbers_that_were_not_in_the_list():
    exps = [("p1", {"did": "a", "happened": "b", "topic": "t", "verdict": "fun"}), ("p2", {"did": "a", "happened": "b", "topic": "t", "verdict": "fun"})]
    g = insight.group(lambda p: json.dumps([{"title": "同じ体験", "ids": [0, 1, 7]}, {"title": "", "ids": [0]}]), "T", exps)
    assert g == [{"title": "同じ体験", "fits": "", "appeal": "", "members": ["p1", "p2"]}]


def test_titles_that_are_not_japanese_are_dropped():
    exps = [("p1", {"did": "a", "happened": "b", "topic": "t", "verdict": "fun"}), ("p2", {"did": "a", "happened": "b", "topic": "t", "verdict": "fun"})]
    g = insight.group(lambda p: json.dumps([{"title": "第二季遇到作弊者と不満", "ids": [0, 1]}, {"title": "Squad play is fun", "ids": [0, 1]},
                                            {"title": "分隊で拠点を奪うと逆転できる", "ids": [0, 1]}]), "T", exps)
    assert [x["title"] for x in g] == ["分隊で拠点を奪うと逆転できる"]


def test_statements_are_one_per_author_in_each_window(conn):
    """材料は、直近の窓と前の窓のそれぞれで投稿者ごとに 1 件（いちばん長いもの）。"""
    from game_signal_scout.repositories import insight as repo
    now = datetime.now(timezone.utc)
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) SELECT 'f', 'i' || g, now(), now(), '{}' FROM generate_series(1, 4) g")
    rows = [("i1", "a", now - timedelta(days=1), "x" * 80), ("i2", "a", now - timedelta(days=2), "y" * 120), ("i3", "a", now - timedelta(days=9), "z" * 90),
            ("i4", "b", now - timedelta(days=1), "w" * 70)]
    for i, au, at, text in rows:
        conn.execute("INSERT INTO player_post (source, item_id, at, author, lang, appid, matched_by, flags, text) VALUES ('f', %s, %s, %s, 'en', '7', 'source', '[]', %s)",
                     (i, at, au, text))
    conn.commit()
    got = repo.statements_by_author(conn, "7", 14, 60, now - timedelta(days=7), ["f"])
    assert sorted(r["item_id"] for r in got) == ["i2", "i3", "i4"]


def test_vague_actions_are_not_experiences():
    assert insight._clean_exp({"did": "ゲームをプレイした", "happened": "楽しかった", "verdict": "fun", "topic": "t"}) is None
    assert insight._clean_exp({"did": "遊んだ", "happened": "x", "verdict": "fun", "topic": "t"}) is None
    assert insight._clean_exp({"did": "大剣で溜め攻撃を連発した", "happened": "ボスを 1 回で倒せた", "verdict": "fun", "topic": "t"})["did"] == "大剣で溜め攻撃を連発した"


def test_style_and_caution_are_kept_only_when_most_of_the_group_agrees():
    posts = {p["item_id"]: p for p in [post(1, "a", 1), post(2, "b", 1), post(3, "c", 1)]}
    exps = {"p1": {"did": "d", "happened": "h", "verdict": "fun", "topic": "t", "style": "coop", "caution": None},
            "p2": {"did": "d", "happened": "h", "verdict": "fun", "topic": "t", "style": "coop", "caution": "online"},
            "p3": {"did": "d", "happened": "h", "verdict": "frustration", "topic": "t", "style": "solo", "caution": None}}
    f = insight.tally([{"title": "2 人で拠点を守ると連携できる", "fits": "決まった仲間と遊べる人", "members": ["p1", "p2", "p3"]}], posts, exps, SINCE, 2)[0]
    assert f["style"] == "coop" and f["caution"] is None and f["input"] is None and f["fits"] == "決まった仲間と遊べる人"
    assert f["frustration"] == 1      # 反対の声の人数も残す
    assert insight._clean_exp({"did": "大剣で溜め攻撃", "happened": "ボスを倒せた", "verdict": "fun", "topic": "t", "style": "deep"})["style"] is None   # 決まりにない値は付けない


def test_two_people_make_a_find_and_one_person_stays_a_labeled_single():
    """人数は目安: 2 人で発見。重ならない 1 人の体験は「ひとりの体験」として残す（数で捨てない）。"""
    posts = {p["item_id"]: p for p in [post(1, "a", 1), post(2, "b", 1), post(3, "c", 1)]}
    exps = {k: {"did": f"d{k}", "happened": "h", "verdict": "fun", "topic": "t"} for k in posts}
    f = insight.tally([{"title": "拠点を奪うと逆転できる", "members": ["p1", "p2"]}], posts, exps, SINCE, 2)
    assert len(f) == 1 and f[0]["people"] == 2
    one = insight.singles(posts, exps, {"p1", "p2"}, SINCE)
    assert [e["did"] for e in one] == ["dp3"]


def test_untranslated_or_abstract_text_is_not_used():
    assert insight._clean_exp({"did": "後期進行數值膨脹的爽快遊玩", "happened": "前期受挫但後期變得非常爽快", "verdict": "fun", "topic": "t"}) is None
    exps = [("p1", {"did": "a", "happened": "b", "topic": "t", "verdict": "fun"}), ("p2", {"did": "a", "happened": "b", "topic": "t", "verdict": "fun"})]
    g = insight.group(lambda p: json.dumps({"groups": [{"title": "コンテンツの量や、探索の充実度を評価する。", "ids": [0, 1]},
                                                       {"title": "斬馬刀でボスに挑むと、ほぼ一方的に押し切れる", "ids": [0, 1]}]}), "T", exps)
    assert [x["title"] for x in g] == ["斬馬刀でボスに挑むと、ほぼ一方的に押し切れる"]


def test_one_failed_batch_does_not_lose_the_others():
    rows = [post(i, f"a{i}", 1) for i in range(12)]
    calls = []
    def ask(p):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("500")
        return json.dumps({"items": [{"id": j, "exp": {"did": "大剣で溜め攻撃を連発した", "happened": "ボスを倒せた", "verdict": "fun", "topic": "t"}} for j in range(6)]})
    got = insight.read_statements(ask, "T", rows)
    assert set(got) == {f"p{i}" for i in range(6, 12)}


def test_material_is_taken_from_every_source_in_turn(conn):
    """材料は取得元を順番に取る（件数の多い取得元が占めない）。"""
    from game_signal_scout.repositories import insight as repo
    now = datetime.now(timezone.utc)
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) SELECT s, s || g, now(), now(), '{}' "
                 "FROM (VALUES ('big'), ('small')) v(s), generate_series(1, 5) g")
    for s, n in (("big", 5), ("small", 2)):
        for g in range(1, n + 1):
            conn.execute("INSERT INTO player_post (source, item_id, at, author, lang, appid, matched_by, flags, text) VALUES (%s, %s, %s, %s, 'en', '9', 'source', '[]', %s)",
                         (s, f"{s}{g}", now - timedelta(days=1), f"{s}-a{g}", "x" * (100 + g)))
    conn.commit()
    got = repo.statements_by_author(conn, "9", 14, 3, now - timedelta(days=7), ["big", "small"])
    assert sorted(r["item_id"][:3] for r in got) == ["big", "big", "sma"]
    assert all(r["item_id"].startswith("big") for r in repo.statements_by_author(conn, "9", 14, 3, now - timedelta(days=7), ["big"]))   # 集計に入れていない取得元は使わない


def test_posts_of_sources_not_in_use_are_marked_and_unmarked(conn):
    """無効・利用条件で停止の取得元の保存済みの発言は印で外し、再び使えば印を外す（消さない）。"""
    from game_signal_scout.repositories import post as post_repo
    now = datetime.now(timezone.utc)
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES ('on', '1', now(), now(), '{}'), ('off', '1', now(), now(), '{}')")
    for s in ("on", "off"):
        conn.execute("INSERT INTO player_post (source, item_id, at, author, lang, appid, matched_by, flags, text) VALUES (%s, '1', %s, 'a', 'en', '9', 'source', '[]', 'x')", (s, now))
    assert post_repo.mark_not_in_use(conn, ["on"]) == 1
    flags = dict(conn.execute("SELECT source, flags FROM player_post").fetchall())
    assert flags["off"] == ["not_in_use"] and flags["on"] == []
    post_repo.mark_not_in_use(conn, ["on", "off"])
    assert dict(conn.execute("SELECT source, flags FROM player_post").fetchall())["off"] == []


def test_finds_document_uses_only_public_keys():
    """見つけた面白さの公開文書は、公開しない項目名（did・generated_at など）を使わない（2026-11-09 これで公開が止まった）。"""
    from game_signal_scout.signal import content
    ev = content._pub_ev({"did": "スナイパーで頭を撃ち抜いた", "happened": "快感があった", "verdict": "fun", "appeal": "頭を撃ち抜いた瞬間がたまらない"})
    doc = {"finds": {"items": [{"id": "w1", "finds": [{"title": "t", "examples": [ev]}], "singles": [ev], "since": "2026-11-01"}]}}
    assert content.audit_public(doc, "pages") == []
    assert ev["act"] and ev["result"] and "did" not in ev and "happened" not in ev


def test_work_finds_split_fun_and_frustration_and_stay_public(monkeypatch):
    """作品詳細とダッシュボードに添える面白さ（good）と買う前に知っておきたいこと（warn）: 不満だけを warn に、公開しない項目名を使わない（#2）。"""
    from game_signal_scout.signal import content
    from game_signal_scout.repositories import insight as insight_repo
    ex = lambda d, h: {"did": d, "happened": h}  # noqa: E731
    body = {"kind": "finds", "read_people": 40, "experiences": 9, "window_days": 7, "since": "2026-11-02T00:00:00",
            "finds": [{"appeal": "仲間と作戦が決まる", "appeal_kind": "team", "verdict": "fun", "people": 3, "frustration": 1, "examples": [ex("拠点を作った", "守り切れた")]},
                      {"appeal": "", "verdict": "frustration", "people": 2, "caution": "bugs", "examples": [ex("起動した", "落ちた")]},
                      {"appeal": "賛否のある体験", "verdict": "mixed", "people": 2, "caution": "time", "examples": [ex("長く遊んだ", "時間が溶けた")]}],
            "singles": [{"appeal": "予想外の展開", "appeal_kind": "surprise", "verdict": "fun", "did": "橋を渡った", "happened": "崩れた"}]}
    monkeypatch.setattr(insight_repo, "all_insights", lambda conn: {"123": body, "456": {"kind": "other"}})
    ctx = type("C", (), {"conn": type("K", (), {"rollback": lambda self: None})()})()
    wf = content.work_finds(ctx)
    assert list(wf) == [123]
    f = wf[123]
    assert [x["appeal"] for x in f["good"]] == ["仲間と作戦が決まる", "賛否のある体験", "予想外の展開"]   # 不満を除き、人数の多い順
    assert [x["act"] for x in f["warn"]] == ["起動した"]                                                     # 不満だけ（賛否の注意は入れない）
    assert f["good"][0]["against"] == 1 and f["read_people"] == 40
    assert content.audit_public({"finds": f, "lead": {"finds": {"good": f["good"][:3]}}}, "work") == []
    assert content.work_finds(ctx) is wf                                                                   # 1 回の事前計算で 1 度だけ読む


def test_work_and_dashboard_show_finds_only_when_read():
    """作品詳細は W.finds があるときだけ面白さと買う前に知っておきたいことを出し、ダッシュボードは今日の兆しの作品の上位 3 件を兆しの下に出す（#2）。並びは変えない。"""
    from pathlib import Path
    root = Path(__file__).parents[1] / "src/game_signal_scout"
    wj = (root / "web/static/work.js").read_text()
    assert "const finds = WF && (WF.good.length || WF.warn.length)" in wj and "<div class=\"wk-grid\">${finds}${trend}" in wj
    assert "この作品でプレイヤーが見つけた面白さ" in wj and "買う前に知っておきたいこと" in wj
    dj = (root / "web/static/dashboard.js").read_text()
    lead = dj[dj.index('$("lead").innerHTML'):dj.index('${others}')]
    assert "LF ?" in lead and "この作品で、プレイヤーがしたこと・起きたこと" in lead
    c = (root / "signal/content.py").read_text()
    assert 'd == ctx.pdays[-1]' in c and 'wf["good"][:3]' in c                                              # 読み取りは直近の発言なので最新の日だけ


def test_finds_filter_keeps_kinds_and_counts_and_shows_the_result():
    """注目の作品の絞り込み（#7-A）: 種類と件数は実データ（体験のある種類だけ・作品数）、押すと ?k= で絞り、選んだ結果と解除を出す。日本語の凡例は絞り込みと別の枠。"""
    from pathlib import Path
    js = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/finds.js").read_text()
    for k in ("conquer", "explore", "story", "grow", "team", "versus", "feel", "surprise"):
        assert f"{k}: [" in js                                                                        # 分類は変えない
    assert 'href="finds.html?k=${k}"' in js and 'aria-current="true"' in js and 'class="fk-now" role="status"' in js
    assert '<div class="fk-box">' in js and '<div class="flg">' in js and js.index('<div class="fk-box">') < js.index('<div class="flg">')
    assert "filter(xs => xs.some(x => x.kind === k)).length" in js                                    # 件数は実データの作品数


def test_work_chart_does_not_stretch_to_the_side_column():
    """作品詳細の話題の動き（#7-B）: 棒は右の段の高さまで伸ばさない（PC 200px・狭い幅 140px）。言語圏は多い順に 8 まで、残りは開いて見られる（消さない）。"""
    from pathlib import Path
    root = Path(__file__).parents[1] / "src/game_signal_scout/web/static"
    css = (root / "work.css").read_text()
    tail = css[css.index("/* 話題の動きの棒の大きさ（#7-B）"):]
    assert ".wk-tr { align-items: start; }" in tail and "height: 200px" in tail and "height: 140px" in tail and "overflow: hidden" not in tail
    js = (root / "work.js").read_text()
    assert "const LMAX = 8;" in js and '<details class="wk-lx">' in js and "ls.slice(LMAX)" in js


def test_english_translation_keeps_numbers_and_drops_bad_answers():
    """英語の表示（#2）: 画面に出す日本語の文だけを訳す。数字を落とした訳・日本語の残る訳・壊れた応答は入れず、次の回に訳し直す。訳した文は訳し直さない。"""
    body = {"finds": [{"appeal": "仲間と作戦が決まる", "examples": [{"did": "4500kmを走った", "happened": "配送が消えた"}]}],
            "singles": [{"appeal": "", "did": "橋を渡った", "happened": "崩れた"}]}
    texts = insight.public_texts(body)
    assert texts == ["仲間と作戦が決まる", "4500kmを走った", "配送が消えた", "橋を渡った", "崩れた"]
    asked = []

    def ask(p):
        asked.append(p)
        return json.dumps({"items": [{"id": 0, "en": "Plans with friends click"}, {"id": 1, "en": "Drove a long way"},    # 数字を落とした → 入れない
                                     {"id": 2, "en": "配送 vanished"}, {"id": 3, "en": "Crossed the bridge"}]})               # 日本語が残る → 入れない（4 は答えなし）
    en = insight.translate_en(ask, "T", texts, {"崩れた": "It collapsed"})
    assert en == {"崩れた": "It collapsed", "仲間と作戦が決まる": "Plans with friends click", "橋を渡った": "Crossed the bridge"}
    assert "崩れた" not in asked[0]                                                                            # 訳した文は訳し直さない
    assert insight.translate_en(lambda p: "壊れた応答", "T", ["配送が消えた"]) == {}


def test_public_documents_carry_english_only_when_translated():
    """公開の文書（#2）: 訳のある文にだけ act_en・result_en・appeal_en を添える。訳がなければ付けない（画面は元の文を出す）。"""
    from game_signal_scout.signal import content
    ev = content._pub_ev({"did": "橋を渡った", "happened": "崩れた", "appeal": "予想外"}, {"橋を渡った": "Crossed the bridge", "崩れた": "It collapsed"})
    assert ev["act_en"] == "Crossed the bridge" and ev["result_en"] == "It collapsed" and "appeal_en" not in ev
    assert content.audit_public({"finds": {"items": [{"id": "w1", "singles": [ev]}]}}, "pages") == []
    from pathlib import Path
    root = Path(__file__).parents[1] / "src/game_signal_scout/web/static"
    assert 'const tx = (o, k) => (o ? (lang === "en" && o[`${k}_en`]) || o[k] || "" : "");' in (root / "common.js").read_text()
    for f in ("finds.js", "work.js", "dashboard.js"):
        assert 'tx(' in (root / f).read_text()


def test_attributes_are_rebuilt_when_the_item_is_fetched_again(conn):
    """取り直した項目（受け取った時刻が属性より新しい）は属性を作り直す（開発元の英語の名前が入らなかった: #2 2026-11-09）。新しくない項目は作り直さない。"""
    from game_signal_scout.repositories import catalog
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES "
                 "('s', 'old', now(), now() - interval '2 days', '{}'), ('s', 'new', now(), now(), '{}'), ('s', 'none', now(), now(), '{}')")
    conn.execute("INSERT INTO game_attribute (appid, key, source, item_id, value, fetched_at) VALUES "
                 "('1', 'k', 's', 'old', '[]', now() - interval '2 days'), ('2', 'k', 's', 'new', '[]', now() - interval '2 days')")
    assert sorted(r[0] for r in catalog.attribute_rows(conn, "s", 10)) == ["new", "none"]


def test_llm_lengths_come_from_the_config_not_the_code():
    """共有の LLM に渡す文脈の長さ・出力の長さは設定から読む（#3: Anime と交互に枠を取るたびにモデルを読み直していた。コードに数字を書かない）。"""
    from pathlib import Path
    from game_signal_scout.config import load_daily_config
    root = Path(__file__).parents[1] / "src/game_signal_scout"
    for f in ("services/insight.py", "ops/runner.py"):
        t = (root / f).read_text()
        assert '"num_ctx": 8192' not in t and '"num_predict": 2048' not in t
    ic = load_daily_config()["insight"]
    assert int(ic["num_ctx"]) > 0 and int(ic["num_predict"]) > 0


def test_work_trend_is_one_series_without_source_switch():
    """作品詳細の話題の動き（#7 2026-11-09）: 出典の切り替えはなく、作品全体の 1 つの系列。人数は出典ごとの合計と明記し、出典はグラフの下の説明に残す。"""
    from pathlib import Path
    root = Path(__file__).parents[1] / "src/game_signal_scout"
    c = (root / "signal/content.py").read_text()
    assert "streams = [_stream_all(ctx, w, hist, per)] if per else []" in c and '"scope": "source"' in c
    js = (root / "web/static/work.js").read_text()
    assert "st.all ? srcNote(st)" in js and "人数は出典ごとに数えた人数の合計" in js and "変化を見つけた出典の中で数えた数" in js
