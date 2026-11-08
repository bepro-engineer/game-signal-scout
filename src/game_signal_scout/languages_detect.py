"""発言の言語（取得元が言語を示さないとき）。すべての取得元で共通の判定器（discovery/lang.detect: 文字種 → langid、確信度 0.8 未満は uncertain）を使う
（Anime の §7。2026-11-08 Issue #3: 掲示板などは確信度の閾値なしで第 1 候補を採っていた）。中国語は文字で繁体字・簡体字を分ける。短すぎる文は None。"""
from __future__ import annotations

import re

HAN = re.compile(r"[\u4e00-\u9fff]")
KANA = re.compile(r"[\u3040-\u30ff]")
TRAD = set("們這個說會為與來對時後從國發還點開關經過現樣變學問題讓實體邊頭東車長專業電話歡")


def detect(text: str | None) -> str | None:
    from game_signal_scout.discovery.lang import detect as detect_lang
    t = (text or "").strip()
    if len(t) < 3:
        return None
    if HAN.search(t) and not KANA.search(t) and not re.search(r"[\uac00-\ud7af]", t):
        return "zh-Hant" if any(c in TRAD for c in t) else "zh-Hans"
    code, _prob, _how = detect_lang(t)
    return code
