"""作品の画像の取得元: Steam のストアの画像の場所（IStoreBrowseService/GetItems の assets。キー不要）。縦長の表紙（library_capsule）と横長の帯（library_hero）、スクリーンショット（年齢の制限のない場面）。

画面の作品の画像の枠は縦長（Anime と同じ 3:4）なので、横長のヘッダーを切り抜かずに縦長の表紙を使う（なければ従来のヘッダー）。
画像は複製せず、URL だけを持つ（表示は利用者のブラウザが Steam の配信元から読む）。対象は作品の情報のある作品（50 作品ずつ 1 回の問い合わせ）。
"""
from __future__ import annotations

import json
import urllib.parse
from collections.abc import Iterator
from datetime import datetime, timezone

from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json={q}"
CDN = "https://shared.akamai.steamstatic.com/store_item_assets/"


MAX_SHOTS = 8


def shot_urls(screens: dict) -> list[str]:
    """スクリーンショットの場所（年齢の制限のない場面だけ。並びは配信元の順）。"""
    xs = sorted((screens or {}).get("all_ages_screenshots") or [], key=lambda x: x.get("ordinal") or 0)
    return [CDN + x["filename"] for x in xs if x.get("filename")][:MAX_SHOTS]


def asset_urls(assets: dict) -> dict:
    fmt = (assets or {}).get("asset_url_format") or ""
    url = lambda k: CDN + fmt.replace("${FILENAME}", assets[k]) if fmt and assets.get(k) else None
    return {"capsule": url("library_capsule_2x") or url("library_capsule"), "hero": url("library_hero")}


class SteamAssets(SourceReader):
    conn = None

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        from game_signal_scout.repositories import catalog
        apps = [str(a) for a in self.settings.get("appids") or []] or (catalog.all_appids(self.conn) if self.conn is not None else [])
        now = datetime.now(timezone.utc)
        for i in range(0, len(apps), 50):
            chunk = apps[i:i + 50]
            q = {"ids": [{"appid": int(a)} for a in chunk], "context": {"language": "japanese", "country_code": "JP"}, "data_request": {"include_assets": True, "include_screenshots": True}}
            body = self.http.get_json(self.name, URL.format(q=urllib.parse.quote(json.dumps(q, separators=(",", ":")))))
            items = []
            for it in ((body or {}).get("response") or {}).get("store_items") or []:
                if it.get("appid"):
                    u = {**asset_urls(it.get("assets") or {}), "shots": shot_urls(it.get("screenshots") or {})}
                    items.append(SourceItem(self.name, str(it["appid"]), now, {"appid": str(it["appid"]), **u}, json.dumps(u, sort_keys=True)))
            yield Batch(items, {"done": i + len(chunk), "total": len(apps)})
