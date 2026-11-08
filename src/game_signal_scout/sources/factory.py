"""取得元を作る唯一の入口（Factory。Anime の sources/factory と同じ考え方）。

取得元のクラスは記述（config/sources.toml の adapter = "module:Class"）から引き、同じ引数（設定・取得の部品）で作る。
取得元の名前で分岐しない。
"""
from __future__ import annotations

import importlib

from game_signal_scout import config
from game_signal_scout.sources.contract import SourceReader


def load_sources_config() -> dict:
    """取得元の記述（既定は config/sources.toml。GSS_SOURCES_CONFIG で別のファイル: 検証・試験で有効にする取得元を替える）。"""
    import os
    import tomllib
    alt = os.environ.get("GSS_SOURCES_CONFIG")
    if alt:
        with open(alt, "rb") as f:
            return tomllib.load(f)
    return config.load_toml("sources.toml")


def sources(cfg: dict | None = None) -> list[str]:
    """日次の collect で収集する取得元（記述があり、enabled が false でなく、常駐〔resident = true〕でなく、利用条件で禁止されていないもの。常駐は ops/collector が読む）。"""
    from game_signal_scout import source_terms
    cfg = cfg if cfg is not None else load_sources_config()
    return [name for name, sec in cfg.items() if isinstance(sec, dict) and sec.get("adapter") and sec.get("enabled", True) and not sec.get("resident")
            and source_terms.allowed(name)]


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



# ---- 取得しない用途の部品（Anime の sources/factory と同じ: 画面の引用の可否・URL・内部の識別子の印）
_READERS: dict[str, SourceReader | None] = {}


def reader_for(source: str | None) -> SourceReader | None:
    """取得しない用途の取得元（1 process に 1 つ）。記述のない取得元は None（呼ぶ側は既定の扱い）。"""
    if not source:
        return None
    if source not in _READERS:
        try:
            _READERS[source] = create(source, None)
        except Exception:  # noqa: BLE001 — 記述・設定のない取得元
            _READERS[source] = None
    return _READERS[source]


def permalink(source: str | None, item_id: str, url: str | None = None) -> str | None:
    """発言の公開の URL（取得元の permalink。取得元がなければ保存した url のうち https のもの）。ID を URL の代わりに返さない。"""
    reader = reader_for(source)
    if reader:
        return reader.permalink({"item_id": item_id, "url": url})
    return url if url and str(url).startswith("https://") else None


def internal_id_markers() -> tuple:
    """記述のあるすべての取得元の、公開してはいけない内部の識別子の印（クラスの属性。取得元を作らない）。"""
    cfg = load_sources_config()
    out = []
    for name, sec in cfg.items():
        if isinstance(sec, dict) and sec.get("adapter"):
            try:
                out += list(reader_class(name, cfg).internal_id_markers)
            except (ImportError, AttributeError, ValueError):
                continue
    return tuple(dict.fromkeys(out))
