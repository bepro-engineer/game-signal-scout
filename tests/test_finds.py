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
    assert g == [{"title": "同じ体験", "members": ["p1", "p2"]}]


def test_titles_that_are_not_japanese_are_dropped():
    exps = [("p1", {"did": "a", "happened": "b", "topic": "t", "verdict": "fun"}), ("p2", {"did": "a", "happened": "b", "topic": "t", "verdict": "fun"})]
    g = insight.group(lambda p: json.dumps([{"title": "第二季遇到作弊者と不満", "ids": [0, 1]}, {"title": "Squad play is fun", "ids": [0, 1]},
                                            {"title": "分隊で拠点を奪うと逆転できる", "ids": [0, 1]}]), "T", exps)
    assert [x["title"] for x in g] == ["分隊で拠点を奪うと逆転できる"]
