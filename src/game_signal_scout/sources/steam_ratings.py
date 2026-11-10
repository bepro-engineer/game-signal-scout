"""作品のユーザー評価の取得元: Steam のストアのユーザーレビューの集計（IStoreBrowseService/GetItems の reviews。キー不要・50 作品ずつ）。#2 2026-11-10。

- 持つのはストアが示す集計だけ: 全期間（トピずれのレビューを除いた、ストアの既定の表示と同じ summary_filtered）と、
  日本語のレビューだけの集計（summary_language_specific。context の言語が日本語のとき）。それぞれ件数・好評の割合・評価の段階（1〜9）・評価の名前。
- 評価の名前は日本語と英語の両方（言語を変えて 2 回問い合わせ、段階ごとの名前を取る）。100 点への換算や、集めたレビューからの推定はしない。
- 最近 30 日の集計は、この問い合わせ先にない（ストアのページの文にだけある）。持たない。
- 取得できなかった作品は記録しない。件数が少なく評価の段階がない作品は、件数だけを持つ（段階・名前なし）。
利用条件は sources.steam_attributes と同じ API（config/source_terms.toml）。
"""
from __future__ import annotations

import json
import urllib.parse
from collections.abc import Iterator
from datetime import datetime, timezone

from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json={q}"
STORE = "https://store.steampowered.com/app/{appid}/#app_reviews_hash"


def summary(s: dict | None, label_en: dict) -> dict | None:
    """ストアの集計 1 つ → 共通の形 {n: 件数, pct: 好評の割合, score: 段階, label: {ja, en}}。件数がなければ None。"""
    if not isinstance(s, dict) or not s.get("review_count"):
        return None
    out = {"n": int(s["review_count"]), "pct": int(s.get("percent_positive") or 0)}
    if s.get("review_score") and s.get("review_score_label"):
        sc = int(s["review_score"])
        out.update(score=sc, label={"ja": s["review_score_label"], "en": label_en.get(sc) or s["review_score_label"]})
    return out


class SteamRatings(SourceReader):
    conn = None

    def _items(self, ids: list[str], language: str) -> dict[str, dict]:
        q = {"ids": [{"appid": int(a)} for a in ids], "context": {"language": language, "country_code": str(self.settings.get("country", "JP"))},
             "data_request": {"include_reviews": True}}
        body = self.http.get_json(self.name, URL.format(q=urllib.parse.quote(json.dumps(q, separators=(",", ":")))))
        if body is None:
            return {}
        return {str(it["appid"]): it.get("reviews") or {} for it in ((body.get("response") or {}).get("store_items") or []) if it.get("appid")}

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        from game_signal_scout.repositories import catalog
        apps = [str(a) for a in self.settings.get("appids") or []] or (catalog.all_appids(self.conn) if self.conn is not None else [])
        size = int(self.settings.get("batch_size", 50))
        for i in range(0, len(apps), size):
            chunk = apps[i:i + size]
            ja = self._items(chunk, "japanese")
            if not ja:
                continue                                  # 通信の失敗（記録は Fetcher.log）。次の回に取り直す
            en = self._items(chunk, "english")
            label_en = {int(s["review_score"]): s["review_score_label"] for r in en.values() for s in r.values()
                        if isinstance(s, dict) and s.get("review_score") and s.get("review_score_label")}
            now = datetime.now(timezone.utc)
            items = []
            for a, r in ja.items():
                v = {"all": summary(r.get("summary_filtered"), label_en), "lang": summary(r.get("summary_language_specific"), label_en)}
                if not v["all"]:
                    continue
                v = {**({"all": v["all"]}), **({"lang": {**v["lang"], "code": "ja"}} if v["lang"] else {}), "url": STORE.format(appid=a), "checked_at": now.isoformat()}
                p = {"appid": a, "rating": v}
                items.append(SourceItem(self.name, a, now, p, json.dumps(p, sort_keys=True, ensure_ascii=False)))   # 版に確かめた時刻を含める（鮮度を毎回更新）
            yield Batch(items, {"done": i + len(chunk), "total": len(apps)})

    @staticmethod
    def attributes(item_id: str, received_at, payload: dict) -> list[tuple[str, str, object]]:
        return [(str(payload.get("appid") or item_id), "rating", payload["rating"])] if payload.get("rating") else []
