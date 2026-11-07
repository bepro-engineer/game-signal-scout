"""正規化の Service: 取得元の形の項目を、分析に使う共通の行にする。どの正規化を使うかは取得元の記述（config/sources.toml の normalizer）で選ぶ
（取得元の名前で分岐しない）。normalizer のない取得元は正規化しない。

- protondb: 報告 → player_report（遊べたか・機材構成の hash・記述）
- bluesky: 発言 → player_post（作品の同定: Steam のストアのリンクの app ID、なければ題名の一致。services/identify）

ProtonDB の報告の対応:
- failed: 遊べない（verdict = no）か、起動しない（startsPlay = no）。検証P で事前に固定した定義。
- config_hash: 機材構成（CPU・GPU・カーネル・OS・メモリ）の hash。投稿者の ID がないので、独立した報告者の近似に使う。生の値は持たない。
- notes: 自由記述の欄をまとめたもの（分析の根拠の確認に使う。公開しない）。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from game_signal_scout.repositories import report as repo

CONFIG_KEYS = ("cpu", "gpu", "kernel", "os", "ram")


def failed(record: dict) -> bool:
    r = record.get("responses") or {}
    return r.get("verdict") == "no" or r.get("startsPlay") == "no"


def config_hash(record: dict) -> str:
    s = record.get("systemInfo") or {}
    return hashlib.sha256("|".join(str(s.get(k, "")) for k in CONFIG_KEYS).encode()).hexdigest()[:16]


def notes(record: dict) -> str:
    r = record.get("responses") or {}
    parts = [f"{k}: {v}" for k, v in (r.get("notes") or {}).items() if isinstance(v, str) and v.strip()]
    if isinstance(r.get("concludingNotes"), str) and r["concludingNotes"].strip():
        parts.append("concludingNotes: " + r["concludingNotes"])
    return " | ".join(parts)


def protondb_row(item_id: str, record: dict) -> tuple:
    r = record.get("responses") or {}
    app = record.get("app") or {}
    return (item_id, (app.get("steam") or {}).get("appId"), app.get("title"), datetime.fromtimestamp(record["timestamp"], timezone.utc),
            failed(record), config_hash(record), r.get("protonVersion") or r.get("customProtonVersion"), notes(record))


def normalize_all(conn, cfg: dict | None = None) -> dict[str, int]:
    """記述に normalizer のある取得元をすべて正規化する。取得元ごとの入れた数。"""
    import importlib
    from game_signal_scout.sources import factory
    cfg = cfg or factory.load_sources_config()
    out = {}
    for name, sc in cfg.items():
        ref = sc.get("normalizer") if isinstance(sc, dict) else None
        if not ref:
            continue
        mod, fn = ref.split(":")
        out[name] = getattr(importlib.import_module(mod), fn)(conn, name, sc)
    return out


def protondb(conn, source: str, settings: dict | None = None) -> int:
    return normalize(conn, source)


def bluesky(conn, source: str, settings: dict | None = None, batch: int = 2000) -> int:
    """発言を player_post にする。作品の辞書は ProtonDB の報告の題名から 1 回だけ作る。"""
    from game_signal_scout.repositories import post as post_repo
    from game_signal_scout.services.identify import TitleIndex, identify
    settings = settings or {}
    index = None
    total = 0
    while rows := post_repo.unnormalized(conn, source, batch):
        if index is None:
            index = TitleIndex(post_repo.known_titles(conn), settings.get("ambiguous_titles") or [],
                               settings.get("title_context_words") or settings.get("context_words") or [], int(settings.get("min_title_chars", 8)))
        out = []
        for item_id, occurred_at, p in rows:
            appid, title, how = identify(p, index)
            out.append({"source": source, "item_id": item_id, "at": occurred_at, "author": p.get("author") or "", "lang": p.get("lang"),
                        "appid": appid, "title": title, "matched_by": how, "flags": p.get("flags") or [], "text": p.get("text") or ""})
        with conn.transaction():
            total += post_repo.insert(conn, out)
        conn.commit()
    return total


def normalize(conn, source: str = "protondb", batch: int = 5000) -> int:
    """ProtonDB: まだ正規化していない項目をすべて正規化する。入れた数（何度流しても、新しい項目がなければ 0）。"""
    total = 0
    while rows := repo.unnormalized(conn, source, batch):
        with conn.transaction():
            total += repo.normalize_new(conn, source, (protondb_row(i, p) for i, p in rows))
        conn.commit()
    return total
