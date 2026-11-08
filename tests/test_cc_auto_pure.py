"""discovery.text.clean の振る舞い（DB・ネットワーク・ファイルを使わない純粋な関数）。"""
from game_signal_scout.discovery.text import clean


def test_clean_returns_empty_for_non_string():
    assert clean(None) == ""
    assert clean(123) == ""
    assert clean(["a"]) == ""


def test_clean_removes_nul_and_keeps_other_text():
    assert clean("ab\x00c\x00") == "abc"
    assert clean("ゲーム 🎮") == "ゲーム 🎮"


def test_clean_replaces_lone_surrogate_so_utf8_encodable():
    out = clean("a\ud800b")
    assert out == "a?b"
    out.encode("utf-8")
