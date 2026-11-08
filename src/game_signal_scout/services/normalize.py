"""正規化の Service: 取得元の形の項目を、分析に使う共通の行にする。どの正規化を使うかは取得元の記述（config/sources.toml の normalizer）で選ぶ
（取得元の名前で分岐しない）。normalizer のない取得元は正規化しない。

- protondb: 報告 → player_report（遊べたか・機材構成の hash・記述）
- bluesky: 発言 → player_post（作品の同定: Steam のストアのリンクの app ID、なければ題名の一致。services/identify）
- steam_store: 作品の情報 → game_profile（画像・説明・ジャンル・遊び方・機種・日本語・発売日。取得元に依らない作品の項目）

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


# 遊び方（Steam のカテゴリの ID → 利用者の言葉）。作品を選ぶ切り口の正本はこの言葉で、取得元のカテゴリの名前を画面に出さない
STEAM_MODES = {2: "ひとりで遊べる", 9: "協力プレイ", 38: "協力プレイ", 39: "協力プレイ", 24: "画面分割・同じ画面で", 37: "画面分割・同じ画面で",
               49: "対戦", 36: "対戦", 47: "対戦", 28: "コントローラーで遊べる"}
STEAM_PLATFORMS = {"windows": "Windows", "mac": "Mac", "linux": "Linux・Steam Deck"}


def steam_store_row(item_id: str, received_at, p: dict) -> dict | None:
    if p.get("type") != "game" or not p.get("name"):
        return None
    modes = list(dict.fromkeys(STEAM_MODES[c["id"]] for c in p.get("categories") or [] if c.get("id") in STEAM_MODES))
    langs = p.get("supported_languages") or ""
    ja_text = "日本語" in langs if langs else None
    ja_voice = None
    if ja_text:
        i = langs.find("日本語")
        ja_voice = langs[i + 3:i + 40].lstrip().startswith("<strong>*</strong>")   # 「*」の印は音声も対応
    return {"appid": p.get("appid") or item_id, "source": "", "item_id": item_id, "title": p["name"], "summary": (p.get("short_description") or "").strip() or None,
            "image_url": p.get("header_image"), "genres": p.get("genres") or [], "modes": modes,
            "platforms": [label for k, label in STEAM_PLATFORMS.items() if (p.get("platforms") or {}).get(k)],
            "ja_text": ja_text, "ja_voice": ja_voice, "released": p.get("release_date"),
            "store_url": f"https://store.steampowered.com/app/{p.get('appid') or item_id}/", "fetched_at": received_at}


def steam_store(conn, source: str, settings: dict | None = None, batch: int = 500) -> int:
    """作品の情報（Steam のストア）→ game_profile。作品でない項目は飛ばす（行を作らない）。"""
    from game_signal_scout.repositories import catalog
    total, seen = 0, set()
    while rows := [r for r in catalog.unnormalized(conn, source, batch) if r[0] not in seen]:
        out = []
        for item_id, received_at, p in rows:
            seen.add(item_id)
            if row := steam_store_row(item_id, received_at, p):
                out.append({**row, "source": source})
        with conn.transaction():
            total += catalog.upsert(conn, out)
        conn.commit()
    return total


def steam_charts(conn, source: str, settings: dict | None = None, batch: int = 1000) -> int:
    """遊ばれている規模（Steam の順位）→ game_activity。"""
    from datetime import date
    from game_signal_scout.repositories import catalog
    total = 0
    while rows := catalog.activity_rows(conn, source, batch):
        out = [(p["appid"], date.fromisoformat(p["day"]), source, item_id, p.get("rank"), p.get("prev_rank"), p.get("peak_players")) for item_id, p in rows]
        with conn.transaction():
            total += catalog.insert_activity(conn, out)
        conn.commit()
        if len(rows) < batch:
            break
    return total


def normalize(conn, source: str = "protondb", batch: int = 5000) -> int:
    """ProtonDB: まだ正規化していない項目をすべて正規化する。入れた数（何度流しても、新しい項目がなければ 0）。"""
    total = 0
    while rows := repo.unnormalized(conn, source, batch):
        with conn.transaction():
            total += repo.normalize_new(conn, source, (protondb_row(i, p) for i, p in rows))
        conn.commit()
    return total
