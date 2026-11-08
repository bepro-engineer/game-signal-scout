"""発言の言語（取得元が言語を示さないとき）: 文字の種類で決まる言語は文字で、ほかは py3langid で推定する。短すぎる文は None。"""
from __future__ import annotations

import re

KANA = re.compile(r"[぀-ヿ]")
HANGUL = re.compile(r"[가-힯]")
HAN = re.compile(r"[一-鿿]")
THAI = re.compile(r"[฀-๿]")
TRAD = set("們這個說會為與來對時後從國發還點開關經過現樣變學問題讓實體邊頭東車長專業電話歡")


def detect(text: str | None) -> str | None:
    t = (text or "").strip()
    if len(t) < 3:
        return None
    if KANA.search(t):
        return "ja"
    if HANGUL.search(t):
        return "ko"
    if THAI.search(t):
        return "th"
    if HAN.search(t):
        return "zh-Hant" if any(c in TRAD for c in t) else "zh-Hans"
    try:
        import py3langid
        code, _ = py3langid.classify(t)
        return code
    except Exception:  # noqa: BLE001
        return None
