"""Anime の foundation/normalize の descriptors の Game 版: 観測の集計に入れる取得元（config/map_sources.toml）の数え方。
Game の共通の発言（player_post）は、作品（app ID）に結び付いた時点で数える（identified）。"""
from __future__ import annotations


def descriptors() -> dict[str, dict]:
    from game_signal_scout import config
    srcs = config.load_toml("map_sources.toml").get("sources") or {}
    # text = stored: 本文を保存しているので、同じ書き出しの文の繰り返しで人数を増やさない検査（min_distinct_texts）を効かせる（Anime の §10。2026-11-08 Issue #3）
    return {s: {"counting": "identified", "store": "production", "finalize_partial": False, "text": "stored"} for s in srcs}
