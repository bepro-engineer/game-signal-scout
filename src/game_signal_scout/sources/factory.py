"""取得元を作る唯一の入口（Factory。Anime の sources/factory と同じ考え方）。

取得元のクラスは記述（config/sources.toml の adapter = "module:Class"）から引き、同じ引数（設定・取得の部品）で作る。
取得元の名前で分岐しない。
"""
from __future__ import annotations

import importlib

from game_signal_scout import config
from game_signal_scout.sources.contract import SourceReader


def load_sources_config() -> dict:
    return config.load_toml("sources.toml")


def sources(cfg: dict | None = None) -> list[str]:
    cfg = cfg if cfg is not None else load_sources_config()
    return [name for name, sec in cfg.items() if isinstance(sec, dict) and sec.get("adapter")]


def reader_class(source: str, cfg: dict | None = None) -> type[SourceReader]:
    cfg = cfg if cfg is not None else load_sources_config()
    spec = (cfg.get(source) or {}).get("adapter")
    if not spec:
        raise ValueError(f"取得元の記述がない: {source}（config/sources.toml に adapter = \"module:Class\" を書く）")
    module, name = spec.split(":")
    return getattr(importlib.import_module(module), name)


def create(source: str, http, cfg: dict | None = None) -> SourceReader:
    cfg = cfg if cfg is not None else load_sources_config()
    reader = reader_class(source, cfg)(dict(cfg[source]), http)
    reader.name = source
    return reader
