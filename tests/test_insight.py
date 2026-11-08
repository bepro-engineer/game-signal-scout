"""プレイヤーの声の読み取り（services/insight）。LLM は呼ばない（読んだ結果を与える）。件数はこちらで数えることを確かめる。"""
from game_signal_scout.services import insight


def rows(n_pos, n_neg):
    return ([{"source": "s", "item_id": f"p{i}", "stance": "positive", "text": "fun " * (10 + i), "playtime_minutes": 600, "lang": "en"} for i in range(n_pos)] +
            [{"source": "s", "item_id": f"n{i}", "stance": "negative", "text": "crash " * (10 + i), "playtime_minutes": 30, "lang": "en"} for i in range(n_neg)])


def test_pick_balances_stances_and_caps_inputs():
    got = insight.pick(rows(100, 100))
    assert len(got) == insight.MAX_INPUTS and sum(r["stance"] == "negative" for r in got) == insight.MAX_INPUTS // 2


def test_read_batch_keeps_only_well_formed_answers(monkeypatch):
    monkeypatch.setattr(insight, "ask_llm", lambda *a, **k: '前置き [{"id": 1, "aspect": "fun", "stance": "good", "note": "楽しい"},'
                        '{"id": 2, "aspect": "nope", "stance": "good"}, {"id": 99, "aspect": "bugs", "stance": "bad"}, "x"] 以上')
    got = insight.read_batch("T", [(1, rows(1, 0)[0]), (2, rows(1, 0)[0])], "m", "o")
    assert got == {1: {"aspect": "fun", "stance": "good", "note": "楽しい"}}                # 知らない観点・範囲外の番号・形の崩れは捨てる


def test_tally_and_phenomena_are_counted_here_not_by_the_llm():
    reads = {i: {"aspect": "friends", "stance": "good", "note": "友だちと楽しい"} for i in range(1, 5)}
    reads |= {i: {"aspect": "bugs", "stance": "bad", "note": "落ちる"} for i in range(5, 9)}
    reads[9] = {"aspect": "fun", "stance": "good", "note": "1 人だけ"}
    t = insight.tally(reads)
    good = insight.points(t, reads, "good")
    assert [(p["aspect"], len(p["ids"])) for p in good] == [("friends", 4)]                # 1 人だけの点は出さない
    body = {"tally": {k: {"good": len(v["good"]), "bad": len(v["bad"])} for k, v in t.items()}, "stats": {"positive": 90, "negative": 5, "read": 9}}
    assert insight.phenomena(body, ranked=False) == ["friends", "gem", "caution"]
