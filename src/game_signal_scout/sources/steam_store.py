"""作品の情報の取得元: Steam のストアの作品情報（store.steampowered.com/api/appdetails。キー不要・日本語）。レビューは取らない。

- 読むのは「作品の情報を揃える対象の作品」だけ（repositories/catalog.targets: プレイヤーの報告・発言の多い作品のうち、情報がない・古いもの）。
  対象は収集の Service が渡す接続（self.conn）から引く。取得元の名前で共通の処理を分けない。
- 1 作品 1 回の取得（最小の間隔は Fetcher の min_interval）。束は batch_size 件ごと（途中で落ちても、保存した作品は取り直さない）。
- 保存するのは、作品を選ぶのに使う項目だけ（名前・種類・短い説明・画像の URL・ジャンル・カテゴリ・機種・発売日・言語）。
- 作品でない・取れなかった app ID も「取れなかった」として保存する（毎日取りに行かない。refresh_days の後に取り直す）。
画像は Steam の CDN の URL を持つだけで、複製しない（表示は利用者のブラウザが Steam から読む）。利用条件は Issue #2 の調査のとおり未確定（非公開の試作）。
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import datetime, timezone

from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

URL = "https://store.steampowered.com/api/appdetails?appids={appid}&l=japanese&cc=jp"
KEEP = ("type", "name", "short_description", "header_image", "genres", "categories", "platforms", "release_date", "supported_languages", "controller_support")


def pick(data: dict) -> dict:
    out = {k: data.get(k) for k in KEEP if k in data}
    out["genres"] = [g.get("description") for g in data.get("genres") or [] if g.get("description")]
    out["categories"] = [{"id": c.get("id"), "description": c.get("description")} for c in data.get("categories") or []]
    out["release_date"] = (data.get("release_date") or {}).get("date")
    return out


class SteamStore(SourceReader):
    conn = None     # 収集の Service が渡す（対象の作品を引く）

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        from game_signal_scout.repositories import catalog
        s = self.settings
        todo = catalog.targets(self.conn, int(s.get("active_days", 90)), int(s.get("max_games", 150)), int(s.get("refresh_days", 30)), self.name) if self.conn else []
        size = int(s.get("batch_size", 20))
        items: list[SourceItem] = []
        for i, appid in enumerate(todo, 1):
            body = self.http.get_json(self.name, URL.format(appid=appid))
            if body is None:
                continue                      # 通信の失敗（記録は Fetcher.log）。次の回に取り直す
            entry = (body or {}).get(str(appid)) or {}
            payload = pick(entry["data"]) if entry.get("success") and isinstance(entry.get("data"), dict) else {"type": None, "unavailable": True}
            payload["appid"] = str(appid)
            version = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            items.append(SourceItem(self.name, str(appid), datetime.now(timezone.utc), payload, version))
            if len(items) >= size or i == len(todo):
                yield Batch(items, {"last_appid": str(appid), "done": i, "total": len(todo)})
                items = []
        if items:
            yield Batch(items, {"done": len(todo), "total": len(todo)})
