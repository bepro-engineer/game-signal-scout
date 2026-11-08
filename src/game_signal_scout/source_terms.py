"""取得元の利用条件（Anime の source_terms の考え方を、Game に要る最小の形にしたもの。#3 G2）。

正本は config/source_terms.toml（取得元ごとに、一次資料の URL・条項の要旨・確認日と、分類）。判定はこの 1 か所だけで、取得元の名前で分けない。
- 分類: explicitly_prohibited（自動の取得の禁止が明記）／conditional（条件つき。条件と実装の適合を記録）／explicitly_allowed／unconfirmed（根拠不足）。
- 取得を止めるのは、禁止が明記されたもの（explicitly_prohibited、または uses.collect が prohibited）だけ。未確認を禁止として扱わない（オーナーの指示 2026-11-08）。
- 公開の画面での原文の引用は、既定で出さない（public_quote が allowed と記録された取得元だけ）。
"""
from __future__ import annotations

from functools import lru_cache

PROHIBITED = "explicitly_prohibited"


@lru_cache(maxsize=1)
def terms() -> dict:
    from game_signal_scout import config
    return dict(config.load_toml("source_terms.toml").get("sources") or {})


def entry(source: str) -> dict:
    return dict(terms().get(source) or {})


def allowed(source) -> bool:
    """取得・集計に使ってよいか（禁止が明記されていなければ使う）。"""
    e = entry(str(source))
    return not (e.get("category") == PROHIBITED or str((e.get("uses") or {}).get("collect", "")).startswith("prohibited"))


def quote_allowed(source) -> bool:
    """公開の画面に原文を引用してよいか（既定: 出さない）。"""
    return str((entry(str(source)).get("uses") or {}).get("public_quote", "")).startswith("allowed")
