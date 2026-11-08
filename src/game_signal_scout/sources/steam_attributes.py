"""作品の属性の取得元: Steam のストアの言語の対応と開発元（IStoreBrowseService/GetItems。キー不要・50 作品ずつ）。

言語は、ストアが言語ごとに示す 3 つ（UI〔supported〕・字幕〔subtitles〕・音声〔full_audio〕）を分けて持つ。
ストアの一覧に日本語がなければ「ストアの表記では非対応」（listed = false）。取得できなかった作品は属性を作らない（画面は未確認）。
"""
from __future__ import annotations

import json
import urllib.parse
from collections.abc import Iterator
from datetime import datetime, timezone

from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json={q}"
JAPANESE = 10     # Steam の言語の番号（ELanguage）の日本語


class SteamAttributes(SourceReader):
    conn = None

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        from game_signal_scout.repositories import catalog
        apps = [str(a) for a in self.settings.get("appids") or []] or (
            catalog.attribute_targets(self.conn, self.name, int(self.settings.get("refresh_days", 14))) if self.conn is not None else [])
        now = datetime.now(timezone.utc)
        for i in range(0, len(apps), 50):
            chunk = apps[i:i + 50]
            q = {"ids": [{"appid": int(a)} for a in chunk], "context": {"language": "japanese", "country_code": "JP"},
                 "data_request": {"include_basic_info": True, "include_supported_languages": True}}
            body = self.http.get_json(self.name, URL.format(q=urllib.parse.quote(json.dumps(q, separators=(",", ":")))))
            items = []
            for it in ((body or {}).get("response") or {}).get("store_items") or []:
                if not it.get("appid") or not it.get("supported_languages"):
                    continue
                ja = next((x for x in it["supported_languages"] if x.get("elanguage") == JAPANESE), None)
                info = it.get("basic_info") or {}
                p = {"appid": str(it["appid"]),
                     "ja": {"listed": ja is not None, "ui": bool(ja and ja.get("supported")), "subtitles": bool(ja and ja.get("subtitles")),
                            "audio": bool(ja and ja.get("full_audio"))},
                     "developers": [d["name"] for d in info.get("developers") or [] if d.get("name")],
                     "publishers": [d["name"] for d in info.get("publishers") or [] if d.get("name")]}
                items.append(SourceItem(self.name, p["appid"], now, p, json.dumps(p, sort_keys=True, ensure_ascii=False)))
            yield Batch(items, {"done": i + len(chunk), "total": len(apps)})

    @staticmethod
    def attributes(item_id: str, received_at, payload: dict) -> list[tuple[str, str, object]]:
        a = str(payload.get("appid") or item_id)
        out = [(a, "ja", payload.get("ja") or {})]
        if payload.get("developers"):
            out.append((a, "developers", payload["developers"]))
        if payload.get("publishers"):
            out.append((a, "publishers", payload["publishers"]))
        return out
