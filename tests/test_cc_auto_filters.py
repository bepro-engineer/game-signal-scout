"""web/app.py の Jinja フィルタ pct・day・ts の試験（DB・ネットワークは使わない）。

フィルタは _ENV.filters から直接取り出して呼ぶ。テンプレートを通した呼び出しも 1 つずつ確かめる。
"""
from __future__ import annotations

import pytest

from game_signal_scout.web.app import _ENV

pct = _ENV.filters["pct"]
day = _ENV.filters["day"]
ts = _ENV.filters["ts"]


def render(src: str, **kw) -> str:
    return _ENV.from_string(src).render(**kw)


# pct: 割合（0〜1）を整数の百分率にする。
@pytest.mark.parametrize("x, want", [
    (0.5, "50%"),
    (0.123, "12%"),
    (0.126, "13%"),
    (1, "100%"),
    (1.5, "150%"),
    (-0.25, "-25%"),
])
def test_pct_normal(x, want):
    assert pct(x) == want


def test_pct_zero_is_zero_percent_not_dash():
    # 0 は空ではなく値。day・ts と違い「—」にはならない。
    assert pct(0) == "0%"
    assert pct(0.0) == "0%"


def test_pct_none_is_not_handled():
    # pct には空の値の扱いがない（None は掛け算できず TypeError になる）。今の振る舞いを固定する。
    with pytest.raises(TypeError):
        pct(None)


def test_pct_in_template():
    assert render("{{ v | pct }}", v=0.42) == "42%"


# day: ISO 8601 の文字列の日付の部分（先頭 10 文字）。空なら「—」。
@pytest.mark.parametrize("s, want", [
    ("2026-11-08T12:34:56Z", "2026-11-08"),
    ("2026-11-08T12:34:56.123456+00:00", "2026-11-08"),
    ("2026-11-08", "2026-11-08"),
    ("2026-11", "2026-11"),
])
def test_day_normal(s, want):
    assert day(s) == want


@pytest.mark.parametrize("s", [None, ""])
def test_day_empty_is_dash(s):
    assert day(s) == "—"


def test_day_in_template():
    assert render("{{ v | day }}", v="2026-01-02T03:04:05Z") == "2026-01-02"
    assert render("{{ v | day }}", v=None) == "—"


# ts: 日付と時:分に「UTC」を付ける。空なら「—」。
@pytest.mark.parametrize("s, want", [
    ("2026-11-08T12:34:56Z", "2026-11-08 12:34 UTC"),
    ("2026-11-08T00:00:00.999+00:00", "2026-11-08 00:00 UTC"),
    ("2026-11-08 23:59:59", "2026-11-08 23:59 UTC"),
])
def test_ts_normal(s, want):
    assert ts(s) == want


@pytest.mark.parametrize("s", [None, ""])
def test_ts_empty_is_dash(s):
    assert ts(s) == "—"


def test_ts_in_template():
    assert render("{{ v | ts }}", v="2026-01-02T03:04:05Z") == "2026-01-02 03:04 UTC"
    assert render("{{ v | ts }}", v="") == "—"
