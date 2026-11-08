"""Anime の foundation/normalize の descriptors の Game 版: 観測の集計に入れる取得元（config/map_sources.toml）の数え方。
Game の共通の発言（player_post）は、作品（app ID）に結び付いた時点で数える（identified）。"""
from __future__ import annotations


def descriptors() -> dict[str, dict]:
    from game_signal_scout import config
    srcs = config.load_toml("map_sources.toml").get("sources") or {}
    return {s: {"counting": "identified", "store": "production", "finalize_partial": False} for s in srcs}
